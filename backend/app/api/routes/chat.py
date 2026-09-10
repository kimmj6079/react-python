# 챗봇 HTTP 라우터. 여기서는 요청을 받아 그래프를 돌리고 텍스트 델타를
# 꺼내는 일만 한다. 와이어 포맷(AI SDK 프로토콜) 변환은 app/core/ai_sdk.py에 위임한다.
import logging
from typing import Any

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
from app.core.config import settings
from app.core.timing import current as current_timings
from app.core.timing import mark, request_timings
from app.core.tracing import get_callbacks, record_feedback, trace_id_of, trace_metadata
from app.schemas.chat import ChatRequest, FeedbackRequest

logger = logging.getLogger(__name__)

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
    # ★ M13: 콜백 리스트를 변수로 받는다 ★ 예전에는 dict 안에서 바로 불렀는데,
    # 이제 스트림이 끝난 뒤 "이번 요청이 만든 트레이스가 무엇인가"를 그 핸들러에게
    # 물어봐야 한다(아래 metadata()). 키가 없으면 빈 리스트라 그 질문의 답도 None이고,
    # 트레이싱이 꺼진 환경에서는 피드백 버튼이 애초에 안 그려진다.
    callbacks = get_callbacks()
    config = {
        "configurable": {"thread_id": payload.id},
        "callbacks": callbacks,
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
                # ★ M13-b: TTFT를 여기서 찍는다 ★ 사용자가 실제로 기다린 시간은
                # "생성이 얼마나 걸렸나"가 아니라 **"첫 글자가 언제 나왔나"** 다.
                # 매 델타마다 부르지만 mark()가 첫 호출만 기록한다 — "지금이 첫
                # 번째인가"를 호출하는 쪽이 판단하게 두면 그 판단이 빠지는 날
                # 조용히 틀린 숫자가 된다.
                mark("ttft")
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

    def metadata() -> dict[str, str]:
        """이 응답을 나중에 가리킬 수 있는 손잡이를 프론트에 준다. (M13)

        ★ sources()와 같은 이유로 함수다 ★ 값으로 넘기면 스트림을 만들 때 평가되어
        항상 비어 있다. 여기서는 실제로는 그래프 시작 직후면 값이 차 있지만(실측:
        핸들러가 관측 **시작** 시점에 대입한다), 그 타이밍에 기대는 코드를 쓰면
        SDK가 대입 시점을 바꾸는 날 조용히 빈 값이 된다.

        키가 없으면 빈 dict → ui_message_stream이 messageMetadata 자체를 안 붙인다
        → 프론트에 message.metadata가 없다 → 피드백 버튼이 안 그려진다.
        **"저장할 곳이 없으면 버튼도 없다"가 세 계층에 걸쳐 자동으로 성립한다.**
        """
        meta: dict[str, Any] = {}

        trace_id = trace_id_of(callbacks)
        if trace_id:
            meta["traceId"] = trace_id

        # ★ M13-b: 13-a에서 만든 자리에 지연 예산이 그대로 얹힌다 ★
        # 새 엔드포인트도 새 파트도 필요 없었다 — "응답에 꼬리표를 붙이는 통로"를
        # 한 번 뚫어두면 두 번째부터는 필드 하나다.
        timings = current_timings()
        if timings is not None:
            # ★ 로그는 설정과 무관하게 항상 남긴다 ★ 와이어로 내보내는 것(아래)은
            # 클라이언트에 내부 구조를 노출하는 일이라 끌 수 있어야 하지만,
            # **우리 서버 로그에서 지연을 볼 수 없게 되는 것은 다른 문제다.**
            # 관측을 끄는 스위치와 노출을 끄는 스위치를 같은 것으로 두면 안 된다.
            logger.info("지연 예산: %s", timings.log_line())
            if settings.timings_in_response:
                meta["timings"] = timings.summary()

        return meta

    async def timed_stream():
        """계측 문맥을 스트림 **전체**에 씌운다. (M13-b)

        ★ 왜 라우터 본문에서 `with`를 열면 안 되는가 ★
        이 함수가 `return StreamingResponse(...)`를 하는 순간 라우터는 **이미 끝난다.**
        실제 스트리밍(그래프 실행 · 검색 · 생성)은 그 뒤에, 보통 다른 태스크에서
        일어난다. 라우터 본문에서 연 `with`는 그 전에 닫혀버려서 **계측치가 전부
        빈 채로 나온다 — 에러 없이.**
        M10에서 sources_fn을 값이 아니라 함수로 넘겨야 했던 것과 뿌리가 같은 함정이다:
        **"라우터가 끝나는 시점"과 "응답이 만들어지는 시점"은 다르다.**

        제너레이터 안에서 열면 첫 프레임을 만들 때 진입하고 마지막 프레임 뒤에
        빠져나가므로, metadata()가 불리는 시점(finish 프레임)까지 정확히 살아 있다.
        """
        with request_timings():
            async for frame in ui_message_stream(text_deltas(), sources, metadata):
                yield frame

    return StreamingResponse(
        timed_stream(),
        media_type="text/event-stream",
        headers=UI_MESSAGE_STREAM_HEADERS,
    )


@router.post("/chat/feedback", status_code=202)
def chat_feedback(payload: FeedbackRequest) -> dict[str, str]:
    """👍/👎를 그 답변의 Langfuse 트레이스에 score로 붙인다. (M13)

    ★ 202 Accepted인 이유 ★ record_feedback은 큐에 넣고 바로 돌아온다(백그라운드
    스레드가 배치로 전송). 200 OK는 "처리가 끝났다"는 뜻인데 실제로는 아직 안 갔으므로
    202가 정직하다. M11의 업로드가 202를 쓴 것과 같은 판단이다.

    ★ 지금 없는 것 = 실무라면 반드시 있어야 하는 것 ★
      - **인증**: 지금은 누구나 아무 traceId로 점수를 넣을 수 있다. 남의 대화에 👎를
        도배하는 것도 가능하다. 실무라면 deps.get_principal의 자리에서 소유권을 본다.
      - **레이트리밋**: 엄지 연타 = score 연타다. 지금은 같은 트레이스에 100개가 쌓인다.
      - **멱등성**: 절반만 돼 있다. record_feedback이 score_id를 trace_id로 고정해
        "트레이스당 하나"까지는 보장하지만(M11의 uuid5 포인트 id와 같은 기법),
        사용자 개념이 없어 "사용자당 하나"는 표현할 수 없다. 인증이 붙는 날
        f"{trace_id}:{user_id}"로 넓히면 위 세 가지가 같이 해결된다.
    """
    if not settings.langfuse_enabled:
        # ★ 조용히 200을 주지 않는다 ★ 저장할 곳이 없는데 "접수했다"고 답하면
        # 사용자는 피드백이 쌓이는 줄 알고, 우리는 왜 데이터가 없는지 모른다.
        # 503(Service Unavailable) = "이 기능이 지금 구성돼 있지 않다".
        raise HTTPException(
            status_code=503,
            detail="트레이싱이 꺼져 있어 피드백을 저장할 수 없다 (LANGFUSE_* 키 필요)",
        )

    record_feedback(
        payload.trace_id,
        positive=payload.value == "up",
        comment=payload.comment,
    )
    return {"status": "accepted"}
