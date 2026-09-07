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
from app.rag.base import TOP_K, RetrievedChunk, VectorStore
from app.rag.embedding import embed_query
from app.rag.factory import get_store, pop_store_arg


def retrieve(store: VectorStore, query: str, top_k: int = TOP_K) -> list[RetrievedChunk]:
    # store를 인자로 받는 이유는 build_graph가 model·checkpointer·retrieve_fn을
    # 인자로 받는 것과 완전히 같다 — 이 함수가 어느 저장소인지 몰라야 3-4에서
    # 설정 한 줄로 갈아끼워진다. 타입을 PgVectorStore가 아니라 VectorStore로 잡은 것도
    # 같은 맥락이다(구현이 아니라 계약에 의존한다).
    return store.search(embed_query(query), top_k)


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
    print(f"[저장소: {store_name or settings.vector_store}]")
    results = retrieve(store, query)

    if not results:
        print("검색 결과 없음 - 저장소가 비어 있을 수 있다 (먼저 app.rag.ingest로 인입)")
        return

    for rank, r in enumerate(results, start=1):
        preview = r.content[:80].replace("\n", "")
        print(f"[{rank}] {r.source}#{r.chunk_index} distance={r.distance:.4f}")
        print(f"    {preview}")


if __name__ == "__main__":
    main()
