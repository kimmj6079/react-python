# 검색(retrieval) 평가 러너. 골든셋 전체를 retriever에 통과시켜 hit@k / MRR을 낸다. (M6)
#
# 실행 (backend/에서):
#   uv run python -m evals.run_retrieval
#   uv run python -m evals.run_retrieval --store qdrant
#   uv run python -m evals.run_retrieval --top-k 1            # ← 하네스 검증용 "나쁜 설정"
#   uv run python -m evals.run_retrieval --save               # evals/results/에 마크다운 저장
#
# ★ LLM을 부르지 않는다 ★ 임베딩만 쓴다(로컬 fastembed라 0원). 그래서 싸고 결정론적이고,
# M7~M9에서 설정을 바꿔가며 수십 번 돌릴 수 있다. 생성 품질(faithfulness 등)은
# LLM-as-judge가 필요한 별개 층이고 judge.py의 몫이다.
#
# ★ 검색과 생성을 나눈 이유가 M6의 핵심 설계다 ★ 답이 나빠졌을 때 "검색이 실패한 건지
# 프롬프트가 나쁜 건지"를 구분하려면 지표가 분리돼 있어야 한다. 하나로 뭉치면 원인
# 추적이 불가능해진다.
import argparse
import json
import random
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.rag.base import RetrievedChunk
from app.rag.chunking import MAX_TOKENS, OVERLAP_TOKENS
from app.rag.embedding import MODEL_NAME, embed_query
from app.rag.factory import get_store
from app.rag.ingest import REPO_ROOT
from evals.metrics import hit_at_k, mean, reciprocal_rank

EVALS_DIR = Path(__file__).resolve().parent
DATASET = EVALS_DIR / "dataset.jsonl"
RESULTS_DIR = EVALS_DIR / "results"

# 종류별로 쪼개서 본다. ★ 전체 평균만 보면 keyword가 망해도 안 보인다 ★
# 24건 중 keyword가 7건뿐이라, keyword가 전멸해도 전체 hit@5는 0.7 근처로 멀쩡해 보인다.
# M8 하이브리드 검색의 효과는 오직 keyword에서만 드러나므로, 쪼개지 않으면 M8을 넣고도
# "효과 없네"라고 잘못 결론 낸다.
KINDS = ["normal", "keyword", "unanswerable"]


@dataclass
class Case:
    id: str
    kind: str
    question: str
    expected_sources: list[str]
    expected_substrings: list[str]

    @property
    def answerable(self) -> bool:
        return bool(self.expected_substrings or self.expected_sources)


def load_dataset(path: Path = DATASET) -> list[Case]:
    cases = []
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        raw = raw.strip()
        if not raw:
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError as exc:
            # jsonl은 한 줄이 깨지면 그 줄만 문제인데, 기본 에러 메시지에는 줄 번호가
            # 없어서 24줄짜리 파일에서도 어디인지 못 찾는다.
            raise SystemExit(f"{path.name}:{line_no} JSON 파싱 실패 - {exc}") from exc
        cases.append(
            Case(
                id=row["id"],
                kind=row["kind"],
                question=row["question"],
                expected_sources=row.get("expected_sources") or [],
                expected_substrings=row.get("expected_substrings") or [],
            )
        )
    return cases


