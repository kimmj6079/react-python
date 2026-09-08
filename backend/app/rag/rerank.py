# LLM 리랭킹. 하이브리드가 넉넉히 뽑아온 후보의 **순서를 바로잡는다**. (M8-b)
#
# ★ 역할 분담이 이 마일스톤의 개념 전부다 ★
#   하이브리드 검색 → 재현율(recall). 정답을 후보 안에 들여놓는다.  top-20
#   리랭킹        → 정밀도(precision). 후보 순서를 바로잡는다.      top-5
#   생성          → 답을 만든다.                                    문맥 5개
# 검색은 "비슷한가"만 볼 수 있지만(임베딩은 질문을 이해하지 못한다), 리랭커는 질문과
# 문서를 같이 읽고 "이게 이 질문에 답이 되는가"를 판단한다. 그래서 순서가 달라진다.
import asyncio
import logging

from anthropic import AsyncAnthropic
from pydantic import BaseModel, Field

from app.core.config import settings
from app.rag.base import TOP_K, RetrievedChunk

logger = logging.getLogger(__name__)


class Relevance(BaseModel):
    """★ structured output으로 형식을 강제한다 ★

    자유 텍스트로 "8점 정도"를 받아 파싱하면 모델이 "8/10", "높음", "8점입니다" 같은
    변주를 낼 때마다 깨진다. 그리고 **깨진 문서는 조용히 0점이 되어 순위 맨 뒤로 간다** —
    리랭커가 일을 안 한 게 아니라 파싱이 실패한 건데, 겉으로는 구분되지 않는다.
    judge.py에서 같은 판단을 한 것과 정확히 같은 이유다.

    0~10 정수로 좁게 잡은 것도 같다. 0~1 실수는 재현성이 없다.
    """

    score: int = Field(
        ge=0, le=10, description="이 문서가 질문에 답이 되는 정도. 10=직접 답, 0=무관"
    )


PROMPT = """질문에 이 문서 조각이 얼마나 답이 되는지 0~10으로 매겨라.

[질문]
{question}

[문서 조각]
{content}

기준: 10=질문에 직접 답한다 · 5=관련 주제지만 답은 아니다 · 0=무관하다.
문서가 사실인지가 아니라 **이 질문에 답이 되는지**만 본다."""


async def _score(client: AsyncAnthropic, question: str, chunk: RetrievedChunk) -> int:
    try:
        response = await client.messages.parse(
            model=settings.anthropic_rerank_model,
            max_tokens=64,
            messages=[
                {
                    "role": "user",
                    "content": PROMPT.format(question=question, content=chunk.content[:2000]),
                }
            ],
            output_format=Relevance,
        )
        return response.parsed_output.score
    except Exception:
        # ★ 한 문서의 실패가 전체를 죽이면 안 된다 ★ 30개 중 하나가 레이트리밋에
        # 걸렸다고 검색 전체가 실패하면, 리랭커를 붙인 대가로 가용성을 잃는 것이다.
        # -1을 주면 아래 정렬에서 원래 순위를 그대로 쓰게 된다(점수 동률 처리와 같은 효과).
        logger.warning("리랭킹 실패 - 이 문서는 원래 순위를 유지한다: %s", chunk.source)
        return -1


async def rerank(
    question: str,
    chunks: list[RetrievedChunk],
    top_k: int = TOP_K,
    client: AsyncAnthropic | None = None,
) -> list[RetrievedChunk]:
    """후보를 질문 적합도로 다시 정렬해 top_k만 남긴다.

    ★ 문서별 독립 점수 + 병렬 (README의 (B) 안) ★
    후보 20개를 한 프롬프트에 넣고 "순위를 내라"고 하는 (A) 안이 호출 1번으로 싸다.
    안 고른 이유 셋:
      - 긴 문맥에서 중간을 흘린다(lost in the middle)
      - 후보 하나가 길면 예산을 다 먹는다
      - 한 문서의 점수가 다른 문서에 영향받아 **결정론적이지 않다**
    독립 점수는 호출이 20번이지만 각 프롬프트가 짧고, 실패한 하나만 재시도할 수 있고,
    asyncio.gather로 병렬이라 벽시계 시간은 거의 한 번 호출과 같다.

    ★ 실패하면 원래 순서로 폴백한다 ★ 리랭커 장애가 검색 전체 장애가 되면 안 된다.
    graph.py의 retrieve 노드가 검색 실패를 삼키는 것과 같은 판단이다 —
    리랭킹은 "있으면 더 좋은" 보조 단계지 필수 경로가 아니다.
    """
    if not chunks:
        return []

    client = client or AsyncAnthropic(api_key=settings.anthropic_api_key)
    try:
        scores = await asyncio.gather(*(_score(client, question, c) for c in chunks))
    except Exception:
        logger.exception("리랭킹 전체 실패 - 검색 순서를 그대로 쓴다")
        return chunks[:top_k]

    # ★ 정렬 키에 원래 순위를 함께 넣는다 ★ 점수가 같으면(흔하다 — 0~10 정수라
    # 동률이 많다) 검색이 매긴 순서를 그대로 존중한다. 안 그러면 동률일 때 순서가
    # 파이썬 정렬의 안정성에만 의존하는 것처럼 보여 의도가 안 읽힌다.
    order = sorted(
        range(len(chunks)),
        key=lambda i: (-scores[i], i),
    )
    reranked = [chunks[i] for i in order[:top_k]]

    # ★ 순위 변동량을 남긴다 ★ README의 함정: "리랭킹 후 top-5가 원래 top-5와 매번
    # 같으면 리랭커가 일을 안 하고 있다." 프롬프트가 나빠서 모든 문서에 같은 점수를
    # 주는 경우가 흔한데, 지표만 봐서는 "효과 없음"과 구분되지 않는다.
    moved = sum(1 for rank, i in enumerate(order[:top_k]) if rank != i)
    logger.info(
        "리랭킹: 후보 %d -> %d, 상위 %d 중 %d개 순위 변동, 점수 %s",
        len(chunks),
        top_k,
        top_k,
        moved,
        sorted(scores, reverse=True)[:top_k],
    )
    return reranked
