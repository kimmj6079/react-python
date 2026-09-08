# 질문 문자열 → 검색 결과. "임베딩과 저장소를 짝지어주는" 얇은 층이다.
#
# 단독 실측/검증 (backend/에서):
#   uv run python -m app.rag.retriever "파이썬 버전은 어떻게 관리해?"
#
# ★ 3-3a에서 이 파일의 역할이 바뀌었다 ★
# 3-2a의 search(db, query)는 "임베딩 + Postgres 쿼리"를 한 함수에서 다 했다. 지금은
# Postgres 쪽이 pgvector_store.py로 빠지고, 여기엔 "질문은 embed_query로, 문서는
# embed_passages로"라는 짝 규칙만 남았다. 이 짝이 어긋나도 에러가 안 나고 검색 품질만
# 조용히 무너지므로(embedding.py:45), 규칙을 한 곳에 가둬두는 것 자체가 방어다.
import logging
import sys

from app.core.config import settings
from app.rag.access import Principal
from app.rag.base import TOP_K, HybridStore, RetrievedChunk, VectorStore
from app.rag.embedding import embed_query, embed_sparse_query
from app.rag.factory import get_store, pop_store_arg

logger = logging.getLogger(__name__)


def retrieve(
    store: VectorStore,
    query: str,
    principal: Principal,
    top_k: int = TOP_K,
    *,
    hybrid: bool | None = None,
    max_distance: float | None = None,
) -> list[RetrievedChunk]:
    """★ M12: principal이 세 번째 **필수** 인자다 ★

    기본값을 주지 않은 것이 이 마일스톤의 핵심이다. `principal=None`이면 언젠가
    누가 안 넘기고, 그 호출만 조용히 전체 문서를 보게 된다 - 유출은 그렇게 난다.
    필수로 두면 새 호출 지점이 생길 때마다 **TypeError로 즉시** 걸린다.
    (실제로 이 변경 하나로 retriever/deps/evals/judge 네 곳이 전부 컴파일 에러가 났고,
    그게 정확히 "권한을 지나가는 경로가 넷"이라는 뜻이었다.)
    """
    # store를 인자로 받는 이유는 build_graph가 model·checkpointer·retrieve_fn을
    # 인자로 받는 것과 완전히 같다 — 이 함수가 어느 저장소인지 몰라야 3-4에서
    # 설정 한 줄로 갈아끼워진다. 타입을 PgVectorStore가 아니라 VectorStore로 잡은 것도
    # 같은 맥락이다(구현이 아니라 계약에 의존한다).
    #
    # ★ M8: 능력을 물어보고 분기한다 ★
    # "설정이 켜져 있는가"와 "이 저장소가 할 수 있는가"는 다른 질문이다. 둘 다 참일
    # 때만 하이브리드로 가고, 아니면 dense-only로 조용히 내려간다.
    # isinstance(store, HybridStore)는 상속이 아니라 **메서드가 있는가**를 본다
    # (runtime_checkable Protocol) — pgvector 구현이 base.py를 몰라도 되는 이유다.
    # ★ M10: 임베딩을 이 함수 안에서 한 번만 계산한다 ★ 아래 그라운딩 게이트가
    # 벡터를 한 번 더 필요로 하는데, 게이트를 호출자(deps.py)에 두면 embed_query가
    # 두 번 돌아 100ms를 그냥 버린다. 게이트를 여기 둔 이유의 절반이 이것이다.
    vector = embed_query(query)

    # ── 그라운딩 게이트 (M10) ────────────────────────────────
    # ★ 왜 여기서 dense 검색을 한 번 더 하는가 ★
    # 아래 하이브리드 분기가 돌려주는 distance는 RRF 융합 점수에서 나온 값이라
    # **유사도가 아니라 순위**다. 실측(BASELINE-M10.md): 답할 수 있는 질문과 없는
    # 질문의 하이브리드 거리가 완전히 겹쳐서 어디를 잘라도 의미가 없다. 반면 dense
    # 코사인 거리는 거의 갈린다. 그래서 "얼마나 관련 있나"를 판정할 때만 dense를
    # 따로 본다 - top_k=1이라 왕복 한 번(수 ms)이고 임베딩은 위에서 이미 끝났다.
    #
    # max_distance가 None이면 게이트 자체가 없다(=M9까지와 동일). 평가 스크립트가
    # 기본적으로 게이트 없이 도는 이유다 - 게이트가 켜지면 hit@k·MRR이 "검색 품질"이
    # 아니라 "게이트 성능"을 재게 되어 이전 숫자와 비교가 안 된다.
    if max_distance is not None:
        nearest = store.search(vector, principal, top_k=1)
        if not nearest or nearest[0].distance > max_distance:
            # 빈 리스트를 돌려준다 = "근거가 없다". 거절 문구를 여기서 만들지 않는
            # 이유: 이 모듈은 검색만 안다. 그 사실을 어떻게 말할지는 프롬프트의
            # 일이고(graph.py의 NO_CONTEXT_PROMPT), 어떻게 보여줄지는 UI의 일이다.
            distance = nearest[0].distance if nearest else 1.0
            logger.info(
                "그라운딩 게이트: 근거 부족으로 컨텍스트를 비운다 (거리 %.4f > %.4f)",
                distance,
                max_distance,
            )
            return []

    use_hybrid = settings.hybrid_search if hybrid is None else hybrid
    if use_hybrid and isinstance(store, HybridStore):
        return store.search_hybrid(vector, embed_sparse_query(query), principal, top_k)
    return store.search(vector, principal, top_k)


def main() -> None:
    # Windows 콘솔(cp949)에서 한글 print가 깨지지 않게. probe 스크립트와 달리 모듈
    # 레벨이 아니라 main() 안에서 한다 — 이 모듈은 deps.py가 import하므로, "import만
    # 했는데 전역 상태(stdout)가 바뀌는" 부수효과를 두면 안 된다.
    sys.stdout.reconfigure(encoding="utf-8")

    # ★ 3-4: --store 플래그를 먼저 빼낸다 ★ pop_store_arg가 args를 제자리에서
    # 수정하므로, 남는 것은 질문 단어들뿐이다.
    args = sys.argv[1:]
    store_name = pop_store_arg(args)
    query = " ".join(args).strip()

    if not query:
        print("사용법: uv run python -m app.rag.retriever [--store pgvector|qdrant] <질문>")
        print('예:     uv run python -m app.rag.retriever "파이썬 버전은 어떻게 관리해?"')
        print('        uv run python -m app.rag.retriever --store qdrant "같은 질문"')
        raise SystemExit(1)

    # 플래그가 없으면 settings.vector_store(기본 "pgvector")를 따른다.
    store = get_store(store_name)
    mode = "hybrid" if (settings.hybrid_search and isinstance(store, HybridStore)) else "dense"
    print(f"[저장소: {store_name or settings.vector_store} · 검색: {mode}]")
    # CLI는 기본 테넌트로 조회한다. 실제 사용자 요청은 헤더에서 온다(deps.py).
    results = retrieve(store, query, Principal())

    if not results:
        print("검색 결과 없음 - 저장소가 비어 있을 수 있다 (먼저 app.rag.ingest로 인입)")
        return

    for rank, r in enumerate(results, start=1):
        preview = r.content[:80].replace("\n", "")
        print(f"[{rank}] {r.source}#{r.chunk_index} distance={r.distance:.4f}")
        print(f"    {preview}")


if __name__ == "__main__":
    main()
