# 골든셋을 Langfuse Dataset으로 올리고, 실행마다 run을 남긴다. (M6-c)
#
# 실행 (backend/에서):
#   uv run python -m evals.langfuse_dataset --upload              # 업로드만 (무료)
#   uv run python -m evals.langfuse_dataset --experiment          # 실행 + 채점 (API 비용 발생)
#   uv run python -m evals.langfuse_dataset --experiment --limit 5
#
# ★ 왜 로컬 마크다운만으로는 부족한가 ★
# evals/results/의 파일들은 "이번에 얼마가 나왔나"는 잘 보여주지만, 3주 뒤에 "설정 A와
# 설정 B 중 뭐가 나았지"를 답하기 어렵다. 파일 이름과 표를 사람이 눈으로 대조해야 하고,
# 질문 하나가 왜 실패했는지 보려면 그때의 프롬프트·검색 결과가 필요한데 마크다운에는 없다.
# Langfuse Dataset은 run끼리의 비교와 **개별 항목의 트레이스**를 UI에서 묶어준다 —
# M4에서 이미 붙여놨으므로 여기서는 공짜다.
#
# ★ v4 API 실측 ★ 예전 langfuse 예제의 `for item in dataset.items: with item.run(...)`
# 패턴은 v4에 없다. `dataset.run_experiment(name=..., task=..., evaluators=[...])` 하나로
# 바뀌었고, 동시 실행·run 생성·score 기록을 라이브러리가 대신한다.
import argparse
import sys

from anthropic import AsyncAnthropic
from langchain_anthropic import ChatAnthropic
from langfuse import Evaluation
from langgraph.checkpoint.memory import InMemorySaver

from app.core.config import settings
from app.core.tracing import get_langfuse_client
from app.graph import build_graph
from app.rag.access import Principal
from app.rag.embedding import embed_query
from app.rag.factory import get_store
from evals.judge import judge
from evals.metrics import hit_at_k, reciprocal_rank
from evals.run_retrieval import Case, load_dataset, validate_dataset

DATASET_NAME = "rag-golden-set"

# ★ 동시 실행을 낮게 잡는다 ★ 기본값은 50인데, 그러면 임베딩(CPU) 50개가 동시에 돌고
# Anthropic 레이트리밋에도 걸린다. 평가는 지연이 상관없는 배치 작업이라 느려도 된다.
MAX_CONCURRENCY = 4


def upload(cases: list[Case]) -> None:
    client = get_langfuse_client()
    client.create_dataset(
        name=DATASET_NAME,
        description="react-python 문서 RAG 골든셋 (normal / keyword / unanswerable)",
    )
    for case in cases:
        # ★ id를 우리 케이스 id로 고정하는 것이 핵심이다 ★ 안 주면 Langfuse가 매번
        # 새 항목을 만들어서, 골든셋을 두 번 올리면 48건짜리 데이터셋이 된다.
        # 고정하면 재업로드가 덮어쓰기가 된다 — Qdrant에서 uuid5를 쓴 것과 같은 이유다.
        client.create_dataset_item(
            dataset_name=DATASET_NAME,
            id=case.id,
            input={"question": case.question},
            expected_output={
                "sources": case.expected_sources,
                "substrings": case.expected_substrings,
            },
            metadata={"kind": case.kind, "answerable": case.answerable},
        )
    client.flush()
    print(f"업로드 완료: {DATASET_NAME} ({len(cases)}건)")


def build_task(graph):
    async def task(*, item, **kwargs):
        """데이터셋 항목 하나를 프로덕션 그래프에 통과시킨다.

        반환값은 Langfuse에 그대로 저장되므로 JSON 직렬화가 되어야 한다 —
        RetrievedChunk(dataclass)를 그대로 넣으면 조용히 문자열로 뭉개진다.
        """
        question = item.input["question"]
        state = await graph.ainvoke(
            {"messages": [{"role": "user", "content": question}], "principal": Principal()},
            {"configurable": {"thread_id": f"lf-eval-{item.id}"}},
        )
        return {
            "answer": state["messages"][-1].text,
            "context": state.get("retrieved_context") or "",
        }

    return task


def build_retrieval_evaluator(store):
    """검색 지표를 항목마다 점수로 남긴다. LLM을 안 부르므로 공짜다."""

    def evaluate(*, input, output, expected_output, metadata, **kwargs):
        substrings = (expected_output or {}).get("substrings") or []
        if not substrings:
            # unanswerable은 정답 청크가 없어서 hit@k도 MRR도 정의되지 않는다.
            # 0점으로 기록하면 "검색이 나쁘다"로 오해되므로 아예 점수를 남기지 않는다.
            return []
        chunks = store.search(embed_query(input["question"]), Principal())
        relevance = [any(s in c.content for s in substrings) for c in chunks]
        return [
            Evaluation(name="hit@5", value=float(hit_at_k(relevance, 5)), data_type="NUMERIC"),
            Evaluation(name="mrr", value=reciprocal_rank(relevance), data_type="NUMERIC"),
        ]

    return evaluate


