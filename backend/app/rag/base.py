# RAG 저장소의 "계약"만 담는 파일. 구현(pgvector / Qdrant)은 여기 없다.
#
# ★ 3-3a에서 이 파일이 생긴 이유 ★
# 3-2b까지 그래프가 아는 것은 retrieve_fn: Callable[[str], list[RetrievedChunk]] 하나였고,
# "찾기"만 갈아끼우면 됐으므로 그걸로 충분했다. 그런데 저장소를 둘로 만들려면 "넣기"도 같이
# 갈아끼워야 한다 — 같은 문서가 양쪽에 들어가 있어야 3-4의 비교가 성립하기 때문이다.
# 넣기와 찾기는 반드시 같은 저장소를 봐야 하는 한 쌍이라, 함수 두 개가 아니라 객체 하나로 묶었다.
#
# 이 파일은 app.db도 qdrant_client도 import하지 않는다. 그게 "계약"이라는 말의 실체다 —
# 계약 파일이 구현을 import하는 순간, 계약을 읽는 사람이 구현을 같이 읽게 된다.
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

# ★ 임베딩 차원. 3-3c에서 models/chunk.py에서 여기로 옮겼다 ★
# 원래 있던 자리(document_chunks 테이블 모델)는 사실 틀린 자리였다 — 1024는 Postgres
# 테이블의 성질이 아니라 임베딩 모델(intfloat/multilingual-e5-large)의 성질이고,
# **두 저장소가 반드시 같은 값으로 합의해야 하는 값**이다. 저장소가 하나였을 때는
# 그 어긋남이 안 보이다가, Qdrant 컬렉션을 만들면서 "qdrant_store가 SQLAlchemy 모델을
# import한다"는 이상한 그림이 되어서야 드러났다. 계약 파일은 아무것도 import하지 않으므로
# models/chunk.py도 rag/embedding.py도 rag/qdrant_store.py도 여기서 가져다 쓴다.
#
# 모델을 바꾸면 이 숫자가 바뀌고, 그러면 pgvector는 마이그레이션 + 전체 재인입,
# Qdrant는 컬렉션 재생성 + 전체 재인입이 필요하다. "설정 한 줄"이 아니다.
EMBEDDING_DIM = 1024

# 몇 개를 가져올 것인가. retriever.py에 있던 상수를 여기로 옮겼다 — 이제 이 값은
# 특정 구현의 사정이 아니라 "검색 계약"의 일부다(두 구현이 같은 기본값으로 동작해야
# 3-4의 비교가 공정하다).
# 크면 정답이 낄 확률(재현율)은 오르지만 프롬프트가 길어져 비용과 잡음이 는다.
# 5는 관례적 기본값일 뿐이고, "우리 문서에서의 최적"은 M6 평가 하네스가 생겨야 숫자로 정해진다.
TOP_K = 5


@dataclass
class RetrievedChunk:
    # 저장소 중립인 "검색 결과" 타입. ORM 객체(DocumentChunk)를 그대로 쓰지 않는 이유:
    #   1) 소비자(그래프)가 SQLAlchemy에 묶이면 Qdrant 구현이 같은 타입을 못 돌려준다
    #   2) ORM 객체는 세션이 닫힌 뒤 만지면 터지는 지뢰(DetachedInstance)를 들고 다닌다
    source: str
    chunk_index: int
    content: str

    # ★ 코사인 "거리"(1 - 유사도). 낮을수록 가깝다 ★
    # pgvector는 거리를, Qdrant는 점수(높을수록 가깝다)를 준다. 계약은 둘 중 하나를
    # 골라야 한다 — 안 고르면 이 값을 쓰는 쪽(M6 지표, M8 리랭킹)이 저장소별로 분기하게
    # 되고, 그 순간 추상화가 실패한 것이다. 3-3c에서 Qdrant 어댑터가 1 - score로
    # 변환해 여기에 맞춘다(코사인에서는 정확히 같은 값이라 손실이 없다).
    distance: float


@runtime_checkable
class VectorStore(Protocol):
    """문서 청크를 넣고 찾는 저장소. 구현은 pgvector(3-3a)와 Qdrant(3-3c) 둘이다.

    ★ 벡터를 받지 텍스트를 받지 않는다 ★
    임베딩은 이 계약 밖(retriever.py / ingest.py)에서 한다. store가 임베딩까지 하면
    "인입은 passage 접두어, 검색은 query 접두어"라는 짝 규칙이 구현 수만큼 복사되고,
    한쪽만 고치는 날 에러 없이 검색 품질만 무너진다(embedding.py 참고).

    ★ ABC가 아니라 Protocol인 이유 ★
    구현체가 이 파일을 상속(import)하지 않아도 "모양만 맞으면" 통과한다(구조적 타이핑).
    graph.py가 retrieve_fn을 Callable로 받는 것과 같은 사고방식이고, 테스트의 가짜
    store도 상속 없이 만들 수 있다.
    대가를 알고 쓴다: 이 저장소에는 mypy가 없으므로(pyproject의 dev 그룹은 pytest·
    httpx·ruff뿐) Protocol은 런타임 강제력이 없다 — 에디터 힌트 + 문서 +
    tests/test_rag_store.py의 conformance 테스트가 실질적 안전망의 전부다.
    ABC로 했다면 "메서드를 안 만들면 인스턴스화가 TypeError"로 막혔겠지만, 대신 모든
    구현이 이 파일을 상속해야 한다.
    """

    def upsert_document(self, source: str, chunks: list[str], vectors: list[list[float]]) -> int:
        """같은 source의 기존 청크를 지우고 새 청크로 통째로 교체한다(멱등).

        반환값은 "지운 개수". 인입 로그에 찍혀서 재인입이 실제로 옛것을 치웠다는
        증거가 된다 — 3-1에서 "기존 19개 삭제"가 안 찍혔다면 같은 문서가 두 벌
        쌓이고 있었다는 뜻이다.

        ★ "어떻게" 멱등을 달성하는지는 계약에 없다 ★ Postgres는 삭제+삽입을 한
        트랜잭션으로 묶을 수 있지만 Qdrant에는 트랜잭션이 없다. 저장소마다 방법이
        다른 것을 계약에 적으면 한쪽이 반드시 억지를 쓰게 된다.
        """

    def search(self, query_vector: list[float], top_k: int = TOP_K) -> list[RetrievedChunk]:
        """질문 벡터와 가장 가까운 청크 top_k개를 distance 오름차순으로 돌려준다."""
