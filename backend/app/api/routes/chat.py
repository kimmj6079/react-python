# 챗봇 HTTP 라우터. 여기서는 요청을 받아 그래프를 돌리고 텍스트 델타를
# 꺼내는 일만 한다. 와이어 포맷(AI SDK 프로토콜) 변환은 app/core/ai_sdk.py에 위임한다.
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessageChunk

from app.api.deps import CurrentPrincipal, Graph
from app.core.ai_sdk import (
    UI_MESSAGE_STREAM_HEADERS,
    latest_user_text,
    source_part,
    ui_message_stream,
)
from app.core.tracing import get_callbacks, trace_metadata
from app.schemas.chat import ChatRequest

router = APIRouter(tags=["chat"])


@router.get("/chat/health")
def chat_health() -> dict[str, str]:
    """
    채팅 서버 상태 확인
    """
    return {"status": "ok"}


@router.post("/chat")
async def chat(
    payload: ChatRequest, graph: Graph, principal: CurrentPrincipal
) -> StreamingResponse:
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
    #
    # ★ M4에서 예고한 대로 "여기 한 줄"이었다 ★
    # 2b에서 "M4의 Langfuse callbacks도 같은 dict에 들어간다"고 적어뒀던 그 자리다.
    # graph.py도 ai_sdk.py도 프론트도 안 바뀐다 — RunnableConfig가 LangChain 공통
    # 규약이라, 그래프 안의 모든 노드·모델·도구 호출이 이 콜백을 자동으로 상속한다.
    # 우리가 노드마다 계측 코드를 심을 일이 없다는 뜻이고, 그게 이 배선의 값이다.
    #
    # metadata는 트레이스에 붙는 꼬리표다. langfuse_session_id로 thread_id를 넘겨
    # Langfuse Sessions 뷰의 묶음이 우리 대화 단위와 일치하게 만든다.
    # 키가 없으면 get_callbacks()가 빈 리스트를 주고, 빈 callbacks는 LangChain이
    # 그냥 무시한다 → 트레이싱 없이도 이 코드 경로가 똑같이 동작한다.
    config = {
        "configurable": {"thread_id": payload.id},
        "callbacks": get_callbacks(),
        "metadata": trace_metadata(payload.id),
    }

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
            # ★ M12: principal을 그래프 입력에 실는다 ★ config가 아니라 입력인 이유는
            # State 주석 참고. 체크포인터가 State를 저장하므로 이 값도 함께 저장되는데,
            # 매 턴 덮어써지고 리스트처럼 쌓이지 않아 문제되지 않는다.
            {"messages": [{"role": "user", "content": text}], "principal": principal},
            config,
            stream_mode="messages",
        ):
            # ★ 2c에서 필터가 하나 늘었다 ★
            # stream_mode="messages"는 "메시지"를 흘리지 "LLM 토큰"만 흘린다고
            # 약속한 적이 없다. 도구 노드가 생기면서 ToolMessage(도구 실행 결과)도
            # 같은 통로로 나온다. 그건 모델에게 건네줄 재료지 사용자에게 보여줄
            # 글이 아니다 — 안 거르면 답변 앞에 원시 결과가 그대로 찍힌다.
            if not isinstance(chunk, AIMessageChunk):
                continue

            # chunk.content가 아니라 chunk.text를 쓴다.
            # (이하 기존 주석 그대로)
            if chunk.text:
                yield chunk.text

    def sources() -> list[dict[str, str]]:
        """스트림이 끝난 뒤 "무엇을 근거로 답했나"를 그래프 상태에서 꺼낸다. (M10)

        ★ 함수로 넘기는 이유 ★ ui_message_stream은 응답을 만들기 시작할 때 생성되는데,
        그 시점에는 아직 검색이 안 끝났다. 값을 넘기면 항상 빈 리스트가 된다 —
        에러 없이 인용 카드만 안 나오는, 찾기 어려운 종류의 버그다.

        get_state는 체크포인터에서 이번 턴의 최종 State를 읽는다. 2b에서 상태의
        주인을 서버로 옮겨둔 덕에 "방금 그 턴이 무엇을 봤는지"를 물어볼 곳이 있다.
        """
        snapshot = graph.get_state(config)
        chunks = snapshot.values.get("retrieved") or []
        # ★ 중복 제거 ★ 같은 문서의 여러 청크가 top-5에 들어오는 일이 흔하다.
        # 인용 카드에 같은 파일이 세 번 뜨면 사용자에게는 잡음이다.
        seen: set[str] = set()
        parts = []
        for chunk in chunks:
            part = source_part(chunk)
            if part["sourceId"] in seen:
                continue
            seen.add(part["sourceId"])
            parts.append(part)
        return parts

    return StreamingResponse(
        ui_message_stream(text_deltas(), sources),
        media_type="text/event-stream",
        headers=UI_MESSAGE_STREAM_HEADERS,
    )
