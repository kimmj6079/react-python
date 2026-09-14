# 대화 체크포인터 배선 테스트. (M5-2)
#
# ★ 진짜 Postgres를 두드리지 않는다 ★ 여기서 재는 것은 "어떤 주소로 붙는가",
# "지금 이벤트 루프에서 붙을 수 있는가", "memory 모드가 정말 DB를 안 건드리는가" 셋이다.
# 실제 저장이 되는지는 docker compose를 띄워 손으로 확인한다(README의 검증 절차).
#
# ★ 이 파일이 있는 이유 ★ 체크포인터는 **틀려도 앱이 멀쩡히 뜨는** 부품이다.
# 주소를 잘못 만들면 첫 채팅에서야 터지고, memory로 조용히 내려가면 "왜 재시작하면
# 대화가 사라지지"를 며칠 뒤에 깨닫는다. 그래서 조용히 틀릴 수 있는 지점만 골라 못 박는다.
import asyncio

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.core.checkpointer import (
    checkpointer_scope,
    ensure_loop_supports_psycopg,
    to_psycopg_dsn,
)

# --- DSN 변환 ---------------------------------------------------------------


def test_strips_the_sqlalchemy_driver_prefix():
    # ★ 이 한 줄이 없으면 조용히 안 붙는다 ★ settings.database_url은 SQLAlchemy용이라
    # `postgresql+psycopg://`인데, psycopg_pool은 그 `+psycopg`를 모른다.
    # 설정을 두 벌로 나누는 대신(= 두 값이 어긋날 자유를 만드는 대신) 변환한다.
    assert to_psycopg_dsn("postgresql+psycopg://u:p@db:5432/app") == "postgresql://u:p@db:5432/app"


def test_leaves_a_plain_postgres_url_alone():
    assert to_psycopg_dsn("postgresql://u:p@db:5432/app") == "postgresql://u:p@db:5432/app"


def test_strips_any_driver_not_just_psycopg():
    assert to_psycopg_dsn("postgresql+asyncpg://u@h/d") == "postgresql://u@h/d"


def test_rejects_a_non_postgres_url_loudly():
    # ★ pytest는 SQLite로 돈다 ★ 누가 CHECKPOINTER=postgres인 채로 SQLite URL을 주면
    # "대화가 저장되는 줄 알았는데 아니었다"가 된다. 조용히 넘어가는 대신 죽는다.
    with pytest.raises(ValueError, match="postgres"):
        to_psycopg_dsn("sqlite:///./app.db")


# --- 이벤트 루프 호환성 (Windows 함정) -----------------------------------------


class ProactorEventLoop:  # 이름만 흉내 낸 대역 — 실제 루프를 만들 필요가 없다
    pass


class SelectorEventLoop:
    pass


def test_rejects_the_windows_proactor_loop():
    # ★ 실측으로 확인한 함정이다 ★ psycopg의 비동기 연결은 ProactorEventLoop에서
    # 동작하지 않는다(InterfaceError). Windows의 기본 루프가 그것이고,
    # uvicorn은 --reload일 때만 Selector 루프를 쓴다 —
    # 즉 **--reload를 빼는 순간 챗봇만 죽는다.**
    # 첫 채팅 요청에서 psycopg의 에러로 만나면 원인을 찾기 어려우니,
    # 기동 시점에 우리가 먼저 이름을 대고 죽는다.
    with pytest.raises(RuntimeError, match="Proactor"):
        ensure_loop_supports_psycopg(ProactorEventLoop())


def test_accepts_a_selector_loop():
    assert ensure_loop_supports_psycopg(SelectorEventLoop()) is None


# --- memory 모드 -------------------------------------------------------------


