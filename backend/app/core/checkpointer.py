# 대화 상태 저장소(체크포인터) 배선. (M5-2)
#
# ★ 무엇이 바뀌었나 ★ 2b부터 M5-1까지 체크포인터는 `InMemorySaver()` 한 줄이었다.
# 이름 그대로 파이썬 프로세스 메모리라, deps.py 주석에 한계 셋을 적어뒀었다:
#   1) --reload가 재시작하면 전 대화가 사라진다 (개발 중 "왜 기억을 못 하지?"의 90%)
#   2) 워커/파드가 둘 이상이면 요청이 흩어져 대화가 뒤죽박죽 된다 → 스케일아웃 불가
#   3) 지우는 코드가 없어 스레드가 쌓이기만 한다 (오래 살면 누수)
# k8s에서 backend replicas가 2라 (2)는 **이미 일어나고 있던 일**이다 — 같은 사용자의
# 두 번째 질문이 다른 파드로 가면 앱이 첫 턴처럼 행동한다. 에러가 아니라
# "가끔 기억을 못 하는 챗봇"으로만 보여서, 배포해두고도 한참 모를 수 있는 종류다.
#
# ★ 실측으로 정해진 것 세 가지 (문서가 아니라 설치된 패키지에게 물었다) ★
#   ① 동기 PostgresSaver는 astream과 함께 못 쓴다 — NotImplementedError.
#      BaseCheckpointSaver.aget_tuple의 기본 구현이 그냥 raise다. 즉 비동기 앱은
#      AsyncPostgresSaver를 써야 하고, 선택의 여지가 없다.
#   ② AsyncPostgresSaver를 쓰면 `graph.get_state()`(동기)를 이벤트 루프에서 못 부른다.
#      InvalidStateError를 던진다. chat.py의 sources()가 그걸 부르고 있었다 →
#      `await graph.aget_state()`로 바꿔야 한다(그 파일 참고).
#   ③ **Windows의 기본 이벤트 루프에서는 psycopg 비동기가 아예 안 된다.**
#      아래 ensure_loop_supports_psycopg 참고. 이게 가장 찾기 어려운 함정이었다.
#
# ★ 테이블은 여기서 만들지 않는다 ★ AsyncPostgresSaver.setup()이 DDL을 돌리는데,
# 그걸 앱 기동 시점에 부르는 예제가 대부분이다. 이 저장소는 안 그런다 —
# "마이그레이션은 절대 컨테이너 시작 시 자동 실행되지 않는다"(CLAUDE.md)와 같은 규칙이다.
# 스키마 변경은 감사 가능한 별도 단계여야 하고, 파드가 뜰 때마다 DDL을 시도하면
# 롤링 업데이트 중 여러 파드가 동시에 같은 DDL을 돌린다.
# → `python -m app.db.checkpointer_setup`이 그 단계다.
from __future__ import annotations

import logging
import re
from contextlib import asynccontextmanager

from langgraph.checkpoint.memory import InMemorySaver

from app.core.config import settings

logger = logging.getLogger(__name__)

# SQLAlchemy는 `postgresql+psycopg://`처럼 드라이버를 URL에 박지만 psycopg는 그 문법을
# 모른다. `postgresql+무엇이든://` 를 `postgresql://`로 되돌린다.
_DRIVER_PREFIX = re.compile(r"^postgres(?:ql)?\+[a-z0-9_]+://", re.IGNORECASE)


def to_psycopg_dsn(url: str) -> str:
    """SQLAlchemy URL을 psycopg가 이해하는 DSN으로.

    ★ 설정을 두 벌로 나누지 않으려고 변환한다 ★ `CHECKPOINTER_DSN`을 따로 두면
    DATABASE_URL과 어긋날 자유가 생기고, 어긋나면 "앱은 A DB를 보는데 대화는 B DB에
    쌓이는" 상태가 된다 — 에러가 없어서 한참 모른다. 출처를 하나로 두고 모양만 바꾼다.
    (alembic/env.py가 alembic.ini의 url을 무시하고 settings를 쓰는 것과 같은 규칙이다.)
    """
    if _DRIVER_PREFIX.match(url):
        return _DRIVER_PREFIX.sub("postgresql://", url, count=1)
    if url.startswith(("postgresql://", "postgres://")):
        return url
    # ★ 조용히 넘기지 않는다 ★ pytest는 SQLite로 돈다. 누가 CHECKPOINTER=postgres인 채로
    # SQLite URL을 주면 "대화가 저장되는 줄 알았는데 아니었다"가 된다.
    raise ValueError(
        f"체크포인터는 postgres URL이 필요하다 (받은 값: {url!r}). "
        "CHECKPOINTER=memory로 두거나 DATABASE_URL을 postgres로 맞춘다."
    )


