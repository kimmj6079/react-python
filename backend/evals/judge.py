# 생성(generation) 평가 — LLM-as-judge. (M6-b)
#
# 실행 (backend/에서. DB/Qdrant가 떠 있어야 하고 실제 Anthropic API를 부른다):
#   uv run python -m evals.judge
#   uv run python -m evals.judge --limit 5 --save
#
# ★ run_retrieval.py와 층이 다르다 ★
#   검색 층: "정답이 담긴 청크가 top-k에 들어왔나" — 임베딩만, 0원, 결정론적
#   생성 층: "그 문맥으로 실제로 답을 잘 했나" — LLM 호출, 비용 발생, 확률적
# 나누는 이유는 답이 나빠졌을 때 **검색이 실패한 건지 프롬프트가 나쁜 건지**를 구분하기
# 위해서다. 하나로 뭉치면 원인 추적이 불가능해진다.
#
# ★ 프로덕션 경로를 그대로 쓴다 ★ 답변을 따로 만들지 않고 app/graph.py의 그래프를
# 실제로 돌린다. 평가용 파이프라인을 따로 두면 "평가에서는 좋은데 실제로는 나쁜" 격차가
# 생기고, 그 격차는 아무도 눈치채지 못한다.
import argparse
import asyncio
import sys
from datetime import datetime
from typing import Literal

from anthropic import AsyncAnthropic
from langchain_anthropic import ChatAnthropic
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel, Field

from app.core.config import settings
from app.graph import build_graph
from app.rag.access import Principal
from app.rag.embedding import embed_query
from app.rag.factory import get_store
from app.rag.ingest import REPO_ROOT
from evals.metrics import mean
from evals.run_retrieval import RESULTS_DIR, Case, load_dataset, validate_dataset


class Verdict(BaseModel):
    """채점 결과의 모양. ★ 이 클래스가 곧 API가 강제하는 스키마다 ★

    structured output(`output_config.format`)을 쓰는 이유: 자유 텍스트로 "4점입니다"를
    받아 파싱하면 모델이 "4/5", "네 점", "약 4점 정도" 같은 변주를 낼 때마다 깨진다.
    **파싱이 깨지면 그 질문이 조용히 누락되고 평균이 흔들린다** — 계측기가 계측 대상보다
    불안정해지는 최악의 상황이다. 스키마를 API 레벨에서 강제하면 그 실패 모드가 사라진다.

    점수를 1~5 정수로 좁게 잡은 것도 같은 이유다. 0~1 실수로 두면 모델이 0.73 같은 값을
    내는데, 그 숫자에는 재현성이 없다(같은 답을 다시 채점하면 0.68이 나온다).
    """

    faithfulness: Literal[1, 2, 3, 4, 5] = Field(
        description="답변이 주어진 문서 발췌에만 근거하는가. "
        "5=전부 근거 있음, 1=문맥에 없는 내용을 지어냄"
    )
    faithfulness_reason: str = Field(description="한 문장 근거. 감점했다면 어느 대목인지 지목")
    answer_relevance: Literal[1, 2, 3, 4, 5] = Field(
        description="질문에 실제로 답했는가. 5=정확히 답함, 1=동문서답"
    )
    answer_relevance_reason: str = Field(description="한 문장 근거")
    refused: bool = Field(
        description="답을 아는 척하지 않고 '문서에 없다/모른다'고 명시적으로 밝혔는가"
    )


JUDGE_PROMPT = """너는 RAG 챗봇의 답변을 채점하는 평가자다. 아래 세 가지를 보고 판정하라.

[질문]
{question}

[챗봇에게 주어진 문서 발췌]
{context}

[챗봇의 답변]
{answer}

채점 기준:
- faithfulness: 답변의 모든 주장이 위 발췌로 뒷받침되는가. 발췌에 없는 사실을 덧붙였으면
  감점한다. ★ 그 내용이 세상의 사실로는 맞더라도, 발췌에 없으면 감점이다 ★ — 이 지표가
  재는 것은 "정답인가"가 아니라 "근거에 붙어 있는가"다.
- answer_relevance: 질문에 답했는가. 사실관계가 틀려도 질문에 답하려 했다면 여기서는
  높을 수 있다(그건 faithfulness가 잡는다). 두 지표는 일부러 다른 것을 본다.
- refused: "문서에서 찾을 수 없다", "모르겠다"처럼 **모름을 명시**했으면 true.
  얼버무리거나 그럴듯하게 지어냈으면 false.

★ 문서에 답이 없는 질문이라면, 거절하는 것이 정답이다 ★ 그 경우 refused=true이고
faithfulness는 높아야 한다(지어내지 않았으므로)."""


