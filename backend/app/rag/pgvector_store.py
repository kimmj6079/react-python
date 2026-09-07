# VectorStore의 pgvector 구현. 3-1(ingest.py)과 3-2a(retriever.py)에 흩어져 있던
# "Postgres를 아는 코드"를 여기 한 파일로 모았다.
#
# ★ 세션을 이 클래스가 소유한다 — 이게 3-3a의 핵심 이동이다 ★
# 3-2a의 시그니처는 search(db: Session, query, top_k)였고 세션은 호출자
# (deps.py의 _retrieve, retriever.py의 main)가 열었다. 그 모양으로는 Qdrant 구현을
# 만들 수 없다 — Qdrant에 SQLAlchemy Session이라는 개념이 없기 때문이다.
# 인터페이스에 특정 구현의 타입이 새어나오는 것을 추상화 누수(leaky abstraction)라
# 하고, 구현을 둘로 늘리려는 순간 가장 먼저 걸리는 것이 이것이다.
# → 세션을 메서드 안으로 밀어넣으면 계약(base.py)에서 Session이라는 단어가 사라진다.
#
# 대가를 알고 간다: "요청 하나의 트랜잭션에 검색까지 묶기"가 불가능해졌다. RAG 검색은
# 읽기 전용이고 요청 트랜잭션과 묶일 이유가 없어 지금은 손해가 0이다. 트랜잭션 경계를
# 공유해야 하는 저장소라면 실무에서는 unit-of-work 패턴(세션을 컨텍스트로 주입)을 쓴다.
from sqlalchemy import delete, select

from app.db.session import SessionLocal
from app.models.chunk import DocumentChunk
from app.rag.base import TOP_K, RetrievedChunk


class PgVectorStore:
    # 인스턴스에 상태가 없다(SessionLocal이 모듈 전역이라). 그런데도 함수 두 개가
    # 아니라 클래스로 만든 이유는 QdrantStore가 접속 URL·컬렉션 이름을 들고 있어야
    # 하기 때문이다. 두 구현의 모양이 같아야 3-4의 교체가 "한 줄"이 된다.

    def upsert_document(self, source: str, chunks: list[str], vectors: list[list[float]]) -> int:
        # 삭제 + 삽입을 한 트랜잭션으로 묶는다(3-1과 동일 로직, 위치만 이동).
        # 커밋 전까지 검색에는 옛 청크가 그대로 보이고, 커밋 순간 새 청크로 통째로
        # 바뀐다 — "반쯤 지워진 상태"가 밖에서 보이는 순간이 없다. 실패하면 통째로
        # 롤백되어 옛 청크가 그대로 남는다.
        #
        # UPSERT(ON CONFLICT)를 안 쓰는 이유도 그대로다: 문서가 짧아져 청크 수가
        # 줄면 옛 꼬리 청크가 유령으로 남는다. (진짜 증분 업서트는 M11의 doc_hash로)
        with SessionLocal() as db:
            stmt = delete(DocumentChunk).where(DocumentChunk.source == source)
            deleted = db.execute(stmt).rowcount
            db.add_all(
                [
                    DocumentChunk(source=source, chunk_index=i, content=c, embedding=v)
                    for i, (c, v) in enumerate(zip(chunks, vectors, strict=True))
                ]
            )
            db.commit()
        return deleted

    def search(self, query_vector: list[float], top_k: int = TOP_K) -> list[RetrievedChunk]:
        # pgvector의 코사인 거리 연산자 <=> 로 정렬한다. SQL로는:
        #   SELECT *, embedding <=> :v AS distance
        #   FROM document_chunks ORDER BY distance LIMIT :k
        # 거리 = 1 - 유사도이므로 오름차순 = 가장 비슷한 것부터.
        #
        # 인덱스(HNSW/IVFFlat)가 없어서 순차 스캔이다 = 근사가 아니라 정확한 kNN이고
        # 수백 청크에선 밀리초다(3-1의 "알고 남겨둔 것" ①). 기본이 HNSW인 Qdrant와의
        # 차이가 3-4 비교에서 다시 나온다.
        distance = DocumentChunk.embedding.cosine_distance(query_vector).label("distance")
        with SessionLocal() as db:
            stmt = select(DocumentChunk, distance).order_by(distance).limit(top_k)
            rows = db.execute(stmt).all()
            # ★ 리스트 조립을 with 블록 "안"에서 한다 ★ rows의 원소는 ORM 객체를
            # 품은 Row라, 세션이 닫힌 뒤 건드리면 DetachedInstanceError 위험이 있다.
            # 순수 데이터(RetrievedChunk)로 복사한 뒤에야 세션 밖으로 내보낸다.
            # (return을 with 안에 둬도 파이썬은 __exit__를 정상 실행하므로 세션은 닫힌다)
            return [
                RetrievedChunk(
                    source=row.DocumentChunk.source,
                    chunk_index=row.DocumentChunk.chunk_index,
                    content=row.DocumentChunk.content,
                    distance=row.distance,
                )
                for row in rows
            ]
