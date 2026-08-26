# POST /api/v1/chat 테스트. 실제 Anthropic을 부르지 않고 가짜 채팅 모델로 만든
# 그래프를 주입해서, "우리가 만든 것"(SSE 와이어 포맷 · 스키마 파싱 · 메시지 변환/필터
# · 그래프 배선)만 검증한다.
#
# M2에서 목킹 대상이 바뀌었다: M1은 AsyncAnthropic 클라이언트를 갈아끼웠지만
# 이제는 그래프를 통째로 갈아끼운다. 기대하는 SSE 바이트는 M1-1b 캡처 그대로이고,
# 그게 이 단계의 핵심이다 — 내부를 LangGraph로 바꿨는데 밖으로 나가는 바이트가
# 같아야 "동작 동일"이 증명된다.
from typing import Any

import pytest
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGenerationChunk, ChatResult

from app.api.deps import get_graph
from app.graph import build_graph
from app.main import app

# 가짜 모델이 흘려보낼 고정 델타. 값을 고정하면 매 실행이 같은 바이트를 내므로
# 1b 캡처와 == 하나로 비교할 수 있다. 한글을 넣은 이유는 ensure_ascii=False가
# 실제로 동작하는지 같이 확인하기 위함이다.
FAKE_DELTAS = ["안녕", "하세", "요"]

# 가짜 모델이 어떤 메시지를 받았는지 기록해둔다. "무엇이 모델에 전달됐는가"를
# 검증하는 게 이 테스트의 핵심이다 — 응답만 보면 히스토리 누락을 못 잡는다.
CALLS: list[list[BaseMessage]] = []

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


class FakeChatModel(BaseChatModel):
    """LangGraph 노드가 부를 가짜 채팅 모델.

    진짜 ChatAnthropic이 하는 일 중 우리가 실제로 쓰는 표면만 흉내낸다.
    """

    @property
    def _llm_type(self) -> str:
        # BaseChatModel의 추상 멤버. 로깅·직렬화에 쓰인다.
        return "fake"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        # 동기 · 비스트리밍 경로. 여기로 들어왔다는 건 스트리밍을 안 탔다는 뜻이라
        # 조용히 통과시키지 않고 터뜨린다. streaming 설정이 잘못돼도 테스트는
        # 통과해버리는 상황(청크 1개짜리 가짜 스트리밍)을 막는 가드다.
        raise AssertionError("_generate가 호출됐다 = 스트리밍 경로를 타지 않았다")

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ):
        # 라우터가 실제로 타는 경로. 노드는 ainvoke()를 부르지만, _astream이
        # 정의돼 있으면 LangChain이 이쪽으로 보낸다(실측 확인).
        CALLS.append(messages)
        for delta in FAKE_DELTAS:
            chunk = ChatGenerationChunk(message=AIMessageChunk(content=delta))
            if run_manager:
                # ★ 이 콜백이 stream_mode="messages"가 토큰을 잡아내는 통로다.
                # 빼먹으면 청크가 완성본 1개로만 나와 스트리밍이 죽는다.
                await run_manager.on_llm_new_token(delta, chunk=chunk)
            yield chunk


@pytest.fixture
def fake_graph():
    """가짜 모델로 만든 그래프를 주입하고, 테스트가 끝나면 원복한다.

    dependency_overrides는 app 객체에 붙는 전역 상태라, 지우지 않으면 다음
    테스트까지 가짜가 살아남는다. 단독 실행은 통과하고 전체 실행에서만
    깨지는 종류의 버그가 여기서 나온다. CALLS도 같은 이유로 매번 비운다.
    """
    CALLS.clear()
    graph = build_graph(FakeChatModel())
    app.dependency_overrides[get_graph] = lambda: graph
    yield graph
    del app.dependency_overrides[get_graph]


