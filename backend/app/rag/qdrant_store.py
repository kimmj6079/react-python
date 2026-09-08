# VectorStore의 Qdrant 구현. pgvector_store.py와 같은 계약(app/rag/base.py)을 지키므로
# 그래프도 인입 스크립트도 이 파일이 존재하는지조차 모른다.
#
# ★ 이 파일은 scripts/probe_qdrant.py의 실측 결과를 그대로 코드로 옮긴 것이다 ★
# 문서를 암기해 쓴 줄이 하나도 없다. 각 결정 옆에 실측 번호를 달아뒀다.
#
# pgvector와 "같은 일"을 하지만 방법이 다른 지점이 넷이다 — 그 넷이 곧
# "전용 벡터 DB를 쓰면 무엇이 달라지는가"의 실체다:
#   1) 스키마 마이그레이션이 없다      → 컬렉션을 런타임에 만든다 (_ensure_collection)
#   2) 자연 키를 못 쓴다              → uuid5로 결정론적 id를 만든다 (_point_id)
#   3) 트랜잭션이 없다                → 삭제와 삽입 사이에 빈 창이 생긴다 (upsert_document)
#   4) 거리가 아니라 점수를 준다       → 1 - score로 변환한다 (search)
import uuid

from qdrant_client import QdrantClient, models

from app.core.config import settings
from app.rag.base import EMBEDDING_DIM, TOP_K, Chunk, RetrievedChunk

# ★ 타임아웃을 반드시 명시한다 ★ (3-3a의 "알고 남겨둔 것" ①이 여기서 회수된다)
# pgvector는 db/session.py의 statement_timeout=5000이 지켜주지만 Qdrant는 HTTP다.
# graph.py의 retrieve 노드는 asyncio.to_thread로 도는데, 여기서 무한정 매달리면
# 스레드 풀이 통째로 막혀서 3-2b가 이벤트 루프를 지키려고 만든 방어가 무력해진다.
# 즉 "느린 Qdrant"가 "챗봇 전체 정지"로 번지는 경로가 이 상수 하나로 끊긴다.
TIMEOUT_SECONDS = 5

# 결정론적 UUID를 만들 때 쓰는 네임스페이스. 값 자체는 아무거나 상관없지만
# ★ 한 번 정하면 절대 바꾸면 안 된다 ★ — 바꾸는 순간 같은 청크가 다른 id를 갖게 되어
# 재인입이 "덮어쓰기"가 아니라 "중복 삽입"이 된다(에러 없이).
ID_NAMESPACE = uuid.NAMESPACE_URL


