# 요청 하나의 단계별 소요 시간을 모으는 계측 층. (M13-b)
#
# ★ 왜 필요한가 ★
# M8·M9를 거치며 사용자가 엔터를 치고 첫 글자가 나오기까지 이 전부가 순차로 일어난다:
#   재작성(LLM) -> 임베딩 -> 게이트 -> 하이브리드 검색 -> 리랭킹(LLM×N) -> 생성 시작
# M1에서 스트리밍으로 얻었던 체감 속도를 그 사이에 상당 부분 잃었다. **어디서 잃었는지
# 모르면 어디를 고칠지도 모른다** — M6가 "품질의 계측기"였다면 이 파일은 "지연의 계측기"다.
#
# ★ Langfuse가 이미 span 지속시간을 갖고 있는데 왜 또 만드나 ★
#   1) Langfuse는 **켜져 있어야** 보인다. 키가 없는 환경(CI·새 클론·오프라인)에서는 0이다.
#   2) 대시보드를 열어야 보인다. 로그 한 줄이면 터미널에서 바로 보인다.
#   3) 우리가 정한 이름으로 쪼갤 수 있다. LangChain의 span 경계는 LangChain이 정하지,
#      "임베딩 / 게이트 / 융합 / 리랭킹"처럼 **우리가 아끼고 싶은 단위**로 나뉘어 있지 않다.
# 둘은 경쟁하지 않는다. 13-e에서 두 숫자를 대조하는 것 자체가 검증이 된다.
#
# ★ 설계: ContextVar에 "가변 딕셔너리"를 담는다 ★
# 함수마다 timings 인자를 늘어놓는 대신(그러면 retriever·store·rerank 시그니처가 전부
# 오염된다) 요청 문맥에 매달아 둔다. 그런데 **여기에 함정이 하나 있다**:
#
#   asyncio.to_thread()는 contextvars를 **복사**해서 새 스레드로 넘긴다.
#   그 스레드 안에서 ContextVar.set()을 하면 복사본만 바뀌고 부모에는 안 보인다.
#
# 우리 검색 경로는 `asyncio.to_thread(retrieve, ...)`로 스레드에서 돈다(deps.py). 그래서
# 단계마다 set()을 하는 설계였다면 **검색 층의 측정치가 통째로 사라진다 — 에러 없이.**
# 대신 **요청 시작 시점에 딕셔너리 하나를 set해두고, 이후로는 그 객체를 mutate**한다.
# 복사되는 것은 "딕셔너리를 가리키는 참조"뿐이라 스레드 안의 기록이 부모에게 그대로 보인다.
import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class Stage:
    """한 단계의 누적 시간과 호출 횟수."""

    ms: float = 0.0
    # ★ 횟수를 따로 세는 이유 ★ 도구를 부르는 턴에서는 생성이 **두 번** 일어난다
    # (FLOW.md 경로 B: 모델 -> 도구 -> 모델). 합계만 보면 "생성이 원래 느리다"로
    # 읽히지만 실제로는 "두 번 불렀다"이고, 처방이 완전히 다르다.
    calls: int = 0


