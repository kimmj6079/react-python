# Langfuse 트레이싱 배선 테스트. (M4)
#
# ★ 실제 Langfuse에 아무것도 보내지 않는다 ★ 키를 monkeypatch로 심어 "켜졌을 때의
# 분기"만 확인하고, 전송 자체는 확인하지 않는다. 네트워크를 타면 CI가 느려지고
# 플래키해지고 시크릿이 필요해진다 — chatbot/README.md의 CI 경고와 같은 이유다.
# 실제 전송 확인은 scripts/probe_langfuse.py와 대시보드 육안 확인의 몫이다.
import pytest

from app.core import tracing
from app.core.config import settings


@pytest.fixture
def langfuse_keys(monkeypatch):
    """설정에 키가 들어 있는 상태를 만든다.

    ★ tracing._client도 반드시 되돌린다 ★ 모듈 전역 싱글턴이라, 안 지우면 이 테스트가
    만든 클라이언트가 뒤 테스트까지 살아남는다. "단독 실행은 통과, 전체 실행은 실패"의
    전형적 원인이고, 2b에서 체크포인터를 fixture 안에 둔 것과 같은 이유다.
    """
    monkeypatch.setattr(settings, "langfuse_public_key", "pk-lf-test", raising=False)
    monkeypatch.setattr(settings, "langfuse_secret_key", "sk-lf-test", raising=False)
    monkeypatch.setattr(tracing, "_client", None)
    yield
    tracing._client = None


def test_disabled_without_keys():
    # 키가 없으면 빈 리스트다. "빈 핸들러"가 아니라 "빈 리스트"인 것이 핵심이다 —
    # LangChain이 콜백을 아예 안 부르므로 오버헤드가 진짜 0이 된다.
    #
    # 키를 비우는 일은 conftest.py의 _langfuse_off(autouse)가 한다. 예전에는 그냥
    # "개발자 .env에 키가 없겠지"에 기대고 있었는데, 키를 등록하는 순간 이 테스트가
    # 깨지면서 그 가정이 드러났다 — 테스트는 주변 환경이 아니라 자기가 만든 상태에만
    # 의존해야 한다.
    assert settings.langfuse_enabled is False
    assert tracing.get_callbacks() == []


def test_half_configured_counts_as_disabled(monkeypatch):
    # ★ public만 넣고 secret을 깜빡한 반쪽 설정 ★ 이걸 "켜짐"으로 보면 인증 실패가
    # 요청마다 반복되고, 로그를 안 보면 "트레이스가 왜 안 쌓이지"만 남는다.
    # 판단을 settings.langfuse_enabled 한 곳에 모아둔 값이 여기서 나온다.
    #
    # secret을 명시적으로 비운다 — autouse fixture가 이미 비웠더라도, 이 테스트가
    # 무엇을 전제하는지는 테스트 안에서 읽혀야 한다.
    monkeypatch.setattr(settings, "langfuse_public_key", "pk-lf-test", raising=False)
    monkeypatch.setattr(settings, "langfuse_secret_key", "", raising=False)
    assert settings.langfuse_enabled is False
    assert tracing.get_callbacks() == []


def test_enabled_with_keys(langfuse_keys):
    callbacks = tracing.get_callbacks()

    assert len(callbacks) == 1
    assert type(callbacks[0]).__name__ == "LangchainCallbackHandler"


def test_handler_is_new_per_call(langfuse_keys):
    # ★ 이 테스트가 지키는 것은 "트레이스가 서로 안 섞인다"이다 ★
    # 핸들러는 실행 중인 run들을 self._runs와 self.last_trace_id에 들고 다닌다(실측).
    # 하나를 공유하면 동시 요청의 트레이스가 섞이는데, 에러가 아니라 "대시보드에서
    # 남의 대화가 내 트레이스 안에 보이는" 형태로만 드러난다.
    assert tracing.get_callbacks()[0] is not tracing.get_callbacks()[0]