class QdrantStore:
    def __init__(self, url: str | None = None, collection: str | None = None) -> None:
        # 기본값을 settings에서 읽되 인자로 덮어쓸 수 있게 둔다 — 3-4의 비교 스크립트가
        # 컬렉션 이름만 바꿔 여러 설정을 나란히 두고 실험할 수 있어야 하기 때문이다
        # (M7의 docs_v1 / docs_v2 A/B가 정확히 이 형태다).
        self._client = QdrantClient(url=url or settings.qdrant_url, timeout=TIMEOUT_SECONDS)
        self._collection = collection or settings.qdrant_collection

        # 컬렉션 존재 확인을 한 번만 하기 위한 플래그. 매 검색마다 확인하면 사용자
        # 요청 하나당 왕복이 하나 더 붙는다. 대가: 컬렉션이 "밖에서" 지워지면 이
        # 프로세스는 재시작 전까지 계속 404를 낸다.
        # 실무에서는 이 부트스트랩을 앱이 아니라 배포 단계의 Job으로 뺀다 —
        # 이 저장소의 k8s/base/migrate-job.yaml이 pgvector에게 해주는 일과 같은 역할이다.
        self._collection_ready = False

    def _ensure_collection(self) -> None:
        # 실측 ②·⑦: Qdrant는 컬렉션을 런타임 API 한 번으로 만든다(마이그레이션 없음).
        # 그리고 없는 컬렉션을 검색하면 조용히 빈 결과가 아니라 404 예외다 —
        # 그래서 "없으면 만든다"를 우리가 명시적으로 해줘야 한다.
        if self._collection_ready:
            return
        if not self._client.collection_exists(self._collection):
            self._client.create_collection(
                collection_name=self._collection,
                # size는 base.py의 EMBEDDING_DIM 하나에서 온다 — pgvector 컬럼과
                # 같은 출처를 쓰므로 두 저장소의 차원이 어긋날 수가 없다.
                # distance=COSINE은 e5 임베딩 + pgvector의 cosine_distance와 짝을 맞춘 것이다.
                # 여기만 EUCLID로 바꾸면 에러 없이 순위만 달라진다.
                vectors_config=models.VectorParams(
                    size=EMBEDDING_DIM, distance=models.Distance.COSINE
                ),
            )
        self._collection_ready = True

    @staticmethod
    def _point_id(source: str, chunk_index: int) -> str:
        # ★ 실측 ③이 강제한 함수 ★
        # Qdrant의 point id는 unsigned int 또는 UUID만 허용한다. pgvector에서 쓰던
        # "CLAUDE.md#0" 같은 자연 키를 그대로 넣으면 400 Bad Request다.
        #
        # uuid5는 (네임스페이스, 이름) -> UUID가 항상 같은 결정론적 해시다. 그래서 같은
        # 청크는 언제 넣어도 같은 id를 갖고, 재인입이 자동으로 덮어쓰기가 된다.
        # uuid4(랜덤)를 쓰면 매번 다른 id가 나와 같은 문서가 넣을 때마다 중복으로 쌓인다
        # — 에러가 안 나고 검색 결과에 같은 내용이 여러 번 나오는 것으로만 드러난다.
        return str(uuid.uuid5(ID_NAMESPACE, f"{source}#{chunk_index}"))

    def _source_filter(self, source: str) -> models.Filter:
        # payload의 source 필드로 "이 문서의 청크만" 고르는 조건.
        # 실측 ⑥: payload 인덱스를 안 만들어도 동작한다(전수 스캔). 청크가 수만 개를
        # 넘어가면 create_payload_index가 필요해진다 — M12의 권한 필터에서 다시 나온다.
        return models.Filter(
            must=[models.FieldCondition(key="source", match=models.MatchValue(value=source))]
        )

    def upsert_document(self, source: str, chunks: list[Chunk], vectors: list[list[float]]) -> int:
        self._ensure_collection()
        flt = self._source_filter(source)

        # ★ 실측 ⑥이 강제한 한 줄 ★ delete는 "삭제한 개수"를 안 돌려준다
        # (UpdateResult에 operation_id와 status뿐). 계약(base.py)이 "지운 개수"를
        # 요구하므로 지우기 전에 count를 한 번 더 부른다.
        # 계약이 한쪽만 싸게 줄 수 있는 값을 요구할 때 치르는 비용이고, 알고 넣었다.
        deleted = self._client.count(self._collection, count_filter=flt).count

        # ★ 여기가 pgvector와 가장 크게 다른 지점이다 ★
        # pgvector는 delete + insert를 한 트랜잭션으로 묶어서 "반쯤 지워진 상태"가
        # 밖에서 보이는 순간이 아예 없었다. Qdrant에는 트랜잭션이 없다 — 아래 두 줄
        # 사이에 이 문서가 검색에서 통째로 사라지는 창이 실제로 존재한다.
        #
        # 학습용이라 감수하지만, 실무라면 두 갈래로 간다:
        #   (a) 새 컬렉션에 전부 넣고 alias를 원자적으로 바꿔 끼운다(무중단 재인입).
        #       Qdrant의 update_collection_aliases가 이 용도이고, M7의 docs_v1/v2
        #       A/B와 자연스럽게 이어진다.
        #   (b) 삭제를 생략하고 uuid5 덮어쓰기에만 의존한다 — 창은 없어지지만
        #       문서가 짧아졌을 때 옛 꼬리 청크가 유령으로 남는다(3-1에서 pgvector에
        #       UPSERT를 안 쓴 것과 정확히 같은 이유). 그래서 (b)는 안 골랐다.
        self._client.delete(
            collection_name=self._collection,
            points_selector=models.FilterSelector(filter=flt),
        )
        self._client.upsert(
            collection_name=self._collection,
            points=[
                models.PointStruct(
                    id=self._point_id(source, chunk.chunk_index),
                    vector=vector,
                    # payload = pgvector에서 source/chunk_index/content 컬럼이 하던 일.
                    # ★ 원문(content)을 반드시 같이 저장한다 ★ 벡터는 비가역이라
                    # 원문이 없으면 검색에 성공해도 모델에게 붙여줄 게 없다(3-1과 동일 원칙).
                    # Qdrant는 스키마가 없어서 dict를 그냥 넣는다 — 편한 만큼,
                    # 오타 난 키("sorce")도 조용히 저장된다는 뜻이기도 하다.
                    payload={
                        "source": source,
                        "chunk_index": chunk.chunk_index,
                        "content": chunk.content,
                        # ★ M7-2 ★ Qdrant는 스키마가 없어서 payload에 키를 더하는 것이
                        # 마이그레이션 없이 된다. 편한 만큼, 옛 point에는 이 키가 없어서
                        # 읽는 쪽이 .get()으로 방어해야 한다(아래 search 참고).
                        "heading_path": chunk.heading_path,
                        "token_count": chunk.token_count,
                    },
                )
                for chunk, vector in zip(chunks, vectors, strict=True)
            ],
        )
        return deleted

    def search(self, query_vector: list[float], top_k: int = TOP_K) -> list[RetrievedChunk]:
        self._ensure_collection()

        # 실측 ⑤: 반환은 리스트가 아니라 QueryResponse다. .points를 꺼내야
        # ScoredPoint 리스트가 나온다. with_payload=True를 빼면 payload가 안 와서
        # content가 None이 되는데 — 에러가 아니라 "빈 컨텍스트"로 흘러가므로
        # 화면에서는 그냥 "문서를 못 찾았다"처럼 보인다.
        response = self._client.query_points(
            collection_name=self._collection,
            query=query_vector,
            limit=top_k,
            with_payload=True,
        )

        return [
            RetrievedChunk(
                source=point.payload["source"],
                chunk_index=point.payload["chunk_index"],
                content=point.payload["content"],
                # ★ .get()인 이유 ★ M7-2 이전에 넣은 point에는 이 키가 없다.
                # pgvector는 server_default=""가 컬럼 차원에서 막아주지만 Qdrant는
                # 스키마가 없어서 "없는 키"가 그대로 KeyError가 된다 - 스키마 없는
                # 저장소의 편함이 그대로 대가가 되는 지점이다.
                heading_path=point.payload.get("heading_path", ""),
                # ★ 실측 ⑤가 강제한 변환 ★ Qdrant의 score는 "유사도"(높을수록 가깝다)라
                # pgvector의 cosine_distance와 방향이 반대다. 코사인에서는
                # distance = 1 - score 가 정확히 성립한다(probe에서 손계산과 대조 확인).
                # 이 한 줄이 없으면 두 저장소의 숫자가 정반대 의미가 되어, M6 평가
                # 하네스가 Qdrant에서만 순위를 거꾸로 매긴다 — 에러 없이.
                distance=1.0 - point.score,
            )
            for point in response.points
        ]
