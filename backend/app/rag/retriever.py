# 유사도 검색(retriever): 질문을 임베딩해 document_chunks에서 가장 가까운
# 청크 top-k를 가져온다. RAG의 "R"이다.
#
# 단독 실측/검증 (backend/에서):
#   uv run python -m app.rag.retriever "파이썬 버전은 어떻게 관리해?"
#
# 그래프(3-2b)는 이 모듈의 search()만 부른다. 3-3에서 Qdrant 구현이 생겨도
# 반환 타입(RetrievedChunk)이 같으면 그래프는 저장소가 바뀐 걸 모른다 —
# "인터페이스 하나, 구현 둘"에서 인터페이스의 실체가 이 시그니처다.
import sys
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.chunk import DocumentChunk
from app.rag.embedding import embed_query

# 몇 개를 가져올 것인가. 크면 정답이 낄 확률(재현율)은 오르지만 프롬프트가
# 길어져 비용과 잡음이 는다. 5는 관례적 기본값일 뿐이고, "우리 문서에서의
# 최적"은 M6 평가 하네스가 생겨야 숫자로 정할 수 있다.
TOP_K = 5


@dataclass
class RetrievedChunk:
    # ORM 객체(DocumentChunk)를 그대로 반환하지 않는 이유 두 가지:
    #   1) 소비자(그래프)가 SQLAlchemy에 묶이면 3-3의 Qdrant 구현이 같은
    #      타입을 돌려줄 수 없다 — 저장소 중립인 "검색 결과" 타입이 필요하다.
    #   2) ORM 객체는 세션이 닫힌 뒤 만지면 터질 수 있는 지뢰(DetachedInstance)를
    #      들고 다닌다. 순수 데이터로 바꿔서 세션 밖으로 내보내는 게 안전하다.
    source: str
    chunk_index: int
    content: str
    distance: float  # 코사인 거리(1 - 유사도). ★ 낮을수록 가깝다 ★


def search(db: Session, query: str, top_k: int = TOP_K) -> list[RetrievedChunk]:
    # 질문은 "query: " 접두어 경로로 임베딩한다 — 인입 때의 passage와 짝.
    query_vector = embed_query(query)

    # pgvector의 코사인 거리 연산자 <=> 로 정렬한다. SQL로는:
    #   SELECT *, embedding <=> :v AS distance
    #   FROM document_chunks ORDER BY distance LIMIT :k
    # 거리 = 1 - 유사도이므로 오름차순 = 가장 비슷한 것부터.
    distance = DocumentChunk.embedding.cosine_distance(query_vector).label("distance")
    rows = db.execute(select(DocumentChunk, distance).order_by(distance).limit(top_k)).all()
    return [
        RetrievedChunk(
            source=row.DocumentChunk.source,
            chunk_index=row.DocumentChunk.chunk_index,
            content=row.DocumentChunk.content,
            distance=row.distance,
        )
        for row in rows
    ]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")

    query = " ".join(sys.argv[1:]).strip()

    if not query:
        print("사용법: uv run python -m app.rag.retriever <질문>")
        print('예:     uv run python -m app.rag.retriever "파이썬 버전은 어떻게 관리해?"')
        raise SystemExit(1)

    with SessionLocal() as db:
        results = search(db, query)

    if not results:
        print("검색 결과 없음 - document_chunks가 비어 있을 수 있다 (먼저 app.rag.ingest로 인입)")
        return

    for rank, r in enumerate(results, start=1):
        preview = r.content[:80].replace("\n", "")
        print(f"[{rank}] {r.source}#{r.chunk_index} distance={r.distance:.4f}")
        print(f"    {preview}")


if __name__ == "__main__":
    main()