def build_judge_evaluator(client: AsyncAnthropic):
    """LLM-as-judge 점수를 남긴다. ★ 여기서 비용이 발생한다 ★"""

    async def evaluate(*, input, output, expected_output, metadata, **kwargs):
        case = Case(
            id="",
            kind=(metadata or {}).get("kind", "normal"),
            question=input["question"],
            expected_sources=[],
            expected_substrings=[],
        )
        verdict = await judge(client, case, output["answer"], output["context"] or "(없음)")
        return [
            Evaluation(
                name="faithfulness",
                value=float(verdict.faithfulness),
                comment=verdict.faithfulness_reason,
                data_type="NUMERIC",
            ),
            Evaluation(
                name="answer_relevance",
                value=float(verdict.answer_relevance),
                comment=verdict.answer_relevance_reason,
                data_type="NUMERIC",
            ),
            # 거절은 점수가 아니라 사실이라 BOOLEAN으로 남긴다. unanswerable에서는
            # true가 정답이고 normal/keyword에서는 false가 정답이라, 하나의 숫자로
            # 뭉개면 방향이 반대인 두 가지가 섞인다.
            Evaluation(name="refused", value=verdict.refused, data_type="BOOLEAN"),
        ]

    return evaluate


def run_experiment() -> None:
    # ★ asyncio.run을 직접 부르지 않는다 ★ run_experiment가 동기/비동기 task와
    # evaluator를 모두 받아 내부에서 이벤트 루프와 동시성을 관리한다(실측).
    # judge.py가 asyncio.run을 직접 부르는 것과 다른 점이고, 라이브러리가 해주는 일을
    # 다시 하지 않는 편이 낫다.
    client = get_langfuse_client()
    dataset = client.get_dataset(DATASET_NAME)

    store = get_store(None)
    model = ChatAnthropic(
        model=settings.anthropic_model,
        api_key=settings.anthropic_api_key,
        max_tokens=1024,
        streaming=True,
    )
    graph = build_graph(
        model,
        retrieve_fn=lambda q, principal=None: store.search(embed_query(q), Principal()),
        checkpointer=InMemorySaver(),
    )
    anthropic_client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    result = dataset.run_experiment(
        name=f"{settings.vector_store} / {settings.anthropic_model}",
        description=(
            f"store={settings.vector_store} · answer={settings.anthropic_model} "
            f"· judge={settings.judge_model}"
        ),
        task=build_task(graph),
        evaluators=[build_retrieval_evaluator(store), build_judge_evaluator(anthropic_client)],
        max_concurrency=MAX_CONCURRENCY,
    )
    client.flush()  # 스크립트는 끝나기 전에 반드시 flush (M4의 함정과 동일)

    print()
    print(f"실행 완료 — 항목 {len(result.item_results)}건")
    url = getattr(result, "dataset_run_url", None)
    if url:
        print(f"대시보드: {url}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Langfuse Dataset 연동 (M6)")
    parser.add_argument("--upload", action="store_true", help="골든셋 업로드 (무료·멱등)")
    parser.add_argument("--experiment", action="store_true", help="실행 + 채점 (API 비용 발생)")
    parser.add_argument("--limit", type=int, default=None, help="--upload에만 적용 (시험용)")
    args = parser.parse_args()

    if not settings.langfuse_enabled:
        raise SystemExit("LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY가 필요하다 (backend/.env)")
    if not (args.upload or args.experiment):
        raise SystemExit("--upload 또는 --experiment 중 하나를 지정한다")
    if args.experiment and args.limit:
        # ★ 일부러 막는다 ★ dataset.run_experiment는 데이터셋 "전체"를 돌린다.
        # 일부만 돌린 run을 전체 run과 나란히 두면 평균이 다른 모집단끼리 비교되어,
        # 대시보드에서 "개선됐다"가 사실은 "쉬운 것만 골라 돌렸다"가 된다.
        # 비교 가능성이 dataset run의 존재 이유이므로 반쪽 실행을 허용하지 않는다.
        raise SystemExit("--experiment는 데이터셋 전체를 돌린다 (--limit과 함께 쓸 수 없다)")

    cases = load_dataset()
    validate_dataset(cases)
    if args.limit:
        cases = cases[: args.limit]

    if args.upload:
        upload(cases)
    if args.experiment:
        print(
            f"실제 API를 호출한다 (답변 {settings.anthropic_model} / 채점 {settings.judge_model})"
        )
        run_experiment()


if __name__ == "__main__":
    main()
