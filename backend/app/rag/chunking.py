# 문서 청킹. (M7-1)
#
# 3-1의 청킹은 "N자마다 자르기"였다. 그게 깨지는 지점 셋을 이 파일이 순서대로 고친다:
#   ① 문장·표·코드블록 중간을 자른다      -> 마크다운 구조 인식 분할
#   ② 청크만 떼면 어느 대목인지 모른다     -> heading_path 추출 (본문 부착은 M7-2)
#   ③ 문자 수 기준이라 언어별 토큰이 다르다 -> 임베딩 모델의 진짜 토크나이저로 길이를 잰다
#
# ★ ③이 왜 문제인지 실측 (scripts/probe_chunking.py) ★
#   한글 31자 -> 17 토큰 (문자당 0.55)
#   영어 57자 -> 11 토큰 (문자당 0.19)
# 같은 "600자"가 언어에 따라 토큰 수가 약 3배 차이 난다. 문자로 자르면 어떤 청크는
# 임베딩 한도에 아슬아슬하고 어떤 청크는 절반도 안 쓰는데, 그 편차가 눈에 안 보인다.
from __future__ import annotations

import logging
from collections.abc import Callable

from langchain_text_splitters import (
    Language,
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)

from app.rag.base import Chunk

logger = logging.getLogger(__name__)

# 어느 깊이까지 섹션으로 쪼갤 것인가. h4까지 본다 — 이 저장소 문서들이 실제로 h4를 쓴다.
HEADERS = [("#", "h1"), ("##", "h2"), ("###", "h3"), ("####", "h4")]

# ★ e5의 입력 한도는 512 "토큰"이고, 넘으면 에러가 아니라 조용히 잘린다 ★
# 실측한 고정 비용 4토큰을 빼고 쓴다: CLS/SEP 2 + fastembed가 붙이는 "passage: " 2.
E5_INPUT_LIMIT = 512
RESERVED_TOKENS = 4

# ★ 기본 크기를 220으로 잡은 이유 — 베이스라인과 "크기"를 맞추기 위해서다 ★
# 3-1의 600자 청크가 실측 158~264토큰(평균 ~210)이었다. 여기서 크기까지 같이 키우면
# 지표가 움직였을 때 "구조 인식 덕분"인지 "청크가 커진 덕분"인지 구분할 수 없다.
# M6를 만든 이유가 그 구분이므로, 첫 변화는 **경계를 어디에 긋는가만** 바꾼다.
# (크기 스윕은 별도 실험으로 돌린다 — 인자로 뺀 이유)
MAX_TOKENS = 220
OVERLAP_TOKENS = 40

# ★ 이보다 작은 조각은 이웃과 합친다 (M7-1b) ★
# 안 합치면 실제로 이런 것들이 청크가 된다(실측):
#   4토큰  "```"                     <- 닫는 코드펜스 하나. 순수 쓰레기
#   6토큰  "## 저장소 구조"           <- 헤딩만 남고 본문은 코드펜스 경계에서 잘려나감
#   7토큰  "## 자주 쓰는 명령어"       <- CLAUDE.md와 DEPLOYMENT.md 양쪽에 있어 서로 경쟁까지 한다
# 전체의 4.9%였다. 이런 조각은 검색되면 top-k 한 자리를 잡아먹으면서 모델에게는
# 아무 근거도 주지 않는다 — 잡음이자 예산 낭비다.
MIN_TOKENS = 40


# Chunk 타입은 app/rag/base.py(계약)에 있다 — 두 store가 같은 모양을 받아야 하므로
# "청킹 구현의 사정"이 아니라 계약의 일부다. EMBEDDING_DIM을 계약으로 옮긴 것과 같은 이유.


_tokenizer = None