def _wire(*messages):
    """useChat이 보내는 최상위 본문 모양을 만드는 헬퍼.

    실측한 포맷(frontend/node_modules/ai/dist/index.js:17593)을 한 곳에만 적어둔다.
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


def _seen():
    """가짜 모델이 받은 메시지를 (타입, 내용) 쌍으로 납작하게 편다.

    LangChain 메시지 객체를 그대로 비교하면 실패 메시지가 읽기 어려워서,
    확인하고 싶은 두 가지(역할·내용)만 남긴다.
    """
    return [(type(m).__name__, m.content) for m in CALLS[0]]


def test_chat_health(client):
    response = client.get("/api/v1/chat/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_stream_matches_ai_sdk_wire_format(client, fake_graph):
    # 2a의 핵심 테스트다. 내부를 LangGraph로 갈아엎었는데도 밖으로 나가는
    # 바이트가 1b 캡처와 완전히 같아야 한다.
    response = client.post("/api/v1/chat", json=_wire(_msg("m1", "user", "안녕?")))

    assert response.status_code == 200
    assert response.text == EXPECTED_SSE


def test_stream_headers(client, fake_graph):
    response = client.post("/api/v1/chat", json=_wire(_msg("m1", "user", "안녕?")))

    # x-vercel-ai-ui-message-stream이 없으면 useChat이 응답을 UI message stream으로
    # 인식하지 않는다 — 조용히 실패하는 종류라 명시적으로 못 박아둔다.
    assert response.headers["x-vercel-ai-ui-message-stream"] == "v1"
    assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"


def test_full_history_is_forwarded(client, fake_graph):
    # 응답만 보면 절대 못 잡는 버그를 잡는 테스트: "마지막 메시지만 넘기고 있다".
    # add_messages가 dict를 LangChain 메시지로 변환하므로, 역할이 보존되는지도
    # 여기서 같이 확인된다.
    client.post(
        "/api/v1/chat",
        json=_wire(
            _msg("m1", "user", "My favorite color is teal."),
            _msg("m2", "assistant", "Got it, teal."),
            _msg("m3", "user", "What is my favorite color?"),
        ),
    )

    assert len(CALLS) == 1
    assert _seen() == [
        ("HumanMessage", "My favorite color is teal."),
        ("AIMessage", "Got it, teal."),
        ("HumanMessage", "What is my favorite color?"),
    ]


def test_system_role_is_dropped(client, fake_graph):
    # role="system"을 messages 배열에 그대로 넣으면 Anthropic이 400을 낸다.
    # 시스템 프롬프트는 별도 경로로 준다.
    client.post(
        "/api/v1/chat",
        json=_wire(
            _msg("s1", "system", "you are a helpful bot"),
            _msg("m1", "user", "hello"),
        ),
    )

    assert _seen() == [("HumanMessage", "hello")]


def test_non_text_parts_are_dropped(client, fake_graph):
    # 텍스트 파트가 없는 메시지는 content가 ""가 되어 모델이 400을 낸다.
    payload = _wire(_msg("m1", "user", "hello"))
    payload["messages"].insert(
        0, {"id": "f1", "role": "user", "parts": [{"type": "file", "url": "x"}]}
    )

    client.post("/api/v1/chat", json=payload)

    assert _seen() == [("HumanMessage", "hello")]


def test_multiple_text_parts_are_joined(client, fake_graph):
    # 파트 경계는 스트리밍 분할 지점일 뿐 단어 경계가 아니므로 구분자 없이 붙는다.
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

    assert _seen() == [("HumanMessage", "안녕하세요")]


def test_model_is_configured_from_settings():
    # 모델명을 코드에 하드코딩하지 않았는지 확인한다. settings에서 온다면
    # config.py 한 줄로 모델을 교체할 수 있다는 뜻이다.
    #
    # _model이라는 비공개 이름을 테스트가 들여다보는 건 일반적으로 냄새지만,
    # 여기서는 의도적이다 — 아래 streaming 회귀를 막을 다른 방법이 없다.
    from app.api import deps
    from app.core.config import settings

    assert deps._model.model == settings.anthropic_model
    assert deps._model.max_tokens == 1024
    # ★ streaming=False면 astream(stream_mode="messages")가 완성본 1개만 흘린다.
    # 에러가 안 나고 "글자가 툭 나타나는" 형태로만 드러나므로 여기서 못 박는다.
    assert deps._model.streaming is True


def test_empty_messages_returns_400(client, fake_graph):
    # 텍스트가 하나도 없는 요청. 스트림 시작 전에 걸러 정상적인 4xx가 나오는지.
    response = client.post(
        "/api/v1/chat",
        json=_wire({"id": "f1", "role": "user", "parts": [{"type": "file", "url": "x"}]}),
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "no text content in messages"}
    # 그리고 모델을 아예 부르지 않았어야 한다. 불렀다면 가드가 스트림 안쪽에 있다는 뜻이다.
    assert CALLS == []


def test_old_request_format_is_rejected(client, fake_graph):
    # 1a~1c-A에서 쓰던 {"message": "..."} 포맷이 확실히 막히는지.
    response = client.post("/api/v1/chat", json={"message": "old format"})
    assert response.status_code == 422


def test_invalid_role_is_rejected(client, fake_graph):
    # role을 Literal로 좁게 잡은 것의 값. 오타가 조용히 통과하지 않는다.
    response = client.post("/api/v1/chat", json=_wire(_msg("m1", "usr", "typo in role")))
    assert response.status_code == 422
