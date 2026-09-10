# 지연 계측 층 테스트. (M13-b)
#
# 이 파일은 네트워크도 LLM도 안 부른다 — 순수 함수와 ContextVar 동작만 본다.
# 그래서 CI에 그대로 넣을 수 있고, 넣어야 한다: 계측이 조용히 0을 찍기 시작하면
# 그 위에서 내리는 모든 최적화 판단이 틀린다.
import asyncio
import time

from app.core.timing import Timings, current, mark, request_timings, stage


def test_stage_outside_a_request_is_a_noop():
    """★ 계측 문맥 밖에서도 그냥 돌아야 한다 ★

    같은 retrieve()를 CLI(`python -m app.rag.retriever`)와 평가 스크립트도 부른다.
    거기서 예외가 나거나 전역에 값이 쌓이면, 계측을 넣은 대가로 다른 경로를 망가뜨린 것이다.
    """
    assert current() is None
    with stage("embed"):
        pass
    mark("ttft")
    assert current() is None


def test_stages_accumulate_and_count_calls():
    with request_timings() as timings:
        with stage("generate"):
            time.sleep(0.001)
        with stage("generate"):
            time.sleep(0.001)

    stage_data = timings.stages["generate"]
    # ★ 횟수를 따로 세는 이유 ★ 도구를 부르는 턴은 생성이 두 번이다(FLOW.md 경로 B).
    # 합계만 보면 "생성이 느리다"로 읽히지만 실제로는 "두 번 불렀다"이고 처방이 다르다.
    assert stage_data.calls == 2
    assert stage_data.ms > 0


def test_mark_records_only_the_first_call():
    """TTFT는 '첫' 토큰까지의 시간이다. 델타마다 갱신되면 이름과 다른 값이 된다."""
    with request_timings() as timings:
        mark("ttft")
        first = timings.marks["ttft"]
        time.sleep(0.005)
        mark("ttft")

    assert timings.marks["ttft"] == first


def test_stage_records_even_when_the_body_raises():
    # 느려서 터진 경우가 바로 그 숫자를 가장 알고 싶은 순간이다.
    with request_timings() as timings:
        try:
            with stage("search"):
                raise RuntimeError("Qdrant 죽음")
        except RuntimeError:
            pass

    assert "search" in timings.stages


def test_measurements_survive_asyncio_to_thread():
    """★ 이 파일에서 가장 중요한 테스트 ★

    실제 검색 경로는 `asyncio.to_thread(retrieve, ...)`로 **다른 스레드**에서 돈다.
    to_thread는 contextvars를 **복사**해서 넘기므로, 단계마다 ContextVar.set()을 하는
    설계였다면 스레드 안의 기록이 부모에게 안 보인다 — **에러 없이 검색 층 측정치가
    통째로 사라진다.**

    그래서 timing.py는 "요청 시작 시 딕셔너리 하나를 set하고 이후로는 mutate"한다.
    복사되는 것은 참조뿐이라 스레드 안의 기록이 그대로 보인다. 이 테스트가 그 설계를
    못 박는다 — 나중에 누가 stage()를 set() 기반으로 바꾸면 여기서 깨진다.
    """

    def blocking_work():
        with stage("embed"):
            time.sleep(0.001)

    async def scenario():
        with request_timings() as timings:
            await asyncio.to_thread(blocking_work)
        return timings

    timings = asyncio.run(scenario())

    assert "embed" in timings.stages
    assert timings.stages["embed"].calls == 1


def test_summary_is_flat_rounded_ints():
    # 와이어에 실리는 모양. 소수점을 남기면 응답 바이트가 매번 달라져 비교가 안 되고,
    # 0.1ms를 구분해서 할 일도 없다.
    timings = Timings()
    timings.add("embed", 12.4)
    timings.add("search", 3.6)
    timings.mark("ttft")

    summary = timings.summary()

    assert summary["embed"] == 12
    assert summary["search"] == 4
    assert "ttft" in summary
    assert all(isinstance(v, int) for v in summary.values())


def test_log_line_marks_repeated_stages():
    timings = Timings()
    timings.add("generate", 100.0)
    timings.add("generate", 50.0)
    timings.add("search", 10.0)

    line = timings.log_line()

    # "×2"가 있어야 "느린 한 번"과 "두 번 부름"이 로그에서 구분된다.
    assert "generate=150ms×2" in line
    assert "search=10ms" in line
    assert "total=" in line


def test_nested_context_does_not_leak():
    # 요청이 끝나면 다음 요청이 빈 상태에서 시작해야 한다. 안 그러면 한 프로세스가
    # 오래 살수록 숫자가 계속 커지는데, 그건 "느려졌다"와 구분되지 않는다.
    with request_timings():
        with stage("embed"):
            pass
    assert current() is None

    with request_timings() as second:
        pass
    assert second.stages == {}
