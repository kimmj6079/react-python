# 챗봇 HTTP 라우터. 여기서는 요청을 받아 그래프를 돌리고 텍스트 델타를
# 꺼내는 일만 한다. 와이어 포맷(AI SDK 프로토콜) 변환은 app/core/ai_sdk.py에 위임한다.
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.api.deps import Graph
from app.core.ai_sdk import (
    UI_MESSAGE_STREAM_HEADERS,
    latest_user_text,
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
    # 2a에서는 여기서 히스토리 전체를 변환했다. 이제는 이번 턴의 새 발화 하나만
    # 뽑는다 — 나머지는 체크포인터가 이미 갖고 있다.
    text = latest_user_text(payload.messages)

    if not text:
        # 빈 messages로 모델을 부르면 400이 나는데, 그건 스트림이 이미 시작된
        # 뒤라서 클라이언트에는 "200 헤더 + 빈 본문 + 연결 끊김"으로 보인다.
        # 스트림 시작 전에 걸러 정상적인 4xx로 돌려준다.
        raise HTTPException(status_code=400, detail="expected a non-empty user message")

    # ★ 2b의 핵심 두 줄 중 첫 번째 ★
    # thread_id가 "어느 대화인가"를 가리키는 키다. payload.id는 useChat이
    # 자동 생성해 매 요청에 같은 값을 보내는 채팅 세션 id다(M1-1c에서 실측하고
    # schemas/chat.py에 적어둔 값).
    #
    # 모양이 {"configurable": {...}} 로 한 겹 감싸인 이유: 이건 LangGraph 전용
    # 필드가 아니라 LangChain 공통의 RunnableConfig다. 같은 dict에
    # callbacks(M4의 Langfuse), tags, recursion_limit도 함께 들어간다.
    #
    # ★ 이 값은 브라우저가 정한다 = 인증이 붙는 순간 반드시 손봐야 할 곳이다 ★
    # 남의 thread_id를 알아내면 남의 대화에 이어 쓸 수 있다. 지금 이 앱에는
    # 인증 자체가 없어 학습용으로 그냥 두지만, 실무라면 서버가 발급하고 소유권을
    # 검증하거나 최소한 f"{user_id}:{payload.id}"처럼 사용자 식별자를 접두어로
    # 섞는다. M12(멀티테넌시)에서 정면으로 다룬다.
    config = {"configurable": {"thread_id": payload.id}}

    # 이 제너레이터는 "텍스트 델타 문자열"만 내보낸다. SSE 포맷은 전혀 모른다.
    # M1-1c에서 이렇게 잘라둔 덕에 core/ai_sdk.py는 2a에 이어 2b에서도
    # 한 줄도 안 바뀐다.
    async def text_deltas():
        # ★ 2b의 핵심 두 줄 중 두 번째 ★
        # 넣는 것이 "히스토리 전체"에서 "새 메시지 1개"로 줄었고, config가 붙었다.
        # 이전 대화를 앞에 붙이는 일은 체크포인터가 복원하고 add_messages 리듀서가
        # 이어붙인다 — 우리가 조립하는 코드는 없다.
        #
        # config는 키워드가 아니라 2번째 위치 인자다(실측한 시그니처:
        # astream(input, config=None, *, stream_mode=...)). stream_mode부터
        # 키워드 전용이라 순서를 헷갈리면 TypeError로 바로 걸린다.
        #
        # stream_mode="messages"는 (AIMessageChunk, metadata) 2-튜플을 흘린다(실측).
        # 다른 모드: "values"(매 스텝 State 전체), "updates"(노드가 반환한 것만),
        # "custom"(노드가 직접 써넣은 값). 우리한테 필요한 건 토큰 단위라 "messages"다.
        async for chunk, _meta in graph.astream(
            {"messages": [{"role": "user", "content": text}]},
            config,
            stream_mode="messages",
        ):
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
