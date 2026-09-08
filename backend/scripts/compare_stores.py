# M3-4 저장소 비교. 같은 문서·같은 임베딩으로 pgvector와 Qdrant를 나란히 돌려
# "저장소를 바꾸면 무엇이 달라지는가"를 숫자로 본다.
#
# 실행 (양쪽에 같은 문서를 먼저 인입해 두어야 한다):
#   docker compose up -d db qdrant
#   cd backend
#   uv run python -m app.rag.ingest              ../CLAUDE.md ../SETUP.md ../DEPLOYMENT.md
#   uv run python -m app.rag.ingest --store qdrant ../CLAUDE.md ../SETUP.md ../DEPLOYMENT.md
#   uv run python scripts/compare_stores.py
#
# ★ 임베딩을 질문당 딱 한 번만 계산해서 양쪽에 "같은 벡터"를 넘긴다 ★
# 이게 이 스크립트의 핵심 설계다. retrieve()를 두 번 부르면 임베딩도 두 번 도는데,
# 그러면 (a) 느리고 (b) 혹시라도 비결정적 요소가 끼면 "저장소 차이"와 "임베딩 차이"가
# 섞여서 무엇을 비교한 건지 알 수 없게 된다. 계약(base.py)의 search가 텍스트가 아니라
# 벡터를 받도록 설계한 덕에 이게 가능하다 — 3-3a의 설계 결정 ③이 여기서 현금화된다.
#
# ※ 이건 "평가"가 아니라 "관찰"이다. 어느 쪽이 더 좋은지는 정답이 있는 골든셋이
#   있어야 말할 수 있고, 그건 M6의 일이다. 여기서는 "둘이 같은 답을 주는가"만 본다.
import sys
import time

from app.rag.access import Principal
from app.rag.base import TOP_K
from app.rag.embedding import embed_query
from app.rag.factory import get_store

sys.stdout.reconfigure(encoding="utf-8")

QUERIES = [
    # normal — 평범한 사실 확인. 3-2a에서 쓴 질문이라 기존 기록과 대조가 된다.
    ("normal", "파이썬 버전은 어떻게 관리해?"),
    ("normal", "마이그레이션은 언제 실행되나?"),
    ("normal", "대화 내용은 어디에 저장되나?"),
    # keyword — 고유명사·경로. ★ 벡터 검색이 가장 약한 종류다 ★
    # M6 골든셋에 이 종류를 반드시 섞는 이유이고, M8 하이브리드 검색의 효과가
    # 오직 여기서만 드러난다. 지금 미리 눈으로 봐두면 M8에서 "왜 필요한가"가 선명해진다.
    ("keyword", "k8s/base/secret.yaml"),
    ("keyword", "VITE_API_URL"),
]


def key(chunk) -> str:
    # 두 저장소의 결과를 비교하려면 "같은 청크인가"를 판정할 키가 필요하다.
    # (source, chunk_index)가 그 자연 키다 — Qdrant에서 uuid5의 재료로 쓴 것과 같다.
    return f"{chunk.source}#{chunk.chunk_index}"


def main() -> None:
    stores = {name: get_store(name) for name in ("pgvector", "qdrant")}

    print(f"top_k={TOP_K}   질문 {len(QUERIES)}개\n")

    total_overlap = 0
    identical_order = 0

    for kind, question in QUERIES:
        # ★ 여기서 한 번만 임베딩한다 ★
        vector = embed_query(question)

        results = {}
        elapsed = {}
        for name, store in stores.items():
            started = time.perf_counter()
            results[name] = store.search(vector, Principal())
            elapsed[name] = (time.perf_counter() - started) * 1000

        pg, qd = results["pgvector"], results["qdrant"]
        pg_keys, qd_keys = [key(c) for c in pg], [key(c) for c in qd]
        overlap = len(set(pg_keys) & set(qd_keys))
        same_order = pg_keys == qd_keys
        total_overlap += overlap
        identical_order += int(same_order)

        print("=" * 78)
        print(f"[{kind}] {question}")
        print(
            f"  검색 시간: pgvector {elapsed['pgvector']:6.1f}ms / "
            f"qdrant {elapsed['qdrant']:6.1f}ms"
        )
        # E501 회피: 문자열이 길면 ruff format이 못 고친다(문자열 내용은 불변).
        # 인접 문자열 연결(implicit concatenation)로 손수 나눈다 — 3-1의 함정 기록과 동일.
        order_mark = "예" if same_order else "아니오"
        print(f"  top{TOP_K} 겹침: {overlap}/{TOP_K}   순위까지 동일: {order_mark}")
        print()
        print(f"  {'#':<3} {'pgvector':<28} {'dist':<8} {'qdrant':<28} {'dist':<8} {'delta':<8}")
        for rank in range(TOP_K):
            p = pg[rank] if rank < len(pg) else None
            q = qd[rank] if rank < len(qd) else None
            p_key = key(p) if p else "-"
            q_key = key(q) if q else "-"
            p_dist = f"{p.distance:.4f}" if p else "-"
            q_dist = f"{q.distance:.4f}" if q else "-"
            # ★ 같은 순위의 distance 차이 ★ 두 저장소가 같은 벡터로 같은 코사인 거리를
            # 계산했다면 이 값이 0에 가까워야 한다. 크게 벌어지면 (a) 인입된 문서가
            # 다르거나 (b) 1 - score 변환이 틀렸거나 (c) 거리 함수가 다른 것이다.
            delta = f"{abs(p.distance - q.distance):.4f}" if (p and q) else "-"
            mark = " " if p_key == q_key else "*"
            print(
                f"  {rank + 1:<3} {p_key:<28} {p_dist:<8} {q_key:<28} {q_dist:<8} {delta:<8}{mark}"
            )
        print()

    print("=" * 78)
    print(
        f"요약: 겹침 합계 {total_overlap}/{TOP_K * len(QUERIES)}   "
        f"순위까지 동일한 질문 {identical_order}/{len(QUERIES)}"
    )
    print("  * 표시 = 같은 순위에 다른 청크가 있음")


if __name__ == "__main__":
    main()