def validate_dataset(cases: list[Case]) -> None:
    """★ 골든셋 자체를 검증한다 — 이 단계가 없으면 하네스가 조용히 거짓말을 한다 ★

    `expected_substrings`에 오타가 있으면 그 질문은 **영원히 0점**이 되고, 검색이
    아무리 좋아져도 지표가 안 오른다. 그러면 M7~M13 내내 "왜 안 오르지"를 붙들게 된다.
    그래서 각 정답 문자열이 실제로 그 문서 안에 존재하는지 시작 전에 확인한다.

    id 중복도 잡는다 — 결과 표에서 두 줄이 같은 id를 갖는 순간 추적이 불가능해진다.
    """
    problems: list[str] = []

    seen: set[str] = set()
    for case in cases:
        if case.id in seen:
            problems.append(f"[{case.id}] id가 중복이다")
        seen.add(case.id)

        if case.kind not in KINDS:
            problems.append(f"[{case.id}] 모르는 kind: {case.kind!r} (가능: {KINDS})")

        if case.kind == "unanswerable" and case.answerable:
            problems.append(f"[{case.id}] unanswerable인데 정답이 적혀 있다")
        if case.kind != "unanswerable" and not case.answerable:
            problems.append(f"[{case.id}] {case.kind}인데 정답이 비어 있다")

        texts = []
        for source in case.expected_sources:
            path = REPO_ROOT / source
            if not path.is_file():
                problems.append(f"[{case.id}] 없는 파일: {source}")
                continue
            texts.append(path.read_text(encoding="utf-8"))

        # 정답 문자열은 "적어도 한 문서"에 있으면 된다. 여러 문서를 적어둔 경우
        # (k01처럼 CLAUDE.md와 DEPLOYMENT.md 양쪽에 나오는 경로) 전부에 있을 필요는 없다.
        for needle in case.expected_substrings:
            if not any(needle in text for text in texts):
                problems.append(
                    f"[{case.id}] 정답 문자열이 어느 문서에도 없다: {needle!r} "
                    f"(문서를 고쳤거나 골든셋에 오타가 있다)"
                )

    if problems:
        print("골든셋 검증 실패:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        raise SystemExit(1)


def relevance_by_source(case: Case, chunks: list[RetrievedChunk]) -> list[bool]:
    """느슨한 판정: 검색된 청크가 "정답이 있는 문서"에서 왔는가."""
    return [chunk.source in case.expected_sources for chunk in chunks]


def relevance_by_content(case: Case, chunks: list[RetrievedChunk]) -> list[bool]:
    """엄격한 판정: 청크 본문에 정답 문자열이 실제로 들어 있는가.

    ★ 정답을 "청크 번호"가 아니라 "내용"으로 정의한 것이 이 골든셋의 핵심 결정이다 ★
    chunk_index로 적어두면 M7에서 청킹 전략을 바꾸는 순간 골든셋 전체가 무효가 된다 —
    그런데 M7의 before/after를 재는 것이 M6를 만든 이유다. 내용으로 정의하면 청크
    경계가 어떻게 바뀌든 "그 문장을 담은 청크가 왔나"를 그대로 물을 수 있다.

    문서가 3개뿐이라 source 판정만으로는 너무 후하다(찍어도 33%). 두 판정을 나란히
    보면 "문서는 맞췄는데 정작 그 대목은 못 가져왔다"가 드러난다.
    """
    return [any(needle in chunk.content for needle in case.expected_substrings) for chunk in chunks]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="RAG 검색 평가 (M6)")
    parser.add_argument("--store", default=None, help="pgvector | qdrant (기본: settings)")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--save", action="store_true", help="evals/results/에 마크다운 저장")
    parser.add_argument(
        "--shuffle",
        action="store_true",
        help="★ 하네스 검증용 ★ 검색 결과 순서를 무작위로 섞는다 (지표가 떨어져야 정상)",
    )
    args = parser.parse_args()

    cases = load_dataset()
    validate_dataset(cases)
    store = get_store(args.store)
    store_name = args.store or "pgvector"

    print(f"골든셋 {len(cases)}건 · store={store_name} · top_k={args.top_k}\n")

    # ★ 하네스 검증용 대조군 ★ 지표가 안 움직이는 하네스로 M7~M13을 헛돌 수 있다.
    # 순서를 무작위로 섞으면 hit@k는 그대로여야 하고(같은 5개가 그대로 있으니)
    # MRR만 떨어져야 한다 — 그 패턴이 나오지 않으면 지표 계산이 고장난 것이다.
    # seed를 고정해 "나쁜 설정"도 재현 가능하게 둔다.
    rng = random.Random(42)

    rows = []
    for case in cases:
        # compare_stores.py와 같은 이유로 질문당 임베딩은 한 번만.
        chunks = store.search(embed_query(case.question), args.top_k)
        if args.shuffle:
            rng.shuffle(chunks)
        rows.append(
            {
                "case": case,
                "chunks": chunks,
                "by_source": relevance_by_source(case, chunks),
                "by_content": relevance_by_content(case, chunks),
            }
        )

    report = build_report(rows, store_name, args.top_k, args.shuffle)
    print(report)

    if args.save:
        RESULTS_DIR.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        suffix = "-shuffled" if args.shuffle else ""
        out = RESULTS_DIR / f"{stamp}-{store_name}-k{args.top_k}{suffix}.md"
        out.write_text(report, encoding="utf-8")
        print(f"\n저장: {out.relative_to(REPO_ROOT)}")


