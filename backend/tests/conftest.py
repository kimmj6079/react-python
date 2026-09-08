import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import tracing
from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app

# In-memory SQLite shared across a single connection so all sessions in a
# test see the same schema/data. Real Postgres is exercised separately via
# docker-compose / k8s, not in unit tests.
engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def _reset_schema():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def _override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def db_session():
    """테스트용 DB 세션. (M11)

    ★ 라우터가 쓰는 것과 같은 인메모리 SQLite를 연다 ★ 위 _override_get_db와 같은
    엔진이라, 이 세션으로 만든 행을 API 테스트가 그대로 본다.
    문서 인입 로직(upsert_record 등)은 API를 안 부르므로 여기서 직접 검증할 수 있다.
    """
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _langfuse_off(monkeypatch):
    """★ pytest는 절대 실제 Langfuse로 트레이스를 보내지 않는다 ★ (M4)

    이 fixture가 없으면 테스트 결과가 **개발자의 .env에 따라 달라진다.** 실제로 겪었다:
    M4 테스트를 "키가 없는 상태"에서 작성했더니 전부 통과했는데, 키를 등록한 순간
    3개가 깨졌다. 그리고 더 나쁜 건 깨진 것보다 **안 깨진 쪽**이었다 — 통과하는
    테스트들이 그동안 조용히 진짜 Langfuse로 트레이스를 보내고 있었다는 뜻이니까.

    이 저장소의 규칙(chatbot/README.md의 CI 경고)은 "pytest에서 실제 LLM/벡터DB/
    Langfuse API를 호출하면 안 된다"이다. 그 규칙을 각 테스트의 예의에 맡기지 않고
    autouse fixture로 **구조적으로** 보장한다.

    ★ 테스트는 주변 환경(.env)이 아니라 자기가 만든 상태에만 의존해야 한다 ★
    "내 노트북에선 통과하는데 CI에선 실패"의 가장 흔한 원인이 이것이다.
    켜진 상태를 보고 싶은 테스트는 tests/test_tracing.py의 langfuse_keys fixture처럼
    스스로 켠다(autouse가 먼저 돌고 그 위에 덮어쓴다).

    tracing._client도 함께 비운다 — 모듈 전역 싱글턴이라, 안 지우면 앞 테스트가
    만든 클라이언트가 살아남아 "단독 실행은 통과, 전체 실행은 실패"가 된다.
    """
    monkeypatch.setattr(settings, "langfuse_public_key", "", raising=False)
    monkeypatch.setattr(settings, "langfuse_secret_key", "", raising=False)
    monkeypatch.setattr(tracing, "_client", None)
    yield
    tracing._client = None
