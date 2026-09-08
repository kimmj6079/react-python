# 대화형 질의 재작성. 히스토리에 의존하는 질문을 "혼자 읽어도 되는" 질문으로 바꾼다. (M9)
#
# ★ 이건 프롬프트 튜닝으로 못 고치는 문제다 ★
#   사용자: VITE_API_URL은 어떻게 동작해?
#   챗봇  : (설명)
#   사용자: 그거 프로덕션에서는?     <- 이걸 그대로 임베딩하면 검색이 완전히 실패한다
#
# "그거"가 무엇인지는 **대화 히스토리에만** 있고 검색기는 히스토리를 보지 않는다.
# 아무리 좋은 임베딩 모델도 "그거 프로덕션에서는?"이라는 문장에서 VITE_API_URL을
# 복원할 수는 없다 — **검색 입력 자체가 잘못됐다.**
#
# M6~M8의 골든셋은 전부 단발 질문이라 이 실패를 한 번도 잡아내지 못했다.
# M9에서 multiturn 5건을 넣고 재작성 없이 재보니 MRR 0.300이었다(normal은 0.771).
import logging

from anthropic import AsyncAnthropic
from pydantic import BaseModel, Field

from app.core.config import settings

logger = logging.getLogger(__name__)


class Rewritten(BaseModel):
    """structured output으로 형식을 강제한다 — rerank.py·judge.py와 같은 이유다.

    자유 텍스트로 받으면 모델이 "재작성된 질문: ..." 같은 접두어를 붙이거나 설명을
    덧붙이는데, **그게 그대로 임베딩되어 검색 품질을 조용히 떨어뜨린다.**
    """

    question: str = Field(description="히스토리 없이도 혼자 읽히는 완전한 질문 한 문장")


PROMPT = """아래 대화의 마지막 질문을, 대화를 모르는 사람도 이해할 수 있는 \
독립적인 질문 한 문장으로 다시 써라.

[이전 대화]
{history}

[마지막 질문]
{question}

규칙:
- 대명사("그거", "그건", "거기")와 생략된 주어를 앞 대화에서 찾아 실제 이름으로 바꾼다.
- 새로운 정보를 지어내지 않는다. 앞 대화에 없는 내용을 추가하면 안 된다.
- 질문의 의도와 범위를 바꾸지 않는다. 넓히지도 좁히지도 않는다.
- 이미 독립적으로 읽히는 질문이면 그대로 둔다."""


def format_history(history: list[dict[str, str]]) -> str:
    labels = {"user": "사용자", "assistant": "챗봇"}
    return "\n".join(f"{labels.get(m['role'], m['role'])}: {m['content']}" for m in history)


async def rewrite_query(
    question: str,
    history: list[dict[str, str]],
    client: AsyncAnthropic | None = None,
) -> str:
    """히스토리가 있으면 독립적인 질문으로 재작성하고, 없으면 그대로 돌려준다.

    ★ 조건부 실행이 핵심이다 ★ README의 함정: "항상 재작성하면 손해다."
      - 첫 턴은 재작성할 게 없는데 지연만 는다(LLM 호출 한 번이 통째로 낭비)
      - 잘 쓰인 질문을 재작성하다 뉘앙스가 죽는 경우가 실제로 있다
    그래서 히스토리가 없으면 **LLM을 아예 안 부르고** 원문을 그대로 돌려준다.
    M2에서 배운 조건부 엣지의 사고방식을 노드 안쪽에서 한 번 더 쓴다.

    ★ 실패하면 원문을 쓴다 ★ 재작성은 "있으면 더 좋은" 단계지 필수 경로가 아니다.
    rerank.py의 폴백, graph.py의 검색 실패 처리와 같은 판단이다.
    """
    if not history:
        return question

    client = client or AsyncAnthropic(api_key=settings.anthropic_api_key)
    try:
        response = await client.messages.parse(
            model=settings.anthropic_rewrite_model,
            max_tokens=256,
            messages=[
                {
                    "role": "user",
                    "content": PROMPT.format(history=format_history(history), question=question),
                }
            ],
            output_format=Rewritten,
        )
        rewritten = response.parsed_output.question.strip()
    except Exception:
        logger.exception("질의 재작성 실패 - 원문으로 검색한다")
        return question

    if not rewritten:
        return question

    # ★ 재작성 전/후를 반드시 남긴다 ★ README의 함정: 나중에 "왜 이 질문에서 검색이
    # 실패했지?"를 추적할 때 로그에 원 질문만 있으면 영원히 못 찾는다.
    # **실제 실패 원인의 상당수가 재작성 단계에서 생긴 왜곡이다** — 모델이 "그거"를
    # 엉뚱한 것으로 해석하면 그 뒤 검색·생성이 전부 틀린 것을 열심히 한다.
    logger.info("질의 재작성: %r -> %r", question, rewritten)
    return rewritten
