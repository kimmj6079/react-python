# 챗봇 HTTP 라우터. 여기서는 요청을 받아 Anthropic 스트림을 열고 텍스트 델타를
# 꺼내는 일만 한다. 와이어 포맷(AI SDK 프로토콜) 변환은 app/core/ai_sdk.py에 위임한다.
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.api.deps import AnthropicClient
from app.core.ai_sdk import (
    UI_MESSAGE_STREAM_HEADERS,
    to_anthropic_messages,
    ui_message_stream,
)
from app.core.config import settings
from app.schemas.chat import ChatRequest

router = APIRouter(tags=["chat"])


@router.get("/chat/health")
def chat_health() -> dict[str, str]:
    """
    채팅 서버 상태 확인
    """
    return {"status": "ok"}


@router.post("/chat")
async def chat(payload: ChatRequest, client: AnthropicClient) -> StreamingResponse:
    # 변환은 스트림을 열기 전에 해둔다. 이유는 아래 HTTPException과 같다 —
    # 스트림이 시작된 뒤에 터지는 예외는 진단하기 어렵기 때문이다.
    # 브라우저가 매 요청에 히스토리 전체를 보내므로 서버는 무상태이고, 그대로
    # 넘기면 멀티턴이 그냥 동작한다.
    # (M2에서 LangGraph InMemorySaver + thread_id로 서버측 메모리로 뒤집는다.)
    messages = to_anthropic_messages(payload.messages)

    if not messages:
        # 빈 messages로 Anthropic을 부르면 400이 나는데, 그건 스트림이 이미
        # 시작된 뒤라서 클라이언트에는 "200 헤더 + 빈 본문 + 연결 끊김"으로
        # 보인다. 원인을 찾기 매우 어려운 형태다. 스트림 시작 전에 걸러
        # 정상적인 4xx로 돌려준다.
        raise HTTPException(status_code=400, detail="no text content in messages")

    # 이 제너레이터는 "텍스트 델타 문자열"만 내보낸다. SSE 포맷은 전혀 모른다.
    # 그 덕에 M2에서 LangGraph로 갈아탈 때 바꿀 곳이 이 함수 하나로 좁혀진다.
    async def text_deltas():
        # async with를 반드시 이 안에 둔다. 밖으로 빼서 블록 안에서 return하면
        # 함수가 리턴하는 순간 스트림이 닫히고, 정작 읽을 때는 이미 닫혀 있다.
        async with client.messages.stream(
            model=settings.anthropic_model,
            max_tokens=1024,
            messages=messages,
        ) as stream:
            async for text in stream.text_stream:
                yield text

    return StreamingResponse(
        ui_message_stream(text_deltas()),
        media_type="text/event-stream",
        headers=UI_MESSAGE_STREAM_HEADERS,
    )