@dataclass
class Timings:
    """요청 하나의 계측 결과. 라우터가 만들고 각 층이 채운다."""

    started: float = field(default_factory=time.perf_counter)
    stages: dict[str, Stage] = field(default_factory=dict)
    # 시점 기록(누적이 아니라 "요청 시작 후 몇 ms에 일어났는가"). TTFT가 대표적이다.
    marks: dict[str, float] = field(default_factory=dict)

    def add(self, name: str, ms: float) -> None:
        stage = self.stages.setdefault(name, Stage())
        stage.ms += ms
        stage.calls += 1

    def mark(self, name: str) -> None:
        # ★ 덮어쓰지 않는다 ★ TTFT는 "첫" 토큰까지의 시간이다. 델타마다 갱신하면
        # 마지막 토큰 시각이 되어 이름과 다른 값이 된다 — 호출하는 쪽이 "첫 번째냐"를
        # 판단하게 두면 그 판단이 빠지는 날 조용히 틀린 숫자가 된다.
        self.marks.setdefault(name, (time.perf_counter() - self.started) * 1000)

    @property
    def total_ms(self) -> float:
        return (time.perf_counter() - self.started) * 1000

    def summary(self) -> dict[str, int]:
        """와이어/로그에 실을 납작한 dict. 값은 반올림한 정수 밀리초.

        소수점을 버리는 이유: 0.1ms를 구분해서 할 일이 없고, 남겨두면 매 응답의
        바이트가 달라져 테스트에서 == 비교를 할 수 없다.
        """
        out = {name: round(stage.ms) for name, stage in self.stages.items()}
        out.update({name: round(ms) for name, ms in self.marks.items()})
        out["total"] = round(self.total_ms)
        return out

    def log_line(self) -> str:
        """터미널에 한 줄로 찍을 문자열. `단계=123ms` 나열 + 2회 이상이면 ×N."""
        parts = []
        for name, stage in self.stages.items():
            suffix = f"×{stage.calls}" if stage.calls > 1 else ""
            parts.append(f"{name}={stage.ms:.0f}ms{suffix}")
        for name, ms in self.marks.items():
            parts.append(f"{name}={ms:.0f}ms")
        parts.append(f"total={self.total_ms:.0f}ms")
        return " ".join(parts)


# 기본값 None = "계측 문맥 밖". CLI 스크립트·pytest·인입 잡이 같은 함수를 부를 때
# 계측을 강요하지 않기 위해서다. 아래 record/stage가 None이면 그냥 아무것도 안 한다.
_current: ContextVar[Timings | None] = ContextVar("request_timings", default=None)


@contextmanager
def request_timings() -> Iterator[Timings]:
    """이 블록 안에서 일어나는 모든 stage()를 하나로 모은다.

    ★ 라우터 함수 본문에서 열면 안 된다 ★ FastAPI가 StreamingResponse를 돌려주는
    순간 라우터 함수는 **이미 끝나 있고**, 실제 스트리밍은 그 뒤에 (보통 다른 태스크에서)
    일어난다. 그래서 이 컨텍스트는 **스트림 제너레이터 안**에서 열어야 한다.
    M10에서 sources_fn을 값이 아니라 함수로 넘겨야 했던 것과 뿌리가 같은 함정이다:
    **"라우터가 끝나는 시점"과 "응답이 만들어지는 시점"이 다르다.**
    """
    timings = Timings()
    token = _current.set(timings)
    try:
        yield timings
    finally:
        _current.reset(token)


def current() -> Timings | None:
    return _current.get()


@contextmanager
def stage(name: str) -> Iterator[None]:
    """한 단계를 감싸 소요 시간을 기록한다. 계측 문맥 밖이면 아무 일도 안 한다.

    동기 컨텍스트 매니저지만 `with stage("x"): await ...` 도 그대로 된다 —
    블록 안에서 await 하는 동안 이 프레임은 살아 있고, 끝날 때 __exit__이 돈다.
    (async 컨텍스트 매니저가 필요한 경우는 **진입/종료 자체가 await**일 때뿐이다.)

    ★ time.time()이 아니라 perf_counter() ★ time.time()은 시스템 시계라 NTP 보정이나
    서머타임에 뒤로 갈 수 있고, 그러면 음수 지연이 찍힌다. 경과 시간에는 항상 단조
    시계를 쓴다.
    """
    timings = _current.get()
    if timings is None:
        yield
        return

    start = time.perf_counter()
    try:
        yield
    finally:
        # finally에 두는 이유: 예외가 나도 "여기까지 얼마나 걸렸는지"는 남아야 한다.
        # 느려서 타임아웃이 난 경우가 정확히 그 숫자를 가장 알고 싶은 순간이다.
        timings.add(name, (time.perf_counter() - start) * 1000)


def mark(name: str) -> None:
    """요청 시작 후 몇 ms에 이 지점을 지났는지 기록한다(첫 번째 호출만)."""
    timings = _current.get()
    if timings is not None:
        timings.mark(name)
