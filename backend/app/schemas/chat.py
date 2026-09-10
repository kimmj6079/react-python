# 챗봇 API가 주고받는 데이터 형태. schemas/item.py와 같은 역할이다.
#
# 여기 정의된 모양은 추측이 아니라 실측이다: useChat이 POST하는 본문 구조를
# frontend/node_modules/ai/dist/index.js의 HttpChatTransport에서 직접 확인했다
# (ai@7.0.73). 근거와 줄 번호는 chatbot/README.md의 M1-1c 항목에 적어뒀다.
# ai 버전을 올리면 그 코드를 다시 봐야 한다.
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class UIMessage(BaseModel):
    # AI SDK의 UIMessage 한 개 = 브라우저가 들고 있는 대화 히스토리의 한 줄.
    id: str
    # role은 3종으로 고정이라 Literal로 좁게 잡는다. 좁게 잡으면 예상 못 한 값이
    # 422로 시끄럽게 걸리고, /docs에도 "3개 중 하나"로 문서화된다.
    role: Literal["system", "user", "assistant"]

    # parts는 반대로 넓게 받는다. AI SDK의 파트 타입은 11종이고 앞으로 늘어나는데
    # (text/file/tool/reasoning/source/data/...) 우리가 쓰는 건 text 하나다.
    # 유니온으로 다 모델링하면 SDK가 파트를 하나 추가하는 순간 정상 요청이 422로
    # 거부된다. dict로 받아 필요한 것만 골라내면 모르는 파트는 그냥 통과한다.
    parts: list[dict[str, Any]]


class ChatRequest(BaseModel):
    # populate_by_name: alias("messageId")와 필드명("message_id") 양쪽으로 입력받게 한다.
    # 안 켜면 pytest에서 ChatRequest(message_id=...)로 객체를 만들 수 없다.
    model_config = ConfigDict(populate_by_name=True)

    # 채팅 세션 id. useChat이 자동 생성해 매 요청에 같은 값을 보낸다.
    # M1에서는 쓰지 않지만, M2에서 LangGraph thread_id로 쓸 1순위 후보가 이 값이다.
    id: str

    # 대화 히스토리 전체. 서버가 무상태이므로 매 요청에 처음부터 다 들어온다.
    messages: list[UIMessage]

    # 'submit-message'(새 메시지) | 'regenerate-message'(응답 재생성).
    # 지금 구분해서 처리하진 않지만, 정의해두지 않으면 Pydantic 기본값
    # extra="ignore"가 조용히 버려서 무엇이 오는지조차 모르게 된다.
    trigger: str | None = None

    # 재생성 대상 메시지 id. 새 메시지일 때 JS 쪽 값이 undefined이고
    # JSON.stringify가 그런 키를 통째로 빼므로 "없을 수 있는 값"이어야 한다.
    message_id: str | None = Field(default=None, alias="messageId")


class FeedbackRequest(BaseModel):
    """👍/👎 한 번. (M13)

    ★ 프론트가 traceId를 되돌려 보내는 구조다 ★ 서버가 "마지막 트레이스"를 기억해뒀다가
    쓰는 방법도 있지만, 그러면 사용자가 세 턴 전 답변에 엄지를 누를 때 엉뚱한 트레이스에
    점수가 붙는다. **어느 답변에 대한 피드백인지는 화면만 알고 있다** — 그래서 화면이
    말해줘야 한다. finish 프레임에 traceId를 실어 보낸 이유가 이것이다.
    """

    model_config = ConfigDict(populate_by_name=True)

    # 32자리 hex. Langfuse가 만든 값이고 우리는 그대로 돌려받기만 한다.
    # 형식을 여기서 정규식으로 검증하지 않는 이유: 검증해서 얻는 것이 "422가 조금 더
    # 빨리 난다"뿐이고, 대신 Langfuse가 id 형식을 바꾸면 우리가 먼저 깨진다.
    trace_id: str = Field(alias="traceId", min_length=1)

    # ★ Literal로 좁게 받는다 ★ bool로 받으면 나중에 "그저 그럼"이나 별점을 넣고 싶을 때
    # 와이어 포맷이 통째로 바뀐다. 문자열 유니온이면 값을 하나 더 늘리는 것으로 끝난다.
    value: Literal["up", "down"]

    # 자유 텍스트 사유(선택). max_length가 없으면 브라우저가 10MB를 보내도 그대로
    # Langfuse로 흘러간다 — **외부로 나가는 값에는 항상 상한을 건다**(M11의 업로드
    # 크기 제한과 같은 규칙).
    comment: str | None = Field(default=None, max_length=1000)