def ensure_loop_supports_psycopg(loop) -> None:
    """지금 이벤트 루프에서 psycopg 비동기가 동작하는지 확인한다.

    ★★ 실측 ★★ Windows의 기본 루프(ProactorEventLoop)에서는 이렇게 죽는다:

        InterfaceError: Psycopg cannot use the 'ProactorEventLoop' to run in async mode.

    그리고 **uvicorn은 `--reload`일 때만 Selector 루프를 쓴다**
    (uvicorn/loops/asyncio.py: `win32 and not use_subprocess` → Proactor).
    즉 이 저장소의 개발 명령(`uvicorn app.main:app --reload`)으로는 멀쩡하고,
    `--reload`를 빼는 순간 **챗봇만 죽는다.** 그보다 더 헷갈리는 조합은 없다.

    ★ 왜 기동 시점에 죽이나 ★ 안 그러면 첫 채팅 요청에서 psycopg의 에러로 만난다.
    그 시점에는 스택이 LangGraph 안쪽 깊은 곳이라 원인이 "이벤트 루프"라는 것을
    알아보기 어렵다. **틀린 설정으로 뜬 서버는 뜨지 않은 서버보다 나쁘다.**
    (Linux·Docker·k8s에서는 기본이 Selector 계열이라 이 함수가 아무것도 안 한다.)
    """
    name = type(loop).__name__
    if "Proactor" in name:
        raise RuntimeError(
            f"psycopg 비동기는 {name}에서 동작하지 않는다(Windows 기본 루프).\n"
            "셋 중 하나를 고른다:\n"
            "  1. uvicorn을 --reload로 띄운다 (uvicorn이 Selector 루프를 쓴다)\n"
            "  2. CHECKPOINTER=memory 로 둔다 (대화가 프로세스 메모리에만 남는다)\n"
            "  3. docker compose로 띄운다 (컨테이너는 Linux라 해당 없음)"
        )


@asynccontextmanager
async def checkpointer_scope():
    """앱이 사는 동안 쓸 체크포인터를 열고, 끝나면 닫는다.

    ★ 컨텍스트 매니저인 이유 ★ 커넥션 풀은 **닫아야 하는 자원**이다. 모듈 레벨에서
    만들어두면 닫을 자리가 없고, 종료할 때 psycopg가 "pool was not closed" 경고를
    낸다. FastAPI의 lifespan과 모양이 같아서 main.py에서 `async with` 한 줄로 붙는다.
    """
    mode = settings.checkpointer
    if mode == "memory":
        logger.warning(
            "체크포인터가 memory다 — 재시작하면 대화가 사라지고 워커/파드가 둘 이상이면 섞인다"
        )
        yield InMemorySaver()
        return

    if mode != "postgres":
        # vector_store와 같은 규칙: 오타는 조용한 기본값이 아니라 이름을 담은 죽음으로.
        raise ValueError(f"모르는 CHECKPOINTER: {mode!r} (가능: postgres | memory)")

    # ★ import를 함수 안에서 한다 ★ psycopg_pool과 langgraph-checkpoint-postgres는
    # memory 모드에서는 전혀 필요 없다. 모듈 레벨에서 import하면 "체크포인터를 안 쓰는
    # 스크립트"(평가 하네스, 인입 CLI)까지 이 패키지들을 끌고 온다.
    import asyncio

    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from psycopg_pool import AsyncConnectionPool

    ensure_loop_supports_psycopg(asyncio.get_running_loop())

    pool = AsyncConnectionPool(
        conninfo=to_psycopg_dsn(settings.database_url),
        min_size=1,
        max_size=settings.checkpointer_pool_size,
        # open=False + 아래 open(wait=False)가 짝이다. 생성자에서 여는 것은 psycopg_pool이
        # 권장하지 않는다(이벤트 루프가 아직 없을 수 있다).
        open=False,
        kwargs={
            # ★ 둘 다 langgraph의 postgres 체크포인터가 요구하는 값이다 ★
            # autocommit=False면 saver가 트랜잭션을 직접 관리하지 못해 교착이 난다.
            # prepare_threshold=0은 prepared statement 캐시를 끈다 — 풀이 커넥션을
            # 재사용하는데 pgbouncer 같은 중간층이 끼면 캐시가 어긋나 조용히 깨진다.
            "autocommit": True,
            "prepare_threshold": 0,
        },
    )
    # ★ wait=False가 중요하다 ★ True로 두면 DB가 아직 안 떴을 때 **앱 기동 자체가
    # 막힌다.** k8s에서 backend 파드는 postgres보다 먼저 뜰 수 있고, migrate/ingest
    # Job도 아직 안 돌았을 수 있다. 풀은 백그라운드로 붙고, 그때까지 채팅만 실패한다 —
    # items CRUD와 헬스체크는 그대로 돈다. "한 기능의 의존성이 앱 전체를 못 뜨게
    # 만들지 않는다"가 이 저장소가 Langfuse에서도 지켜온 규칙이다.
    await pool.open(wait=False)
    logger.info("체크포인터: postgres (pool max_size=%d)", settings.checkpointer_pool_size)
    try:
        yield AsyncPostgresSaver(pool)
    finally:
        await pool.close()
