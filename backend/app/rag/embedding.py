# 임베딩 모델을 한 곳에서 관리한다.
#
# 인입(ingest.py)과 검색(3-2의 retriever.py)은 반드시 "같은 모델 + 같은 접두어
# 규칙"을 써야 한다. 다르면 에러가 아니라 검색 품질 붕괴로 나타난다 — 서로 다른
# 모델이 만든 벡터는 같은 의미 공간에 있지 않아서, 유사도 숫자는 멀쩡히 나오는데
# 순위가 무작위에 가까워진다. 그래서 모델 이름을 여기 한 곳에만 적고 양쪽이 import한다.
import logging

from fastembed import SparseTextEmbedding, TextEmbedding

from app.rag.base import EMBEDDING_DIM, SparseVector

logger = logging.getLogger(__name__)

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


def _compute_passages(texts: list[str]) -> list[list[float]]:
    # 저장할 문서 조각용. fastembed가 "passage: " 접두어를 자동으로 붙인다.
    # 반환은 넘파이 배열 제너레이터라 list로 소진하고, pgvector 컬럼과
    # Mapped[list[float]] 타입에 맞게 파이썬 리스트로 바꾼다.
    vectors = [v.tolist() for v in get_model().passage_embed(texts)]
    _check_dim(vectors)
    return vectors


def embed_passages(texts: list[str]) -> list[list[float]]:
    """문서 조각 임베딩. 캐시를 먼저 보고, 없는 것만 계산한다. (M13-c)

    ★ 캐시를 호출자가 아니라 여기에 둔 이유 ★ 인입 경로가 둘이다 — CLI(`ingest.py`)와
    업로드(`documents.py` → M11). 호출자마다 캐시를 붙이면 둘이 어긋나고, 세 번째 경로가
    생기는 날 그 경로만 캐시가 없다. "임베딩 모델을 한 곳에서 관리한다"는 이 파일의
    역할에 캐시도 포함시키면 호출자는 아무것도 몰라도 된다 —
    실제로 ingest.py도 documents.py도 **한 글자도 안 바뀌었다.**

    ★ 캐시 키에 모델 이름이 들어간다 ★ MODEL_NAME을 바꾸면 옛 벡터는 자동으로 미스가
    된다. 이게 없으면 모델 교체 후 **다른 의미 공간의 벡터를 캐시가 되살려주고**,
    에러 없이 검색 품질만 무너진다 — 이 파일 머리 주석이 경고하는 바로 그 실패다.
    """
    from app.core.config import settings

    if not settings.embedding_cache_enabled:
        return _compute_passages(texts)

    from app.rag.embedding_cache import get_cache

    # 순서를 유지하며 중복 제거. 같은 문서 안에 같은 조각이 두 번 나오는 일이 실제로
    # 있고(반복되는 표 머리글 등), 그걸 두 번 임베딩할 이유가 없다.
    unique = list(dict.fromkeys(texts))
    cache = get_cache()
    vectors_by_text = cache.get_many(MODEL_NAME, unique)

    missing = [t for t in unique if t not in vectors_by_text]
    if missing:
        computed = _compute_passages(missing)
        cache.put_many(MODEL_NAME, zip(missing, computed, strict=True))
        vectors_by_text.update(zip(missing, computed, strict=True))

    logger.info(
        "임베딩 캐시: %d/%d 적중 (%d개 새로 계산)",
        len(unique) - len(missing),
        len(unique),
        len(missing),
    )

    result = [vectors_by_text[t] for t in texts]
    # 캐시에서 온 벡터도 차원을 검증한다. 캐시 파일이 다른 차원의 모델 시절 것이라면
    # 여기서 시끄럽게 죽는 편이 낫다 — 저장소가 거부할 때까지 가면 메시지가 불친절하다.
    _check_dim(result)
    return result


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


# ★ M8: BM25 희소 임베딩 ★
# dense 임베딩이 구조적으로 못하는 것은 **정확한 토큰 일치**다. "read:packages"를 물으면
# dense는 "비슷하게 생긴 다른 권한 이야기"를 가져온다 — 의미 공간에서는 그게 가깝기 때문이다.
# BM25는 반대로 철자 그대로를 찾는다. 둘은 서로의 약점을 메운다.
#
# ★ torch를 안 끌고 온다 ★ fastembed의 BM25는 onnxruntime 기반이다. 로컬 cross-encoder
# 리랭커를 안 쓰기로 한 이유가 정확히 torch로 인한 이미지 비대화인데, BM25에는 그 문제가
# 없다 — 같은 기준을 적용한 서로 다른 결론이다.
SPARSE_MODEL_NAME = "Qdrant/bm25"

_sparse_model: SparseTextEmbedding | None = None


def get_sparse_model() -> SparseTextEmbedding:
    global _sparse_model
    if _sparse_model is None:
        _sparse_model = SparseTextEmbedding(model_name=SPARSE_MODEL_NAME)
    return _sparse_model


def _to_sparse(embedding) -> SparseVector:
    # fastembed는 numpy 배열을 주고 Qdrant는 파이썬 리스트를 원한다. 계약(base.py)이
    # 어느 라이브러리 타입도 모르게 하려면 여기서 표준 타입으로 바꿔야 한다.
    return (embedding.indices.tolist(), embedding.values.tolist())


def embed_sparse_passages(texts: list[str]) -> list[SparseVector]:
    return [_to_sparse(e) for e in get_sparse_model().embed(texts)]


def embed_sparse_query(text: str) -> SparseVector:
    # ★ query_embed와 embed가 다르다 ★ BM25에서 질의는 문서와 다르게 처리된다
    # (문서는 TF를 세지만 질의는 등장 여부만 본다). e5의 passage/query 접두어와
    # 같은 성질의 비대칭이고, 짝을 어기면 여기서도 에러 없이 품질만 떨어진다.
    return _to_sparse(next(iter(get_sparse_model().query_embed([text]))))