def test_client_is_a_singleton(langfuse_keys):
    # 반대로 클라이언트는 하나여야 한다 — 백그라운드 전송 스레드와 큐를 들고 있어서
    # 요청마다 만들면 스레드가 요청 수만큼 생긴다.
    assert tracing.get_langfuse_client() is tracing.get_langfuse_client()


def test_metadata_uses_the_exact_key_langfuse_reads():
    # ★ 키 이름을 틀리면 에러가 아니라 "그냥 평범한 메타데이터"로 저장된다 ★
    # 대시보드 Sessions 뷰에서 대화가 안 묶이는 것으로만 드러나므로, 실측으로 확인한
    # 문자열(CallbackHandler.py:496)을 테스트로 못 박는다.
    assert tracing.trace_metadata("t-123") == {"langfuse_session_id": "t-123"}


# ---------------------------------------------------------------------------
# M13 — 피드백 루프
# ---------------------------------------------------------------------------
class _FakeHandler:
    def __init__(self, trace_id=None):
        self.last_trace_id = trace_id


class _FakeClient:
    """create_score 호출을 붙잡는 대역. 네트워크로 나가지 않는다."""

    def __init__(self):
        self.scores = []

    def create_score(self, **kwargs):
        self.scores.append(kwargs)


def test_trace_id_is_none_when_tracing_is_off():
    # 키가 없으면 get_callbacks()가 빈 리스트라 물어볼 핸들러 자체가 없다.
    # 이 None이 결국 "피드백 버튼을 그리지 않는다"까지 이어진다.
    assert tracing.trace_id_of([]) is None


def test_trace_id_comes_from_the_handler():
    # ★ 속성 이름을 여기서 못 박는다 ★ last_trace_id는 Langfuse SDK 내부 속성이라
    # 버전이 올라가면 바뀔 수 있다. 바뀌면 이 테스트가 먼저 깨져야 한다 —
    # 안 그러면 "피드백 버튼이 조용히 사라진" 상태로 배포된다.
    assert tracing.trace_id_of([_FakeHandler("deadbeef")]) == "deadbeef"


def test_trace_id_skips_handlers_that_have_not_started():
    # 핸들러는 있는데 아직 관측이 시작 전이면 None이다. 그런 핸들러를 만나도
    # 멈추지 않고 다음을 본다.
    assert tracing.trace_id_of([_FakeHandler(None), _FakeHandler("abc")]) == "abc"


def test_record_feedback_refuses_when_tracing_is_off():
    # ★ 조용한 no-op 금지 ★ create_score()는 꺼져 있으면 아무 말 없이 return한다.
    # 그대로 두면 "버튼은 눌리는데 아무 데도 안 쌓이는" 상태가 되므로 여기서 막는다.
    with pytest.raises(RuntimeError):
        tracing.record_feedback("abc", positive=True)


def test_thumbs_up_is_a_boolean_score_of_one(langfuse_keys, monkeypatch):
    fake = _FakeClient()
    monkeypatch.setattr(tracing, "get_langfuse_client", lambda: fake)

    tracing.record_feedback("trace-1", positive=True, comment="정확했음")

    assert fake.scores == [
        {
            "name": "user-feedback",
            "value": 1,
            "data_type": "BOOLEAN",
            "trace_id": "trace-1",
            "comment": "정확했음",
            # 트레이스당 하나 — 엄지 두 번이 점수 두 개가 되지 않게 하는 열쇠다.
            "score_id": "trace-1",
        }
    ]


def test_thumbs_down_is_zero(langfuse_keys, monkeypatch):
    fake = _FakeClient()
    monkeypatch.setattr(tracing, "get_langfuse_client", lambda: fake)

    tracing.record_feedback("trace-2", positive=False)

    assert fake.scores[0]["value"] == 0
    # ★ 이름을 문자열로 못 박는다 ★ 대시보드 필터와 골든셋 편입 스크립트가 이
    # 이름으로 score를 찾는다. 오타는 에러가 아니라 "필터에 안 걸림"으로만 드러난다.
    assert fake.scores[0]["name"] == tracing.FEEDBACK_SCORE_NAME
