# M13-b 지연 예산 측정. "어디서 시간을 쓰는가"를 단계별 숫자로 낸다.
#
# 실행 (검색 층만 — API 크레딧이 필요 없다):
#   docker compose up -d db qdrant
#   cd backend
#   uv run python scripts/measure_latency.py
#   uv run python scripts/measure_latency.py --repeat 3 --out
#
# 리랭킹까지 재려면 (★ Anthropic 크레딧 필요 ★):
#   uv run python scripts/measure_latency.py --with-rerank
#
# ★ 왜 챗봇 전체가 아니라 검색 층을 재는 스크립트인가 ★
# M13의 지연 예산은 원래 "Langfuse span 지속시간을 뜯어본다"였다. 그건 실제 대화를
# 돌려야 하고, 대화는 생성(LLM)을 반드시 지나므로 **크레딧 없이는 한 글자도 못 잰다.**
# 그런데 파이프라인의 앞쪽 절반(임베딩 · 게이트 · 하이브리드 검색)은 **전부 로컬**이다:
# fastembed는 CPU 추론이고 Qdrant는 옆 컨테이너다. 즉 **지연 예산의 절반은 지금 잴 수 있다.**
# 크레딧이 없다고 아무것도 안 재는 것과, 잴 수 있는 것을 재두고 나머지를 표에 빈칸으로
# 남겨두는 것은 다르다 — 후자는 충전한 날 빈칸만 채우면 끝난다.
#
# ★ 평균이 아니라 p50/p95를 본다 ★ 지연은 정규분포가 아니다. 평균 80ms인데 20번에
# 한 번 400ms면 사용자는 그 400ms를 기억한다. 그리고 p95는 표본이 적으면 의미가 없으므로
# --repeat으로 늘릴 수 있게 해뒀다(질문 24개 × 3회 = 72표본).
import statistics
import sys
import time
from pathlib import Path

from app.core.config import settings
from app.core.timing import request_timings
from app.rag.access import Principal
from app.rag.base import TOP_K, HybridStore
from app.rag.factory import get_store, pop_store_arg
from app.rag.rerank import rerank
from app.rag.retriever import retrieve
from evals.run_retrieval import load_dataset

sys.stdout.reconfigure(encoding="utf-8")

RESULTS_DIR = Path(__file__).resolve().parent.parent / "evals" / "results"

# 평가와 같은 기본 테넌트로 돈다. 골든셋 문서가 전부 공개라 필터가 결과를 바꾸지 않는다.
PRINCIPAL = Principal()


def percentile(values: list[float], q: float) -> float:
    """q분위수(0~1). numpy 없이, 표본이 1개여도 죽지 않게.

    statistics.quantiles는 표본이 2개 미만이면 StatisticsError를 낸다 —
    `--repeat 1`에 질문이 하나뿐인 경우가 실제로 생기므로 직접 계산한다.
    """
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    # 선형 보간 없이 "가장 가까운 순위"를 쓴다. 표본 수십 개 규모에서 보간이 주는
    # 정밀도는 의미가 없고, 대신 "실제로 관측된 값"이 표에 남는다.
    index = min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))
    return ordered[index]


def measure_once(store, question: str, *, with_rerank: bool, gate: bool) -> dict[str, float]:
    """질문 하나를 실제 파이프라인으로 돌리고 단계별 ms를 돌려준다.

    ★ 계측을 위해 별도 코드를 만들지 않는다 ★ 여기서 부르는 retrieve()·rerank()는
    챗봇이 부르는 바로 그 함수다. 측정용으로 비슷한 코드를 새로 쓰면, 그건 챗봇이 아니라
    측정 코드의 성능을 재는 것이 된다(그리고 둘은 반드시 어긋난다).
    """
    max_distance = settings.grounding_max_distance if gate else None
    top_k = settings.rerank_candidates if with_rerank else TOP_K

    with request_timings() as timings:
        chunks = retrieve(store, question, PRINCIPAL, top_k, max_distance=max_distance)
        if with_rerank and len(chunks) >= settings.rerank_min_candidates:
            import asyncio

            asyncio.run(rerank(question, chunks, TOP_K))
        result = timings.summary()

    result["chunks"] = len(chunks)
    return result


