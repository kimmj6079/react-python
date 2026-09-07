# 임베딩 모델을 한 곳에서 관리한다.
#
# 인입(ingest.py)과 검색(3-2의 retriever.py)은 반드시 "같은 모델 + 같은 접두어
# 규칙"을 써야 한다. 다르면 에러가 아니라 검색 품질 붕괴로 나타난다 — 서로 다른
# 모델이 만든 벡터는 같은 의미 공간에 있지 않아서, 유사도 숫자는 멀쩡히 나오는데
# 순위가 무작위에 가까워진다. 그래서 모델 이름을 여기 한 곳에만 적고 양쪽이 import한다.
from fastembed import TextEmbedding

from app.rag.base import EMBEDDING_DIM

# scripts/probe_embedding.py 실측으로 정한 모델. 한국어 포함 다국어 + 1024차원.
# e5 계열은 질문에 "query: ", 문서에 "passage: "를 붙여 학습된 비대칭 모델이라,
# 임베딩할 때도 같은 접두어를 붙여야 학습된 공간에 정확히 들어간다.
#
# config.py(Settings)에 두지 않는 이유: 환경변수로 바꿔도 되는 값이 아니다.
# 모델을 바꾸면 차원과 기존 벡터 전부가 무효가 되어 마이그레이션 + 전체 재인입이
# 따라와야 한다. 코드 상수 + 아래 차원 검증으로 두면 그 실수가 시끄럽게 터진다.
MODEL_NAME = "intfloat/multilingual-e5-large"

# 프로세스당 모델 인스턴스는 하나만 (2.24GB 모델 파일을 메모리에 올리는 작업이다).
# import 시점이 아니라 첫 사용 시점에 만드는(lazy) 이유:
#   - pytest/CI는 임베딩을 안 쓰는데 import만으로 수 초 + 수 GB를 내면 안 된다
#   - chat 엔드포인트도 아직(3-1) 임베딩이 필요 없다
# deps.py가 "import는 항상 안전해야 한다"를 빈 키 허용으로 달성했다면,
# 여기서는 생성 비용이 커서 같은 목표를 lazy 초기화로 달성한다.
_model: TextEmbedding | None = None


def get_model() -> TextEmbedding:
    global _model
    if _model is None:
        _model = TextEmbedding(model_name=MODEL_NAME)
    return _model


def embed_passages(texts: list[str]) -> list[list[float]]:
    # 저장할 문서 조각용. fastembed가 "passage: " 접두어를 자동으로 붙인다.
    # 반환은 넘파이 배열 제너레이터라 list로 소진하고, pgvector 컬럼과
    # Mapped[list[float]] 타입에 맞게 파이썬 리스트로 바꾼다.
    vectors = [v.tolist() for v in get_model().passage_embed(texts)]
    _check_dim(vectors)
    return vectors


def embed_query(text: str) -> list[float]:
    # 검색 질문용. "query: " 접두어가 붙는다 — 저장은 passage, 검색은 query.
    # 이 짝이 어긋나도 에러가 없다. 그래서 함수 이름으로 짝을 강제한다.
    vectors = [v.tolist() for v in get_model().query_embed([text])]
    _check_dim(vectors)
    return vectors[0]


def _check_dim(vectors: list[list[float]]) -> None:
    # 모델과 저장소(pgvector의 vector(1024) / Qdrant 컬렉션의 size=1024)가 어긋난 채
    # 진행되는 것을 막는 안전핀. 저장소도 저장 시점에 차원을 검증하지만, 그건 임베딩
    # 계산(느리다)을 다 마친 뒤이고 메시지도 불친절하다. 여기서 먼저, 모델 이름을 담아 죽는다.
    if vectors and len(vectors[0]) != EMBEDDING_DIM:
        raise ValueError(
            f"임베딩 차원 {len(vectors[0])} != 계약 차원 {EMBEDDING_DIM} - "
            f"모델 {MODEL_NAME}과 app/rag/base.py의 EMBEDDING_DIM이 어긋났다"
        )
