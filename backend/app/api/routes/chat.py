# 챗봇 HTTP 라우터. 여기서는 요청을 받아 그래프를 돌리고 텍스트 델타를
# 꺼내는 일만 한다. 와이어 포맷(AI SDK 프로토콜) 변환은 app/core/ai_sdk.py에 위임한다.
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.api.deps import Graph
from app.core.ai_sdk import (
    UI_MESSAGE_STREAM_HEADERS,
    to_anthropic_messages,
    ui_message_stream,
)
from app.schemas.chat import ChatRequest

router = APIRouter(tags=["chat"])


@router.get("/chat/health")
def chat_health() -> dict[str, str]:
    """
    채팅 서버 상태 확인
    """
    return {"status": "ok"}


@router.post("/chat")
async def chat(payload: ChatRequest, graph: Graph) -> StreamingResponse:
    # 변환은 스트림을 열기 전에 해둔다. 이유는 아래 HTTPException과 같다.
    # add_messages 리듀서가 이 dict들을 LangChain 메시지로 바꿔주므로
    # 이 함수(ai_sdk.to_anthropic_messages)는 M1에서 한 글자도 안 바뀌었다.
    messages = to_anthropic_messages(payload.messages)

    if not messages:
        # 빈 messages로 모델을 부르면 400이 나는데, 그건 스트림이 이미 시작된
        # 뒤라서 클라이언트에는 "200 헤더 + 빈 본문 + 연결 끊김"으로 보인다.
        # 스트림 시작 전에 걸러 정상적인 4xx로 돌려준다.
        raise HTTPException(status_code=400, detail="no text content in messages")

    # 이 제너레이터는 "텍스트 델타 문자열"만 내보낸다. SSE 포맷은 전혀 모른다.
    # M1에서 이렇게 잘라둔 덕에 이번 단계에서 바뀌는 건 이 함수 하나뿐이다 —
    # ai_sdk.py와 프론트엔드는 전혀 손대지 않는다.
    async def text_deltas():
        # stream_mode="messages"는 (AIMessageChunk, metadata) 2-튜플을 흘린다(실측).
        # 다른 모드: "values"(매 스텝 State 전체), "updates"(노드가 반환한 것만),
        # "custom"(노드가 직접 써넣은 값). 우리한테 필요한 건 토큰 단위라 "messages"다.
        async for chunk, _meta in graph.astream({"messages": messages}, stream_mode="messages"):
            # chunk.content가 아니라 chunk.text를 쓴다.
            # content는 문자열일 수도, 콘텐츠 블록 리스트일 수도 있다 — 도구 호출이
            # 붙으면 리스트가 된다(2c에서 실제로 겪는다). text는 그중 텍스트 블록만
            # 이어붙여 항상 str을 준다.
            #
            # 빈 문자열을 거르는 이유: 도구 호출 청크처럼 텍스트가 없는 청크도
            # 흘러나오는데, 그대로 내보내면 의미 없는 text-delta 이벤트가 생긴다.
            if chunk.text:
                yield chunk.text

    return StreamingResponse(
        ui_message_stream(text_deltas()),
        media_type="text/event-stream",
        headers=UI_MESSAGE_STREAM_HEADERS,
    )