def build_report(rows: list[dict], store_name: str, top_k: int, shuffled: bool = False) -> str:
    lines: list[str] = []
    add = lines.append

    add(f"# 검색 평가 결과 — {datetime.now():%Y-%m-%d %H:%M}")
    add("")
    # ★ 설정을 결과와 같이 남긴다 ★ 3주 뒤에 "이 숫자가 어떤 설정이었지"를 못 찾으면
    # 기록이 무의미해진다. 임베딩 모델·청크 크기까지 적는 이유는 M7이 그것들을 바꾸기 때문이다.
    add("| 설정 | 값 |")
    add("|---|---|")
    add(f"| store | `{store_name}` |")
    add(f"| top_k | {top_k} |")
    add(f"| 임베딩 모델 | `{MODEL_NAME}` |")
    # ★ M7-1부터 단위가 "자"가 아니라 "토큰"이다 ★ 결과 파일에 단위를 남기지
    # 않으면 3주 뒤에 220이 자인지 토큰인지 알 수 없다.
    add(f"| 청킹 | 구조 인식 · 최대 {MAX_TOKENS}토큰 / 오버랩 {OVERLAP_TOKENS}토큰 |")
    add(f"| 골든셋 | {len(rows)}건 |")
    if shuffled:
        add("| ⚠ 대조군 | **순서 무작위 셔플** (하네스 검증용, 정상 결과 아님) |")
    add("")

    answerable = [r for r in rows if r["case"].answerable]

    add("## 검색 지표 (종류별)")
    add("")
    add("`source` = 정답 문서에서 왔나(느슨) · `content` = 정답 대목을 실제로 가져왔나(엄격)")
    add("")
    # E501 회피: 문자열이 길면 ruff format이 못 고친다 → 인접 문자열 연결로 손수 나눈다.
    add(
        f"| 종류 | n | hit@1 (src) | hit@{top_k} (src) | MRR (src) "
        f"| hit@1 (cnt) | hit@{top_k} (cnt) | MRR (cnt) |"
    )
    add("|---|---|---|---|---|---|---|---|")

    for kind in KINDS:
        subset = [r for r in answerable if r["case"].kind == kind]
        if not subset:
            add(f"| {kind} | 0 | — | — | — | — | — | — | ")
            continue
        add(_metric_row(kind, subset, top_k))

    add(_metric_row("**전체**", answerable, top_k))
    add("")

    add("## 질문별 상세")
    add("")
    add("| id | 종류 | 질문 | src 순위 | cnt 순위 | top1 |")
    add("|---|---|---|---|---|---|")
    for r in rows:
        case = r["case"]
        chunks = r["chunks"]
        top1 = (
            f"{chunks[0].source}#{chunks[0].chunk_index} ({chunks[0].distance:.4f})"
            if chunks
            else "-"
        )
        add(
            f"| {case.id} | {case.kind} | {case.question[:34]} "
            f"| {_rank(r['by_source'])} | {_rank(r['by_content'])} | {top1} |"
        )
    add("")

    add(_unanswerable_section(rows))
    return "\n".join(lines)


def _metric_row(label: str, subset: list[dict], top_k: int) -> str:
    def score(key: str) -> tuple[float, float, float]:
        rel = [r[key] for r in subset]
        return (
            mean([float(hit_at_k(x, 1)) for x in rel]),
            mean([float(hit_at_k(x, top_k)) for x in rel]),
            mean([reciprocal_rank(x) for x in rel]),
        )

    s1, s5, smrr = score("by_source")
    c1, c5, cmrr = score("by_content")
    return (
        f"| {label} | {len(subset)} | {s1:.2f} | {s5:.2f} | {smrr:.3f} "
        f"| {c1:.2f} | {c5:.2f} | {cmrr:.3f} |"
    )


def _rank(relevance: list[bool]) -> str:
    """첫 정답의 순위를 사람이 읽을 수 있게. 없으면 ✗."""
    for index, is_relevant in enumerate(relevance, start=1):
        if is_relevant:
            return str(index)
    return "✗"


def _unanswerable_section(rows: list[dict]) -> str:
    """★ unanswerable은 검색 지표로 잴 수 없다 — 대신 거리 분포를 본다 ★

    정답 청크가 없으니 hit@k도 MRR도 정의되지 않는다(그래서 위 표에서 뺐다).
    그렇다고 이 질문들이 쓸모없는 게 아니다: 검색은 **무조건 top_k개를 돌려주므로**
    문서에 없는 것을 물어도 "가장 덜 무관한" 청크 5개가 나온다. 모델이 그걸 근거처럼
    쓰면 환각이 된다.

    여기서 보는 것은 "답할 수 있는 질문"과 "없는 질문"의 top-1 거리가 실제로 갈리는가다.
    갈린다면 거리 임계값으로 거를 수 있고, 안 갈린다면 임계값 방식은 못 쓴다는 뜻이다 —
    **M10 그라운딩을 프롬프트로 할지 임계값으로 할지의 판단 근거가 이 숫자다.**
    """
    ans = [r["chunks"][0].distance for r in rows if r["case"].answerable and r["chunks"]]
    una = [r["chunks"][0].distance for r in rows if not r["case"].answerable and r["chunks"]]
    if not ans or not una:
        return ""

    lines = [
        "## unanswerable — 거리로 거를 수 있나",
        "",
        "검색은 무조건 top_k개를 돌려준다. 문서에 없는 것을 물어도 '가장 덜 무관한' 청크가 나온다.",
        "",
        "| 그룹 | n | top1 거리 최소 | 평균 | 최대 |",
        "|---|---|---|---|---|",
        f"| 답할 수 있음 | {len(ans)} | {min(ans):.4f} | {mean(ans):.4f} | {max(ans):.4f} |",
        f"| 답할 수 없음 | {len(una)} | {min(una):.4f} | {mean(una):.4f} | {max(una):.4f} |",
        "",
    ]
    gap = min(una) - max(ans)
    if gap > 0:
        lines.append(
            f"**두 그룹이 겹치지 않는다(간격 {gap:+.4f})** — 거리 임계값으로 거를 수 있다."
        )
    else:
        lines.append(
            f"**두 그룹이 겹친다(간격 {gap:+.4f})** — 단순 거리 임계값으로는 못 거른다. "
            "M10의 그라운딩을 프롬프트/생성 단계에서 해야 한다는 근거다."
        )
    return "\n".join(lines)


if __name__ == "__main__":
    main()
