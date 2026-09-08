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
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from app.rag.access import DEFAULT_ALLOWED_ROLES, DEFAULT_TENANT_ID, Principal

# 희소(sparse) 벡터 하나. BM25가 만드는 "어떤 토큰이 얼마나 중요한가"의 목록이다.
# dense 벡터가 1024개 실수를 빽빽이 채우는 것과 달리, 문서에 등장한 토큰만 (인덱스, 값)
# 쌍으로 듬성듬성 갖는다 — 그래서 sparse다.
#
# dict가 아니라 튜플 두 개인 이유: Qdrant의 SparseVector와 fastembed의 SparseEmbedding이
# 둘 다 indices/values 두 배열로 표현하고, 계약이 둘 중 어느 라이브러리 타입도
# import하지 않으려면 표준 타입이어야 한다.
SparseVector = tuple[list[int], list[float]]

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

# ★ 융합 전에 각 랭킹에서 몇 개를 뽑을 것인가 (M8) ★
# 하이브리드의 역할은 "재현율" — 정답을 후보 안에 들여놓는 것이다. 그래서 top_k(5)보다
# 훨씬 넉넉하게 뽑아 융합한 뒤 상위 5개만 남긴다. 30은 관례적 출발점이고, 키우면
# 재현율은 오르지만 리랭킹(M8 후반) 비용과 지연이 그만큼 는다.
HYBRID_CANDIDATES = 30


@dataclass
class Chunk:
    """저장소에 넣을 청크 하나. (M7-2)

    ★ 왜 계약 파일에 있나 ★ M7-1까지 upsert_document는 list[str](본문만)을 받았다.
    M7-2에서 heading_path 같은 메타데이터가 붙으면서 "본문 + 부속 정보"를 함께
    넘겨야 하는데, 그 모양은 pgvector와 Qdrant가 **같아야** 하므로 계약의 일부다.
    (chunking.py가 이 타입을 만들어 내고, 두 store가 각자 방식으로 저장한다.)
    """

    content: str
    # "CLAUDE.md > 아키텍처 > 요청 흐름". M7-2에서 임베딩 텍스트 앞에 붙고,
    # M10의 인용 카드가 이 값을 화면에 쓴다.
    heading_path: str
    chunk_index: int
    token_count: int

    # ★ M12: 권한 필드 ★ 청크 자체가 "누구 것인가"를 들고 다닌다. 별도 테이블로
    # 조인하지 않는 이유: 벡터 검색은 저장소 안에서 필터와 함께 한 번에 끝나야 하고,
    # 검색 후 애플리케이션이 걸러내는 방식은 **top-k를 채우지 못한다**
    # (5개 뽑아서 3개를 버리면 2개만 남는다).
    tenant_id: str = DEFAULT_TENANT_ID
    # ["*"]는 "이 테넌트 안에서 모두에게 공개". 빈 리스트를 쓰지 않는 이유는
    # access.py의 PUBLIC_ROLE 주석 참고.
    allowed_roles: list[str] = field(default_factory=lambda: list(DEFAULT_ALLOWED_ROLES))


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

    # ★ M7-2에서 늘었다 ★ 검색 결과가 "어느 문서의 어느 대목"인지 그대로 들고 온다.
    # 프롬프트의 출처 표기에 쓰이고, M10의 인용 카드가 같은 값을 쓴다.
    #
    # 기본값을 준 이유는 두 가지다: (a) 옛 데이터(마이그레이션 전 행, Qdrant의 옛
    # payload)에는 이 필드가 없다 (b) dataclass는 기본값 있는 필드가 없는 필드보다
    # 앞에 오면 TypeError를 낸다 — 그래서 새 필드는 맨 뒤에 붙인다.
    heading_path: str = ""

    # ★ M12에서 늘었다 ★ 검색 결과가 어느 테넌트/역할의 것인지 그대로 들고 온다.
    # 필터가 이미 걸러줬는데도 실어 보내는 이유는 **디버깅과 감사(audit)** 다 —
    # "왜 이게 보였지"를 물을 때 결과 자체에 답이 있어야 한다. 필터를 잘못 짜서
    # 남의 것이 섞였을 때, 결과에 tenant_id가 없으면 그 사실조차 알 수 없다.
    tenant_id: str = DEFAULT_TENANT_ID
    allowed_roles: list[str] = field(default_factory=lambda: list(DEFAULT_ALLOWED_ROLES))


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

    def upsert_document(
        self,
        source: str,
        chunks: list[Chunk],
        vectors: list[list[float]],
        sparse_vectors: list[SparseVector] | None = None,
    ) -> int:
        """같은 source의 기존 청크를 지우고 새 청크로 통째로 교체한다(멱등).

        ★ M7-2에서 list[str] -> list[Chunk]로 바뀌었다 ★ 본문만으로는 부족해졌다.
        벡터는 "heading_path + 본문"으로 만들지만 저장되는 content는 본문 그대로다 —
        그 조립은 호출자(ingest.py)의 일이고, store는 받은 것을 넣기만 한다.

        반환값은 "지운 개수". 인입 로그에 찍혀서 재인입이 실제로 옛것을 치웠다는
        증거가 된다 — 3-1에서 "기존 19개 삭제"가 안 찍혔다면 같은 문서가 두 벌
        쌓이고 있었다는 뜻이다.

        ★ "어떻게" 멱등을 달성하는지는 계약에 없다 ★ Postgres는 삭제+삽입을 한
        트랜잭션으로 묶을 수 있지만 Qdrant에는 트랜잭션이 없다. 저장소마다 방법이
        다른 것을 계약에 적으면 한쪽이 반드시 억지를 쓰게 된다.

        ★ M8: sparse_vectors는 선택 인자다 ★ 하이브리드 검색(BM25)을 지원하는 구현만
        쓰고, pgvector 구현은 조용히 무시한다. 계약은 "최대공약수"여야 한다고 3-3a에
        적었는데 여기서 예외를 하나 만든 셈이다 — 대신 **필수가 아니라 선택**으로 두어
        "이걸 못 하는 구현도 계약을 지킨다"는 성질은 유지했다.
        """

    def search(
        self, query_vector: list[float], principal: Principal, top_k: int = TOP_K
    ) -> list[RetrievedChunk]:
        """질문 벡터와 가장 가까운 청크 top_k개를 distance 오름차순으로 돌려준다.

        ★ M12: principal이 **필수 인자**다 ★ 기본값을 주지 않았다.
        `search(vector, filter=None)`처럼 옵션으로 두면 언젠가 누가 빼먹고, 그 순간이
        유출 사고다. 필수로 두면 빼먹는 것이 **TypeError로 즉시** 걸린다 —
        런타임에 조용히 넓어지는 권한보다 컴파일 시점의 시끄러운 실패가 낫다.
        (retrieve_fn에만 기본값을 안 준 3-2b의 판단과 같은 종류의 결정이다.)
        """


