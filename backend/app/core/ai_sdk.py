# Vercel AI SDK의 "UI message stream" 프로토콜을 다루는 계층. 방향이 둘이다.
#   - 내보내기: 텍스트 델타 → SSE 이벤트 (sse / ui_message_stream)
#   - 받기:     useChat이 보낸 UIMessage.parts → 평범한 텍스트 (text_from_parts /
#               to_anthropic_messages)
# 토큰을 "누가" 만들었는지(지금은 Anthropic 직접, M2에서는 LangGraph)와 무관하게
# "어떤 모양으로 주고받는가"만 담당한다 — 그래서 라우터(api/routes/chat.py)와 분리한다.
import json
from collections.abc import AsyncIterable, AsyncIterator
from typing import Any

from app.schemas.chat import UIMessage

# StreamingResponse(headers=)에 그대로 넘길 값.
# - content-type은 media_type= 인자가 담당하므로 여기 넣지 않는다(중복 지정 방지).
# - connection: keep-alive는 캡처에 있었지만 uvicorn이 커넥션을 관리하며 붙이는
#   값이라 애플리케이션이 지정할 헤더가 아니다.
UI_MESSAGE_STREAM_HEADERS = {
    "cache-control": "no-cache",
    "x-accel-buffering": "no",
    "x-vercel-ai-ui-message-stream": "v1",
}

# 스트림 종료 신호. JSON이 아니라 리터럴 문자열이라 아래 sse()로는 만들 수 없다
# (json.dumps("[DONE]")은 따옴표가 붙은 '"[DONE]"'이 되어 틀린다).
DONE = "data: [DONE]\n\n"


# ---------------------------------------------------------------------------
# 받기: useChat이 보낸 UIMessage → 우리가 쓸 평범한 텍스트
# ---------------------------------------------------------------------------
def text_from_parts(parts: list[dict[str, Any]]) -> str:
    # parts 배열에서 텍스트 파트만 골라 이어붙인다.
    #
    # p["type"]이 아니라 p.get("type")인 이유: parts를 dict로 느슨하게 받았으니
    # type 키가 없는 무언가가 들어올 수 있다. KeyError는 500으로 터지는데 우리가
    # 원하는 동작은 "모르는 파트는 무시"다.
    #
    # 구분자 없이 ""로 붙이는 이유: 파트 경계는 스트리밍 분할 지점일 뿐 단어
    # 경계가 아니다. " "로 붙이면 단어 중간에 공백이 끼어든다.
    return "".join(p.get("text", "") for p in parts if p.get("type") == "text")


def to_anthropic_messages(messages: list[UIMessage]) -> list[dict[str, str]]:
    # UIMessage 리스트를 Anthropic messages 형식({"role", "content"})으로 변환한다.
    out: list[dict[str, str]] = []
    for m in messages:
        # role="system"을 Anthropic의 messages 배열에 넣으면 400이다. 시스템
        # 프롬프트는 messages.stream(system=...) 별도 파라미터로 준다.
        # AI SDK 쪽도 같은 입장이다 — index.d.ts:1834가 system 메시지를 피하고
        # 시스템 프롬프트는 서버에서 설정하라고 명시한다.
        if m.role == "system":
            continue

        text = text_from_parts(m.parts)

        # 빈 content 블록을 보내면 Anthropic이 400을 낸다
        # ("text content blocks must be non-empty"). 파일 파트만 있는 메시지가
        # 오면 text가 ""가 되므로 여기서 걸러야 한다.
        if not text:
            continue

        out.append({"role": m.role, "content": text})
    return out


# ---------------------------------------------------------------------------
# 내보내기
# ---------------------------------------------------------------------------
def sse(payload: dict[str, str]) -> str:
    # separators로 공백을 없애는 이유: 파이썬 json.dumps 기본값은 '{"a": 1}'인데
    # JS의 JSON.stringify는 '{"a":1}'다(1b 캡처가 후자). 기능 차이는 없지만,
    # 캡처한 바이트와 == 하나로 비교할 수 있게 맞춰둔다.
    # ensure_ascii=False는 한글을 \uXXXX로 escape하지 않으려는 것(1b도 생 한글이었다).
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    # SSE 한 덩어리의 끝은 빈 줄이다 = 개행 두 개. 하나만 쓰면 클라이언트가
    # 이벤트 경계를 못 잡는다(1a에서 이미 확인한 것).
    return f"data: {body}\n\n"


async def ui_message_stream(
    deltas: AsyncIterable[str], *, text_id: str = "0"
) -> AsyncIterator[str]:
    # 이벤트 순서는 1b 캡처(chatbot/README.md)를 그대로 옮긴 것이다. 암기가 아니라 실측.
    #   start → start-step → text-start → text-delta×N → text-end
    #         → finish-step → finish → [DONE]
    # start: 응답 하나의 시작.
    # start-step: 그 응답 안의 "스텝" 하나의 시작. 스텝은 LLM 왕복 1회를 뜻해서,
    #   도구 호출이 끼면 한 응답에 스텝이 여러 개 생긴다. 지금은 항상 1개다.
    yield sse({"type": "start"})
    yield sse({"type": "start-step"})

    # 텍스트 블록의 시작. 여기서부터 text-end까지가 같은 id로 묶인 한 덩어리다.
    # id가 필요한 이유: 한 응답에 텍스트 블록이 여러 개(추론 블록, 도구 결과 사이의
    # 텍스트 등) 생길 수 있어서 파서가 어느 블록의 델타인지 구분해야 한다.
    yield sse({"type": "text-start", "id": text_id})

    # deltas가 0개여도 위 3개와 아래 4개는 그대로 나간다. 파서가 상태 기계라서
    # text-start 없는 text-delta나 finish 없는 [DONE]은 조용히 무시된다 — 에러가
    # 안 나고 화면만 백지가 되므로, 생애주기를 조건부로 빼먹으면 안 된다.
    async for delta in deltas:
        # 텍스트가 담기는 키는 "text"가 아니라 "delta"다. 1a의 {"text": ...}에서
        # 바뀌는 지점이 정확히 여기다
        yield sse({"type": "text-delta", "id": text_id, "delta": delta})

    yield sse({"type": "text-end", "id": text_id})
    yield sse({"type": "finish-step"})

    # finishReason은 camelCase다. 파이썬 관례(snake_case)와 어긋나지만 와이어 포맷이
    # 정답이므로 그대로 쓴다. M1은 항상 "stop"으로 고정한다 — max_tokens에 걸린
    # 경우를 구분하려면 stream.get_final_message()의 stop_reason을 봐야 하는데,
    # 그러면 스트림을 끝까지 소비한 뒤에야 알 수 있어 구조가 복잡해진다.
    yield sse({"type": "finish", "finishReason": "stop"})

    # 종료 센티넬. JSON이 아니라 리터럴이라 sse()를 통과시키지 않는 유일한 항목.
    yield DONE
