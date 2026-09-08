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
import sys

from app.core.config import settings
from app.rag.access import Principal
from app.rag.base import TOP_K, HybridStore, RetrievedChunk, VectorStore
from app.rag.embedding import embed_query, embed_sparse_query
from app.rag.factory import get_store, pop_store_arg


def retrieve(
    store: VectorStore,
    query: str,
    principal: Principal,
    top_k: int = TOP_K,
    *,
    hybrid: bool | None = None,
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
    use_hybrid = settings.hybrid_search if hybrid is None else hybrid
    if use_hybrid and isinstance(store, HybridStore):
        return store.search_hybrid(embed_query(query), embed_sparse_query(query), principal, top_k)
    return store.search(embed_query(query), principal, top_k)


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
