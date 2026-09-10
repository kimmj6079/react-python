# M13-c 실측: 우리 프롬프트에 Anthropic 프롬프트 캐싱을 걸 수 있는가.
#
# 실행:
#   docker compose up -d db qdrant
#   cd backend
#   uv run python scripts/probe_prompt_cache.py
#
# ★ 구현하기 전에 "가능한가"부터 잰다 ★
# 프롬프트 캐싱에는 **최소 캐시 프리픽스**가 있다. 그보다 짧은 프리픽스는 에러가 아니라
# **조용히 캐시되지 않는다**(`cache_creation_input_tokens: 0`). 즉 `cache_control`을 붙여놓고
# "왜 안 걸리지"를 며칠 헤맬 수 있는 종류의 기능이다. 그래서 먼저 잰다.
#
# 최소 프리픽스는 모델마다 다르고 **세대에 따라 단조롭지도 않다**:
#   Opus 5 / Fable 5 계열      512 토큰
#   Opus 4.8 / Sonnet 5 / 4.6  1024 토큰
#   Opus 4.7                   2048 토큰
#   Opus 4.6 / 4.5 / Haiku 4.5 4096 토큰   <- 우리가 쓰는 모델
#
# ★ 토크나이저가 둘이라는 점에 주의 ★ chunking.py는 e5 토크나이저로 청크 길이를 잰다.
# 그건 "임베딩 모델이 몇 토큰까지 받는가"의 문제라 맞는 선택이다. 반면 여기서 궁금한 것은
# "Claude 프롬프트 예산을 얼마나 먹는가"라 **Claude 토크나이저**여야 한다.
# chunking.py:64의 표에 "이 문맥이 프롬프트 예산을 얼마나 먹는가 → count_tokens → M13"이라고
# 적어둔 그 항목이 지금이다.
#
# count_tokens는 **과금되지 않는 엔드포인트**라 크레딧이 없어도 대개 동작한다.
# 실패하면 e5 토크나이저로 근사치를 내고 그렇다고 표시한다 — 우리가 확인하려는 것은
# "4096을 넘느냐"라 근사로도 결론이 난다.
import sys

from app.core.config import settings
from app.graph import NO_CONTEXT_PROMPT, SYSTEM_PROMPT_TEMPLATE, _format_context
from app.rag.access import Principal
from app.rag.base import TOP_K
from app.rag.factory import get_store
from app.rag.retriever import retrieve

sys.stdout.reconfigure(encoding="utf-8")

# 모델별 최소 캐시 프리픽스(토큰). 출처: Anthropic 프롬프트 캐싱 문서.
MIN_CACHEABLE_PREFIX = {
    "claude-opus-5": 512,
    "claude-fable-5-1": 512,
    "claude-opus-4-8": 1024,
    "claude-sonnet-5": 1024,
    "claude-sonnet-4-6": 1024,
    "claude-opus-4-7": 2048,
    "claude-opus-4-6": 4096,
    "claude-haiku-4-5": 4096,
}

QUESTION = "마이그레이션은 컨테이너가 뜰 때 자동으로 실행되나?"


def count_with_claude(system: str, question: str) -> int | None:
    """Claude 토크나이저로 센다. 키가 없거나 네트워크가 막히면 None."""
    try:
        from anthropic import Anthropic

        client = Anthropic(api_key=settings.anthropic_api_key)
        result = client.messages.count_tokens(
            model=settings.anthropic_model,
            system=system,
            messages=[{"role": "user", "content": question}],
        )
        return result.input_tokens
    except Exception as exc:  # noqa: BLE001 - probe라 원인만 보여주고 넘어간다
        print(f"  (count_tokens 실패 → e5 토크나이저로 근사: {type(exc).__name__})")
        print(f"   {str(exc)[:160]}")
        return None