@runtime_checkable
class HybridStore(Protocol):
    """dense + sparse 두 랭킹을 융합해 검색할 수 있는 저장소. (M8)

    ★ VectorStore를 확장하지 않고 별도 프로토콜로 둔 이유 ★
    하이브리드는 **모든 저장소가 할 수 있는 일이 아니다.** Qdrant는 한 컬렉션에 named
    vector로 dense와 sparse를 같이 두고 서버가 RRF로 융합해주지만, pgvector에는 그
    개념이 없다(tsvector + ts_rank는 BM25가 아니라 다른 메커니즘이라, 같은 것을
    구현했다고 말할 수 없다).

    필수 메서드로 VectorStore에 넣었다면 pgvector 구현이 NotImplementedError를 던지는
    "구현했지만 못 하는" 상태가 된다. 별도 프로토콜로 두면 **호출자가 능력을 물어보고
    분기한다**(retriever.py의 isinstance 검사) — 없는 능력을 있는 척하지 않는다.

    M3-4에서 "Qdrant가 값을 하기 시작하는 지점은 (c) DB 레벨 하이브리드 검색"이라고
    적어둔 예고가 여기서 실현된다. 저장소를 둘 다 만들어둔 값이 회수되는 자리다.
    """

    def search_hybrid(
        self,
        query_vector: list[float],
        query_sparse: SparseVector,
        principal: Principal,
        top_k: int = TOP_K,
        candidates: int = HYBRID_CANDIDATES,
    ) -> list[RetrievedChunk]:
        """dense top-N과 sparse top-N을 각각 뽑아 RRF로 융합한 top_k.

        ★ 반환되는 distance는 코사인 거리가 아니다 ★ RRF 점수(순위의 역수 합)를
        1 - score로 뒤집은 값이라, **정렬에는 쓸 수 있어도 절대값 비교(임계값)에는
        쓸 수 없다.** M6 하네스의 unanswerable 거리 분석이 하이브리드에서는 의미가
        달라지는 이유다 — 그쪽 보고서에 주석을 달아뒀다.
        """
