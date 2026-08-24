# POST /api/v1/chat 테스트. Anthropic을 실제로 부르지 않고 가짜 클라이언트로 바꿔치기해서,
# "우리가 만든 것"(SSE 와이어 포맷 · 스키마 파싱 · 메시지 변환/필터)만 검증한다.
#
# 실제 API를 부르면 (1) 돈이 들고 (2) 느리고 (3) 네트워크에 흔들리고 (4) CI에는 키가 없고
# (5) LLM 출력이 매번 달라 assert를 쓸 수가 없다.
#
# 기대하는 SSE 바이트는 frontend/scripts/capture-wire.mjs로 실측한 1b 캡처(ai@7.0.73)다.
# chatbot/README.md의 M1-1b 항목에 원문이 있다.
import pytest

from app.api.deps import get_anthropic_client
from app.main import app

# 가짜 클라이언트가 흘려보낼 고정 델타. 값을 고정하면 매 실행이 같은 바이트를 내므로
# 캡처와 == 하나로 비교할 수 있다. 한글을 넣은 이유는 ensure_ascii=False가
# 실제로 동작하는지(=\uXXXX로 escape되지 않는지) 같이 확인하기 위함이다.
FAKE_DELTAS = ["안녕", "하세", "요"]

# 1b 캡처 그대로. 델타 3개이므로 text-delta도 3개다.
EXPECTED_SSE = (
    'data: {"type":"start"}\n\n'
    'data: {"type":"start-step"}\n\n'
    'data: {"type":"text-start","id":"0"}\n\n'
    'data: {"type":"text-delta","id":"0","delta":"안녕"}\n\n'
    'data: {"type":"text-delta","id":"0","delta":"하세"}\n\n'
    'data: {"type":"text-delta","id":"0","delta":"요"}\n\n'
    'data: {"type":"text-end","id":"0"}\n\n'
    'data: {"type":"finish-step"}\n\n'
    'data: {"type":"finish","finishReason":"stop"}\n\n'
    "data: [DONE]\n\n"
)


class FakeStream:
    """client.messages.stream(...)이 돌려주는 것의 최소 대역품.

    진짜 객체는 async context manager이고 .text_stream 속성으로 델타를 흘린다.
    라우터가 실제로 쓰는 건 그 둘뿐이므로 그 둘만 흉내낸다.
    """

    async def __aenter__(self):
        # async with 진입 시 호출된다. as 뒤의 변수에 담길 값을 반환한다.
        return self

    async def __aexit__(self, *exc_info):
        # 블록을 나갈 때 호출된다. False를 돌려주면 "예외를 삼키지 않는다"는 뜻이다.
        # True를 돌려주면 테스트 중 발생한 예외가 조용히 사라져서 통과해버린다.
        return False

    @property
    def text_stream(self):
        # 진짜 SDK도 이 속성이 async iterator를 준다. 매번 새 제너레이터를 만들어야
        # 두 번 호출해도 이미 소진된 iterator를 주지 않는다.
        async def gen():
            for delta in FAKE_DELTAS:
                yield delta

        return gen()


class FakeMessages:
    """client.messages 자리에 들어갈 객체."""

    def __init__(self):
        # 라우터가 어떤 인자로 불렀는지 기록해둔다. "무엇이 Anthropic에 전달됐는가"를
        # 검증하는 게 이 테스트의 핵심이다 — 응답만 보면 히스토리 누락을 못 잡는다.
        self.calls = []

    def stream(self, **kwargs):
        # 진짜 SDK의 stream()도 async 함수가 아니다. async context manager를
        # 반환하는 평범한 함수라서 여기서도 def로 맞춘다.
        # (async def로 만들면 라우터의 `async with`가 코루틴을 받아 TypeError가 난다.)
        self.calls.append(kwargs)
        return FakeStream()