def test_memory_mode_yields_an_in_memory_saver_without_touching_postgres(monkeypatch):
    # DSN이 아예 말이 안 되는 값이어도 memory 모드는 성공해야 한다.
    # 성공한다는 것 자체가 "DB를 안 건드렸다"는 증거다.
    from app.core.config import settings

    monkeypatch.setattr(settings, "checkpointer", "memory", raising=False)
    monkeypatch.setattr(settings, "database_url", "sqlite:///nope.db", raising=False)

    async def run():
        async with checkpointer_scope() as saver:
            return saver

    assert isinstance(asyncio.run(run()), InMemorySaver)


def test_rejects_an_unknown_checkpointer_name(monkeypatch):
    # vector_store와 같은 규칙이다 — 오타는 조용한 기본값이 아니라 이름을 담은 죽음으로.
    from app.core.config import settings

    monkeypatch.setattr(settings, "checkpointer", "redis", raising=False)

    async def run():
        async with checkpointer_scope():
            pass

    with pytest.raises(ValueError, match="redis"):
        asyncio.run(run())


# --- 그래프 수명 (lifespan) ---------------------------------------------------


def test_get_graph_fails_loudly_before_lifespan_runs():
    """★ lifespan이 안 돌았는데 조용히 None을 주면 안 된다 ★

    M5-2에서 그래프 생성이 "모듈 import 시점"에서 "lifespan 시점"으로 옮겨졌다.
    커넥션 풀은 이벤트 루프가 있어야 열 수 있고, 닫을 자리도 있어야 하기 때문이다.
    대가는 **lifespan을 안 거치고 앱을 쓰면 그래프가 없다**는 것인데, 그때 None을
    돌려주면 라우터 안쪽 깊은 곳에서 AttributeError로 만난다.
    여기서 이름을 대고 죽는 편이 낫다.
    """
    from fastapi import FastAPI

    from app.api.deps import get_graph

    bare = FastAPI()

    class Req:
        app = bare

    with pytest.raises(RuntimeError, match="lifespan"):
        get_graph(Req())


# --- ai_sdk가 비동기 콜백을 받아야 한다 ------------------------------------------


def test_ui_message_stream_awaits_an_async_sources_fn():
    """★ AsyncPostgresSaver가 강제한 변경이다 ★ (M5-2)

    실측: AsyncPostgresSaver를 쓰면 `graph.get_state()`(동기)를 이벤트 루프에서 부를 수
    없다 — `asyncio.InvalidStateError`를 던진다. chat.py의 sources()가 바로 그걸
    부르고 있었으므로 `await graph.aget_state()`로 바꿔야 하고, 그러면 sources()가
    **코루틴 함수**가 된다.

    ai_sdk는 값이 아니라 함수를 받도록 M10에서 이미 만들어뒀다(그때 이유는 "시점"이었다).
    여기서 필요한 것은 한 겹 더 — **그 함수가 코루틴이어도 된다**는 것이다.
    동기 함수도 계속 받아야 한다: metadata_fn은 여전히 동기이고,
    기존 테스트들도 동기 콜백을 넘긴다.
    """
    from app.core.ai_sdk import ui_message_stream

    async def deltas():
        yield "안녕"

    async def async_sources():
        return [{"type": "source-url", "sourceId": "a.md#1", "url": "a.md"}]

    async def collect():
        return [frame async for frame in ui_message_stream(deltas(), async_sources)]

    wire = "".join(asyncio.run(collect()))

    assert "a.md#1" in wire
    # 출처는 text-end 뒤, finish-step 앞이라는 순서가 유지돼야 한다.
    assert wire.index("text-end") < wire.index("a.md#1") < wire.index("finish-step")


def test_ui_message_stream_still_accepts_a_sync_sources_fn():
    from app.core.ai_sdk import ui_message_stream

    async def deltas():
        yield "안녕"

    async def collect():
        return [
            frame
            async for frame in ui_message_stream(
                deltas(), lambda: [{"type": "source-url", "sourceId": "b.md#0", "url": "b.md"}]
            )
        ]

    assert "b.md#0" in "".join(asyncio.run(collect()))