def _get_tokenizer():
    """★ 임베딩 모델이 실제로 쓰는 토크나이저를 그대로 꺼내 쓴다 ★

    chatbot/README.md의 M7 계획은 `client.messages.count_tokens`(Claude 토크나이저)로
    재라고 적혀 있었다. 실제로 만들어보니 그건 **다른 질문에 대한 답**이었다:

      | 무엇을 재는가 | 어느 토크나이저 | 언제 |
      |---|---|---|
      | 이 청크가 임베딩될 때 잘리는가 | **e5** (여기) | 청킹 시점 |
      | 이 문맥이 프롬프트 예산을 얼마나 먹는가 | Claude `count_tokens` | 검색 후 (M13) |

    청킹의 길이 함수는 앞쪽이다. e5의 512 토큰 한도를 넘으면 **에러 없이 뒷부분이
    날아가므로**, 그 한도를 정확히 아는 토크나이저로 재야 한다. Claude 토크나이저로
    재면 숫자가 다르고, 무엇보다 `count_tokens`는 API 호출이라 재귀 분할의 길이
    함수로 쓰면 문서 하나에 수천 번을 부르게 된다 — 애초에 쓸 수 없다.

    (tiktoken을 안 쓰는 이유는 README 그대로다. 그건 OpenAI 토크나이저라 여기서도
    저기서도 맞지 않는다 — 틀린 이유가 하나 더 있을 뿐이다.)
    """
    global _tokenizer
    if _tokenizer is None:
        # embedding.py의 lazy 싱글턴을 재사용한다. 모델을 두 번 올리면 2.24GB가 두 배다.
        from app.rag.embedding import get_model

        _tokenizer = get_model().model.tokenizer
    return _tokenizer


def token_length(text: str) -> int:
    """e5 토크나이저 기준 토큰 수. RecursiveCharacterTextSplitter의 length_function."""
    return len(_get_tokenizer().encode(text).ids)


def heading_path_of(metadata: dict[str, str]) -> str:
    # MarkdownHeaderTextSplitter가 넣어주는 h1~h4를 깊이 순서대로 이어붙인다.
    # dict 순서에 기대지 않고 HEADERS의 순서를 따른다 — 순서가 곧 의미이기 때문이다.
    return " > ".join(metadata[key] for _, key in HEADERS if metadata.get(key))


def _merge_small(
    pieces: list[tuple[str, int]],
    measure: Callable[[str], int],
    max_tokens: int,
    min_tokens: int,
) -> list[tuple[str, int]]:
    """같은 섹션 안에서 너무 작은 조각을 이웃과 합친다.

    ★ 섹션을 넘어가며 합치지 않는다 ★ heading_path가 달라지기 때문이다. 다행히 실측한
    문제 조각들(닫는 코드펜스, 헤딩만 남은 조각)은 전부 **같은 섹션 안**에서 생긴다 —
    RecursiveCharacterTextSplitter가 코드펜스 경계에서 자르면서 섹션의 첫 줄만 떼어놓는
    식이라, 섹션 내 병합만으로 충분하다.

    합쳐서 max_tokens를 넘으면 합치지 않는다. 작은 조각을 없애려다 e5 한도에 가까운
    거대 청크를 만들면 본말전도다 — 그래서 일부는 작은 채로 남을 수 있고, 그게 맞다.
    """
    merged: list[tuple[str, int]] = []
    for text, count in pieces:
        if merged:
            prev_text, prev_count = merged[-1]
            # 앞이 작든 지금이 작든, 둘 중 하나가 작으면 붙일 후보다.
            if prev_count < min_tokens or count < min_tokens:
                candidate = prev_text + "\n\n" + text
                candidate_count = measure(candidate)
                if candidate_count <= max_tokens:
                    merged[-1] = (candidate, candidate_count)
                    continue
        merged.append((text, count))
    return merged


