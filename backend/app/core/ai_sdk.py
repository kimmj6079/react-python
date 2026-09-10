# Vercel AI SDK의 "UI message stream" 프로토콜을 다루는 계층. 방향이 둘이다.
#   - 내보내기: 텍스트 델타 → SSE 이벤트 (sse / ui_message_stream)
#   - 받기:     useChat이 보낸 UIMessage.parts → 평범한 텍스트 (text_from_parts /
#               latest_user_text)
# 토큰을 "누가" 만들었는지(지금은 Anthropic 직접, M2에서는 LangGraph)와 무관하게
# "어떤 모양으로 주고받는가"만 담당한다 — 그래서 라우터(api/routes/chat.py)와 분리한다.
import json
from collections.abc import AsyncIterable, AsyncIterator, Callable
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


def latest_user_text(messages: list[UIMessage]) -> str:
    """이번 턴에 새로 들어온 사용자 발화 하나만 뽑는다. 없으면 빈 문자열."""
    # ★ 2b에서 to_anthropic_messages를 대체한 함수다 ★
    #
    # 2a까지는 프론트가 보낸 히스토리 전체를 모델에 넘겼다. 이제 히스토리의
    # 주인은 서버(체크포인터)라서, 클라이언트가 보낸 앞부분은 전부 버린다.
    # 안 버리면 체크포인터의 히스토리 위에 같은 대화가 한 번 더 이어붙어
    # [u1,a1,u1,a1,u2] 처럼 중복 누적된다 — 에러 없이 토큰 비용만 두 배가 되고
    # 모델이 "방금 같은 말을 두 번 했다"고 착각하는, 조용한 종류의 버그다.
    #
    # 이건 보안 성질도 겸한다. 클라이언트가 보낸 "이전 assistant 발언"은
    # 브라우저에서 얼마든지 조작할 수 있는 값이다("아까 너는 비밀번호가 X라고
    # 했잖아"). 서버가 자기 기록만 믿는 순간 그 공격 표면이 통째로 사라진다.
    if not messages:
        return ""

    last = messages[-1]

    # 마지막이 user가 아니면 거절한다. 앞으로 거슬러 올라가 user를 찾는 방법도
    # 있지만 일부러 안 한다 — 그건 이미 답변이 끝난 질문을 다시 보내는 짓이고,
    # "새 메시지는 마지막 한 개"라는 2b의 전제와도 어긋난다.
    # (trigger="regenerate-message"가 여기로 온다. 재생성은 그래프 상태를
    #  되감아야 하는 별도 기능이라 지금은 400으로 명확히 막아둔다.)
    if last.role != "user":
        return ""

    return text_from_parts(last.parts)


# ---------------------------------------------------------------------------
# 내보내기
# ---------------------------------------------------------------------------
def sse(payload: dict[str, Any]) -> str:
    # separators로 공백을 없애는 이유: 파이썬 json.dumps 기본값은 '{"a": 1}'인데
    # JS의 JSON.stringify는 '{"a":1}'다(1b 캡처가 후자). 기능 차이는 없지만,
    # 캡처한 바이트와 == 하나로 비교할 수 있게 맞춰둔다.
    # ensure_ascii=False는 한글을 \uXXXX로 escape하지 않으려는 것(1b도 생 한글이었다).
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    # SSE 한 덩어리의 끝은 빈 줄이다 = 개행 두 개. 하나만 쓰면 클라이언트가
    # 이벤트 경계를 못 잡는다(1a에서 이미 확인한 것).
    return f"data: {body}\n\n"