async def generate(case: Case, graph) -> tuple[str, str]:
    """프로덕션 그래프를 그대로 돌려 (답변, 그때 쓰인 문맥)을 얻는다.

    ★ 문맥을 따로 검색하지 않고 그래프의 최종 state에서 꺼낸다 ★ 따로 부르면 두 번
    검색하게 되고, 임베딩이 같아도 "채점에 쓴 문맥"과 "답변에 쓰인 문맥"이 다를 위험이
    생긴다. 3-2b에서 retrieved_context를 State 필드로 둔 설계가 여기서 값을 한다.

    thread_id를 질문마다 다르게 준다 — 같은 스레드를 쓰면 앞 질문의 대화가 남아
    뒤 질문의 답에 섞인다(2b의 스레드 격리를 평가에서도 지켜야 한다).
    """
    state = await graph.ainvoke(
        {"messages": [{"role": "user", "content": case.question}], "principal": Principal()},
        {"configurable": {"thread_id": f"eval-{case.id}"}},
    )
    answer = state["messages"][-1].text
    context = state.get("retrieved_context") or "(검색 결과 없음)"
    return answer, context


async def judge(client: AsyncAnthropic, case: Case, answer: str, context: str) -> Verdict:
    response = await client.messages.parse(
        model=settings.judge_model,
        max_tokens=2000,
        messages=[
            {
                "role": "user",
                "content": JUDGE_PROMPT.format(
                    question=case.question, context=context, answer=answer
                ),
            }
        ],
        output_format=Verdict,
    )
    return response.parsed_output


async def run(limit: int | None, store_name: str | None) -> list[dict]:
    cases = load_dataset()
    validate_dataset(cases)
    if limit:
        cases = cases[:limit]

    # 프로덕션과 같은 부품으로 그래프를 조립한다(deps.py와 동일한 배선).
    # 체크포인터만 새로 만든다 — 평가가 앱의 대화 상태를 오염시키면 안 된다.
    store = get_store(store_name)
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
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    rows = []
    for index, case in enumerate(cases, start=1):
        print(f"  [{index}/{len(cases)}] {case.id} {case.question[:36]}", flush=True)
        answer, context = await generate(case, graph)
        verdict = await judge(client, case, answer, context)
        rows.append({"case": case, "answer": answer, "verdict": verdict})
    return rows


def build_report(rows: list[dict]) -> str:
    lines: list[str] = []
    add = lines.append

    add(f"# 생성 평가 결과 (LLM-as-judge) — {datetime.now():%Y-%m-%d %H:%M}")
    add("")
    add("| 설정 | 값 |")
    add("|---|---|")
    add(f"| 답변 모델 | `{settings.anthropic_model}` |")
    add(f"| 채점 모델 | `{settings.judge_model}` |")
    add(f"| 저장소 | `{settings.vector_store}` |")
    add(f"| 골든셋 | {len(rows)}건 |")
    add("")

    add("## 종류별")
    add("")
    add("| 종류 | n | faithfulness | answer relevance | 거절률 |")
    add("|---|---|---|---|---|")
    for kind in ("normal", "keyword", "unanswerable"):
        subset = [r for r in rows if r["case"].kind == kind]
        if not subset:
            continue
        add(
            f"| {kind} | {len(subset)} "
            f"| {mean([r['verdict'].faithfulness for r in subset]):.2f} "
            f"| {mean([r['verdict'].answer_relevance for r in subset]):.2f} "
            f"| {mean([float(r['verdict'].refused) for r in subset]):.2f} |"
        )
    add("")
    add("★ `unanswerable`의 거절률이 1.00이어야 정상이다 — 문서에 없는 것을 지어내지 ")
    add("않았다는 뜻이다. `normal`/`keyword`의 거절률은 0에 가까워야 한다(답할 수 있는데도")
    add("거절하면 그건 과잉 거절이고, 사용자 입장에서는 그냥 못 쓰는 챗봇이다).")
    add("")

    add("## 질문별")
    add("")
    add("| id | 종류 | faith | rel | 거절 | 채점 근거 |")
    add("|---|---|---|---|---|---|")
    for r in rows:
        v = r["verdict"]
        reason = v.faithfulness_reason if v.faithfulness < 5 else v.answer_relevance_reason
        add(
            f"| {r['case'].id} | {r['case'].kind} | {v.faithfulness} | {v.answer_relevance} "
            f"| {'O' if v.refused else '-'} | {reason[:70]} |"
        )
    return "\n".join(lines)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="RAG 생성 평가 - LLM-as-judge (M6)")
    parser.add_argument("--store", default=None, help="pgvector | qdrant (기본: settings)")
    parser.add_argument("--limit", type=int, default=None, help="앞에서 N건만 (시험 실행용)")
    parser.add_argument("--save", action="store_true", help="evals/results/에 마크다운 저장")
    args = parser.parse_args()

    # ★ 실제 API를 부른다는 것을 실행 전에 알린다 ★ 이 스크립트는 pytest가 아니라
    # 사람이 의도적으로 돌리는 것이고, 돌릴 때마다 돈이 든다.
    print(
        f"실제 Anthropic API를 호출한다 "
        f"(답변 {settings.anthropic_model} / 채점 {settings.judge_model})\n"
    )

    rows = asyncio.run(run(args.limit, args.store))
    report = build_report(rows)
    print()
    print(report)

    if args.save:
        RESULTS_DIR.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out = RESULTS_DIR / f"{stamp}-judge.md"
        out.write_text(report, encoding="utf-8")
        print(f"\n저장: {out.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