def main() -> None:
    args = sys.argv[1:]
    store_name = pop_store_arg(args)
    with_rerank = "--with-rerank" in args
    gate = "--no-gate" not in args
    write_file = "--out" in args
    repeat = 1
    if "--repeat" in args:
        repeat = int(args[args.index("--repeat") + 1])

    store = get_store(store_name)
    mode = "hybrid" if (settings.hybrid_search and isinstance(store, HybridStore)) else "dense"
    cases = load_dataset()

    print(
        f"[저장소 {store_name or settings.vector_store} · 검색 {mode} · 게이트 {gate}"
        f" · 리랭킹 {with_rerank} · 질문 {len(cases)}개 × {repeat}회]"
    )

    # ★ 워밍업을 따로 잰다 ★ fastembed는 첫 호출에서 모델(약 1GB)을 디스크에서 읽어
    # 메모리에 올린다. 그 한 번을 표본에 섞으면 p95가 통째로 오염되고, 반대로 그냥
    # 버리면 **"서버를 막 띄운 뒤 첫 사용자가 겪는 시간"** 이라는 진짜 숫자를 잃는다.
    # 그래서 버리지 않고 따로 보고한다 — k8s에서 파드가 뜬 직후 오는 요청이 이것이다.
    warmup_start = time.perf_counter()
    measure_once(store, cases[0].question, with_rerank=False, gate=gate)
    warmup_ms = (time.perf_counter() - warmup_start) * 1000
    print(f"콜드 스타트(첫 호출, 모델 로딩 포함): {warmup_ms:.0f}ms\n")

    samples: dict[str, list[float]] = {}
    empties = 0
    for _ in range(repeat):
        for case in cases:
            result = measure_once(store, case.question, with_rerank=with_rerank, gate=gate)
            if result["chunks"] == 0:
                # 게이트에 걸린 질문. 단계가 애초에 안 돈 것이라 표본에서 뺀다 —
                # 안 빼면 "게이트 덕에 검색이 빨라졌다"는 착시가 생긴다.
                empties += 1
            for name, ms in result.items():
                if name != "chunks":
                    samples.setdefault(name, []).append(float(ms))

    report = build_report(samples, mode, warmup_ms, empties, repeat, len(cases), with_rerank)
    print(report)

    if write_file:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        suffix = "with-rerank" if with_rerank else "search-only"
        path = RESULTS_DIR / f"{stamp}-latency-{mode}-{suffix}.md"
        path.write_text(report, encoding="utf-8")
        print(f"\n저장: {path}")


def build_report(
    samples: dict[str, list[float]],
    mode: str,
    warmup_ms: float,
    empties: int,
    repeat: int,
    case_count: int,
    with_rerank: bool,
) -> str:
    # 사용자가 기다리는 순서대로 정렬한다. 알파벳순으로 두면 표를 읽으며 파이프라인을
    # 머릿속에서 다시 정렬해야 한다.
    order = ["rewrite", "embed", "gate", "embed_sparse", "search", "rerank", "generate", "ttft"]
    names = [n for n in order if n in samples] + [
        n for n in samples if n not in order and n != "total"
    ]

    lines = [
        f"# 지연 예산 — 검색 층 ({mode})",
        "",
        f"- 표본: 질문 {case_count}개 × {repeat}회 = {case_count * repeat}건"
        f" (게이트에 걸려 검색이 생략된 질문 {empties}건 포함)",
        f"- 콜드 스타트(첫 호출, fastembed 모델 로딩 포함): **{warmup_ms:.0f}ms**",
        f"- 리랭킹 포함: {'예' if with_rerank else '아니오 (크레딧 불필요 경로만 측정)'}",
        "",
        "| 단계 | p50 | p95 | max | 표본 |",
        "|---|---:|---:|---:|---:|",
    ]
    for name in names:
        values = samples[name]
        lines.append(
            f"| `{name}` | {percentile(values, 0.5):.0f}ms | {percentile(values, 0.95):.0f}ms"
            f" | {max(values):.0f}ms | {len(values)} |"
        )
    if "total" in samples:
        total = samples["total"]
        lines.append(
            f"| **합계** | **{percentile(total, 0.5):.0f}ms** | **{percentile(total, 0.95):.0f}ms**"
            f" | **{max(total):.0f}ms** | {len(total)} |"
        )
    lines += [
        "",
        f"평균 참고용: 합계 {statistics.mean(samples['total']):.0f}ms"
        if "total" in samples
        else "",
        "",
        "## 읽는 법",
        "",
        "- `embed`는 **네트워크가 아니라 CPU**다(fastembed 로컬 추론). 느리면 캐시(13-c)나",
        "  더 작은 모델이 처방이지, 인덱스를 손대는 것이 아니다.",
        '- `gate`는 M10이 넣은 `top_k=1` dense 검색 한 번이다. "싸다"고 적어뒀던 주장을',
        "  이 표가 처음으로 검증한다.",
        "- `search`가 하이브리드면 Qdrant 서버가 dense·sparse 두 prefetch와 RRF 융합까지",
        "  한 왕복에 처리한 시간이다(M8).",
        "- 여기 없는 것: `rewrite`·`rerank`·`generate`·`ttft`는 LLM이라 크레딧이 필요하다.",
        "  **표의 빈칸이 곧 남은 일이다.**",
    ]
    return "\n".join(line for line in lines if line != "")


if __name__ == "__main__":
    main()