class FakeAnthropic:
    """AsyncAnthropic 자리에 들어갈 객체. 라우터는 .messages.stream()만 쓴다."""

    def __init__(self):
        self.messages = FakeMessages()


@pytest.fixture
def fake_anthropic():
    """가짜 클라이언트를 주입하고, 테스트가 끝나면 원복한다.

    yield 뒤의 정리 코드가 중요하다. dependency_overrides는 app 객체에 붙는
    전역 상태라서, 지우지 않으면 다음 테스트까지 가짜가 살아남는다. 테스트를
    단독으로 돌리면 통과하고 전체로 돌리면 깨지는 종류의 버그가 여기서 나온다.
    """
    fake = FakeAnthropic()
    app.dependency_overrides[get_anthropic_client] = lambda: fake
    yield fake
    del app.dependency_overrides[get_anthropic_client]


def _wire(*messages):
    """useChat이 보내는 최상위 본문 모양을 만드는 헬퍼.

    실측한 포맷(frontend/node_modules/ai/dist/index.js:17593)을 한 곳에만 적어둔다.
    각 테스트가 이 dict를 복붙하면, 포맷이 바뀔 때 고칠 곳이 여러 군데로 흩어진다.
    """
    return {
        "id": "test-chat",
        "messages": list(messages),
        "trigger": "submit-message",
        "messageId": messages[-1]["id"] if messages else None,
    }


def _msg(msg_id, role, text):
    """텍스트 파트 하나만 가진 UIMessage."""
    return {"id": msg_id, "role": role, "parts": [{"type": "text", "text": text}]}