def count_with_e5(text: str) -> int:
    """e5 토크나이저로 근사한다.

    ★ 함정: e5 토크나이저는 512토큰에서 잘린다 ★ 그대로 `token_length(전체)`를 부르면
    무엇을 넣든 512가 나온다 — 처음에 그렇게 짰다가 "프롬프트가 정확히 512토큰"이라는
    수상한 숫자를 보고서야 알았다. **상한에 딱 맞는 숫자가 나오면 측정이 아니라 절단을
    보고 있는 것이다.** (chunking.py는 청크가 220토큰 이하라 이 상한에 안 닿는다.)

    토크나이저의 truncation 설정을 끄는 방법도 있지만, 그 객체는 chunking.py와
    공유하는 전역이라 probe가 전역 상태를 바꾸게 된다. 대신 조각내어 더한다 —
    경계에서 몇 토큰 과다 계산되지만, 우리가 볼 것은 "4096을 넘느냐"라 충분하다.
    """
    from app.rag.chunking import token_length

    lines = text.splitlines(keepends=True)
    total, buffer = 0, ""
    for line in lines:
        if len(buffer) + len(line) > 600:
            total += token_length(buffer)
            buffer = ""
        buffer += line
    if buffer:
        total += token_length(buffer)
    return total


def main() -> None:
    model = settings.anthropic_model
    minimum = MIN_CACHEABLE_PREFIX.get(model)

    print(f"[모델 {model} · 최소 캐시 프리픽스 {minimum or '?'}토큰]\n")

    store = get_store()
    chunks = retrieve(store, QUESTION, Principal(), TOP_K)
    context = _format_context(chunks)
    full_system = SYSTEM_PROMPT_TEMPLATE.format(context=context) if context else NO_CONTEXT_PROMPT

    # ★ 두 조각을 따로 센다 ★ 캐싱은 프리픽스 매칭이라 "전체가 몇 토큰인가"보다
    # **"매 요청 똑같은 앞부분이 몇 토큰인가"** 가 중요하다.
    #   - 고정부: 지시문 템플릿 (매 턴 같다)
    #   - 가변부: 검색된 문맥 (매 턴 다르다)
    instructions_only = SYSTEM_PROMPT_TEMPLATE.format(context="")

    total = count_with_claude(full_system, QUESTION)
    tokenizer = "Claude"
    if total is None:
        tokenizer = "e5(근사)"
        total = count_with_e5(full_system + QUESTION)
    fixed = count_with_e5(instructions_only)
    ctx = count_with_e5(context)

    print(f"검색된 청크: {len(chunks)}개")
    print(f"토크나이저: {tokenizer}\n")
    print(f"  고정부(지시문 템플릿)  {fixed:>6}토큰   <- 매 턴 동일 = 캐시 후보")
    print(f"  가변부(검색된 문맥)    {ctx:>6}토큰   <- 매 턴 다름")
    print("  ─────────────────────────────")
    print(f"  프롬프트 전체          {total:>6}토큰")
    if minimum:
        print(f"  최소 캐시 프리픽스     {minimum:>6}토큰\n")

        if total < minimum:
            print(f"❌ 프롬프트 **전체**가 최소치보다 작다 ({total} < {minimum}).")
            print("   cache_control을 어디에 붙여도 캐시가 만들어지지 않는다 — 에러도 없이.")
        elif fixed < minimum:
            print(f"⚠ 전체는 최소치를 넘지만 **고정부**가 부족하다 ({fixed} < {minimum}).")
            print("   가변부(문맥)가 프리픽스 앞에 있으면 그 뒤는 전부 무효다.")
        else:
            print("✅ 고정부만으로 최소치를 넘는다 → cache_control을 고정부 끝에 붙일 수 있다.")

    print("\n[레이아웃 점검]")
    print("  현재: tools → system(지시문 + **문맥**) → messages(질문)")
    print("  ★ 가변부(문맥)가 프리픽스의 거의 맨 앞에 있다 ★")
    print("  = 매 턴 프리픽스가 바뀌므로, 최소치를 넘겼더라도 그 뒤 전부가 캐시 불가다.")
    print("  캐싱을 하려면 문맥을 system이 아니라 **마지막 user 턴**으로 옮겨야 한다.")
    print("  (그 이동은 M12가 인젝션 방어를 위해 이미 권고했던 것과 같은 변경이다.)")


if __name__ == "__main__":
    main()