def split_markdown(
    text: str,
    *,
    max_tokens: int = MAX_TOKENS,
    overlap_tokens: int = OVERLAP_TOKENS,
    min_tokens: int = MIN_TOKENS,
    strip_headers: bool = False,
    length_function: Callable[[str], int] | None = None,
) -> list[Chunk]:
    """마크다운을 구조 인식 + 토큰 기반으로 자른다.

    2단 분할이다:
      1) MarkdownHeaderTextSplitter — 헤더 경계로 먼저 쪼갠다. 한 섹션은 한 주제다.
      2) RecursiveCharacterTextSplitter — 섹션이 너무 크면 그 안에서 다시 쪼갠다.
         구분자 우선순위가 마크다운을 안다(실측). 앞에서부터 시도한다:
           1. 헤더(\\n#{1,6} )  2. 코드펜스(```\\n)  3. 구분선(---, ***, ___)
           4. 빈 줄(\\n\\n)  5. 줄(\\n)  6. 공백  7. 문자
         **코드펜스가 빈 줄보다 앞에 있는 것이 핵심이다** — 코드블록을 통째로 유지하려
         시도하고, 그래도 안 되면 빈 줄 -> 줄 -> 공백 -> 문자 순으로 물러난다.
         3-1의 "600자마다 무조건 자르기"는 이 우선순위가 아예 없었다.

    ★ strip_headers 기본값이 False인 이유 ★
    True(라이브러리 기본값)면 헤딩 텍스트가 본문에서 **사라지고** metadata로만 간다.
    그러면 "## 아키텍처" 아래 청크는 '아키텍처'라는 단어를 잃은 채 임베딩되어,
    베이스라인(원문 그대로 자른 것)보다 오히려 나빠질 수 있다. 실제로 두 값을 모두
    돌려 비교했다 — evals/results/ 참고. M7-2에서 heading_path를 명시적으로 앞에
    붙이면 h1>h2>h3 전체 경로가 들어가므로 그때는 True로 둬도 손해가 없다.
    """
    if overlap_tokens >= max_tokens:
        # 3-1의 chunk_text와 같은 가드. 없으면 분할기가 무한 루프에 빠지거나
        # 조용히 이상한 경계를 만든다.
        raise ValueError(f"overlap({overlap_tokens})은 max_tokens({max_tokens})보다 작아야 한다")

    budget = E5_INPUT_LIMIT - RESERVED_TOKENS
    if max_tokens > budget:
        raise ValueError(f"max_tokens({max_tokens})가 e5 한도({budget})를 넘는다 - 조용히 잘린다")

    # ★ 길이 함수를 인자로 뺀 이유 ★ 기본값(token_length)은 2.24GB 임베딩 모델을
    # 로딩한다. 그대로 두면 이 함수는 pytest에서 절대 테스트할 수 없다 —
    # CI에서 모델을 받게 되기 때문이다(chatbot/README.md의 CI 경고).
    # 인자로 빼두면 테스트가 len(문자 수)을 넣어 **분할 구조만** 검증할 수 있다.
    # build_graph가 model·retrieve_fn을 인자로 받는 것과 정확히 같은 패턴이다.
    measure = length_function or token_length

    header_splitter = MarkdownHeaderTextSplitter(HEADERS, strip_headers=strip_headers)
    body_splitter = RecursiveCharacterTextSplitter.from_language(
        Language.MARKDOWN,
        chunk_size=max_tokens,
        chunk_overlap=overlap_tokens,
        length_function=measure,
    )

    chunks: list[Chunk] = []
    for section in header_splitter.split_text(text):
        path = heading_path_of(section.metadata)
        pieces = [p.strip() for p in body_splitter.split_text(section.page_content)]
        for piece, count in _merge_small(
            [(p, measure(p)) for p in pieces if p], measure, max_tokens, min_tokens
        ):
            if count > budget:
                # 여기 걸리면 분할기가 더 못 쪼갠 것이다(공백 없는 초장문 등).
                # 조용히 잘린 채 임베딩되면 검색 품질만 무너지므로 로그로 드러낸다.
                logger.warning("청크가 e5 한도를 넘는다 (%d > %d): %.40s", count, budget, piece)
            chunks.append(
                Chunk(
                    content=piece,
                    heading_path=path,
                    chunk_index=len(chunks),
                    token_count=count,
                )
            )
    return chunks