def test_chat_health(client):
    response = client.get("/api/v1/chat/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_stream_matches_ai_sdk_wire_format(client, fake_anthropic):
    # 이 테스트가 M1의 핵심이다. 1b에서 실측한 바이트와 우리 출력이 같은지를 본다.
    response = client.post("/api/v1/chat", json=_wire(_msg("m1", "user", "안녕?")))

    assert response.status_code == 200
    # SSE 청크 전체를 한 문자열로 비교한다. 개별 청크로 쪼개 비교하면 순서 버그를
    # 놓치기 쉽고, 통째로 비교하면 순서·개수·구분자가 한 번에 검증된다.
    assert response.text == EXPECTED_SSE


def test_stream_headers(client, fake_anthropic):
    response = client.post("/api/v1/chat", json=_wire(_msg("m1", "user", "안녕?")))

    # x-vercel-ai-ui-message-stream은 AI SDK 고유 헤더다. 이게 없으면 useChat이
    # 응답을 UI message stream으로 인식하지 않는다 — 조용히 실패하는 종류라
    # 명시적으로 못 박아둔다.
    assert response.headers["x-vercel-ai-ui-message-stream"] == "v1"
    # charset=utf-8은 StreamingResponse가 media_type에 자동으로 붙여준다.
    assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"


def test_full_history_is_forwarded(client, fake_anthropic):
    # 응답만 보면 절대 못 잡는 버그를 잡는 테스트: "마지막 메시지만 넘기고 있다".
    # 실제 LLM이라면 그럴듯한 답이 나와서 통과해버린다.
    client.post(
        "/api/v1/chat",
        json=_wire(
            _msg("m1", "user", "My favorite color is teal."),
            _msg("m2", "assistant", "Got it, teal."),
            _msg("m3", "user", "What is my favorite color?"),
        ),
    )

    # 라우터가 Anthropic을 정확히 한 번 불렀고,
    assert len(fake_anthropic.messages.calls) == 1
    # 히스토리 3개가 role까지 보존돼 전달됐는지 본다.
    assert fake_anthropic.messages.calls[0]["messages"] == [
        {"role": "user", "content": "My favorite color is teal."},
        {"role": "assistant", "content": "Got it, teal."},
        {"role": "user", "content": "What is my favorite color?"},
    ]


def test_system_role_is_dropped(client, fake_anthropic):
    # role="system"을 Anthropic messages 배열에 넣으면 400이다. 시스템 프롬프트는
    # messages.stream(system=...) 별도 파라미터로 준다.
    client.post(
        "/api/v1/chat",
        json=_wire(
            _msg("s1", "system", "you are a helpful bot"),
            _msg("m1", "user", "hello"),
        ),
    )

    assert fake_anthropic.messages.calls[0]["messages"] == [{"role": "user", "content": "hello"}]


def test_non_text_parts_are_dropped(client, fake_anthropic):
    # 텍스트 파트가 없는 메시지는 content가 ""가 되어 Anthropic이 400을 낸다
    # ("text content blocks must be non-empty"). 걸러지는지 확인한다.
    payload = _wire(_msg("m1", "user", "hello"))
    payload["messages"].insert(
        0, {"id": "f1", "role": "user", "parts": [{"type": "file", "url": "x"}]}
    )

    client.post("/api/v1/chat", json=payload)

    assert fake_anthropic.messages.calls[0]["messages"] == [{"role": "user", "content": "hello"}]


def test_multiple_text_parts_are_joined(client, fake_anthropic):
    # 한 메시지에 텍스트 파트가 여러 개인 경우. 구분자 없이 붙어야 한다 —
    # 파트 경계는 스트리밍 분할 지점일 뿐 단어 경계가 아니다.
    client.post(
        "/api/v1/chat",
        json=_wire(
            {
                "id": "m1",
                "role": "user",
                "parts": [
                    {"type": "text", "text": "안녕"},
                    {"type": "text", "text": "하세요"},
                ],
            }
        ),
    )

    assert fake_anthropic.messages.calls[0]["messages"] == [
        {"role": "user", "content": "안녕하세요"}
    ]


def test_model_and_max_tokens_come_from_settings(client, fake_anthropic):
    # 모델명을 라우터에 하드코딩하지 않았는지 확인한다. settings에서 온다면
    # config.py 한 줄로 모델을 교체할 수 있다는 뜻이다.
    from app.core.config import settings

    client.post("/api/v1/chat", json=_wire(_msg("m1", "user", "hi")))

    call = fake_anthropic.messages.calls[0]
    assert call["model"] == settings.anthropic_model
    assert call["max_tokens"] == 1024


def test_empty_messages_returns_400(client, fake_anthropic):
    # 텍스트가 하나도 없는 요청. 스트림을 시작한 뒤 Anthropic이 400을 내면
    # 클라이언트에는 "200 헤더 + 빈 본문 + 끊김"으로 보여서 진단이 어렵다.
    # 스트림 시작 전에 걸러 정상적인 4xx가 나오는지 확인한다.
    response = client.post(
        "/api/v1/chat",
        json=_wire({"id": "f1", "role": "user", "parts": [{"type": "file", "url": "x"}]}),
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "no text content in messages"}
    # 그리고 Anthropic을 아예 부르지 않았어야 한다. 불렀다면 가드가 스트림
    # 안쪽에 있다는 뜻이다.
    assert fake_anthropic.messages.calls == []


def test_old_request_format_is_rejected(client, fake_anthropic):
    # 1a~1c-A에서 쓰던 {"message": "..."} 포맷이 확실히 막히는지.
    # 스키마가 실제로 검증하고 있다는 증거다 — 안 그러면 extra="ignore"가
    # 다 삼켜서 messages가 빈 리스트로 통과할 수도 있다.
    response = client.post("/api/v1/chat", json={"message": "old format"})
    assert response.status_code == 422


def test_invalid_role_is_rejected(client, fake_anthropic):
    # role을 Literal로 좁게 잡은 것의 값. 오타나 예상 못 한 값이 조용히
    # 통과하지 않고 422로 걸린다.
    response = client.post("/api/v1/chat", json=_wire(_msg("m1", "usr", "typo in role")))
    assert response.status_code == 422