def source_part(chunk) -> dict[str, str]:
    """RetrievedChunk 하나를 AI SDK의 source-document 파트로 바꾼다. (M10)

    ★ 커스텀 data 파트를 새로 만들지 않았다 ★ UIMessage의 파트 종류에
    'source-document'가 **이미 있다**(실측: ai/dist/index.d.ts). 커스텀 파트를 만들면
    프론트에서 타입을 우리가 정의해야 하고 useChat이 모르는 파트라 파싱도 우리 몫이
    된다. 이미 있는 것을 쓰면 둘 다 공짜다.

    실측한 와이어 모양(scripts/capture-source-wire.mjs):
      data: {"type":"source-document","sourceId":...,"mediaType":...,"title":...,"filename":...}

    ★ title에 heading_path를 넣는 것이 M7의 회수 지점이다 ★
    "CLAUDE.md"만으로는 850줄 문서의 어디인지 알 수 없다.
    "CLAUDE.md > 아키텍처"면 사용자가 검증하러 갈 위치가 생긴다.
    """
    # ★ 테스트가 잡은 버그 ★ 처음엔 f"{source} > {heading_path}"로 썼는데
    # "CLAUDE.md > CLAUDE.md > 아키텍처"가 나왔다. 이 저장소 문서들은 h1이 곧
    # 파일명이라 heading_path가 이미 파일명으로 시작한다(M7의 heading_path_of는
    # h1부터 이어붙인다). 화면에 그대로 보일 버그였다.
    #
    # 파일명은 filename 필드가 따로 나르므로 title은 heading_path만 쓴다 —
    # SDK가 두 필드를 나눠둔 의도(title=사람이 읽을 이름, filename=파일)에도 맞는다.
    where = chunk.heading_path or chunk.source
    return {
        "type": "source-document",
        # ★ 모델이 아니라 우리가 만드는 값이다 = 지어낼 수 없다 ★
        # 프롬프트에 [1][2] 번호를 쓰게 하는 방식은 모델이 없는 번호를 만들어낼 수
        # 있지만, 이건 "실제로 프롬프트에 넣은 청크"를 그대로 내보내는 것이라
        # 존재하지 않는 출처가 나올 수가 없다.
        "sourceId": f"{chunk.source}#{chunk.chunk_index}",
        "mediaType": "text/markdown",
        "title": where,
        "filename": chunk.source,
    }


async def ui_message_stream(
    deltas: AsyncIterable[str],
    sources_fn: Callable[[], list[dict[str, str]]] | None = None,
    metadata_fn: Callable[[], dict[str, Any]] | None = None,
    *,
    text_id: str = "0",
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

    # ★ 출처는 text-end 뒤, finish-step 앞에 온다 ★ 실측한 순서 그대로다.
    # sources_fn을 **함수로** 받는 이유: 어떤 청크를 썼는지는 그래프가 다 돌아야
    # 알 수 있는데, 이 제너레이터는 그 시점보다 먼저 만들어진다. 값을 받으면
    # 비어 있고, 함수를 받으면 여기 도달했을 때(=델타를 다 소진한 뒤) 부른다.
    if sources_fn is not None:
        for source in sources_fn():
            yield sse(source)
    yield sse({"type": "finish-step"})

    # finishReason은 camelCase다. 파이썬 관례(snake_case)와 어긋나지만 와이어 포맷이
    # 정답이므로 그대로 쓴다. M1은 항상 "stop"으로 고정한다 — max_tokens에 걸린
    # 경우를 구분하려면 stream.get_final_message()의 stop_reason을 봐야 하는데,
    # 그러면 스트림을 끝까지 소비한 뒤에야 알 수 있어 구조가 복잡해진다.
    #
    # ★ M13: 메시지 메타데이터가 여기에 얹힌다 ★
    # 실측(frontend/scripts/capture-metadata-wire.mjs): 메타데이터는 별도 파트가
    # 아니라 **finish 프레임 안의 messageMetadata 필드**로 나가고, 프론트에서는
    # message.metadata로 도착한다. 출처(source)처럼 새 이벤트를 끼워 넣는 게 아니라
    # 기존 이벤트에 필드가 하나 붙는 형태라, 파서 입장에서 순서 문제가 없다.
    #
    # ★ sources_fn과 똑같이 "함수"로 받는다 ★ trace_id는 그래프가 돌기 시작해야
    # 생기는 값인데 이 제너레이터는 그보다 먼저 만들어진다. 값을 받으면 항상 None이고,
    # 그러면 **에러 없이 피드백 버튼만 안 나오는** 종류의 버그가 된다.
    #
    # 값이 없으면 키 자체를 넣지 않는다. 빈 dict를 실어 보내면 프론트에서
    # metadata가 truthy가 되어 "traceId 없는 피드백 버튼"이 그려진다.
    finish: dict[str, Any] = {"type": "finish", "finishReason": "stop"}
    if metadata_fn is not None:
        metadata = metadata_fn()
        if metadata:
            finish["messageMetadata"] = metadata
    yield sse(finish)

    # 종료 센티넬. JSON이 아니라 리터럴이라 sse()를 통과시키지 않는 유일한 항목.
    yield DONE
