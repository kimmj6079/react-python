# FastAPI 앱의 진입점(entry point). `uvicorn app.main:app`으로 이 파일의 app 객체를 띄운다.
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.deps import build_app_graph
from app.api.routes import chat, documents, health, items
from app.core.checkpointer import checkpointer_scope
from app.core.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """앱이 사는 동안만 존재해야 하는 것들을 여기서 열고 닫는다. (M5-2)

    ★ 왜 lifespan이 생겼나 ★ M5-1까지 그래프는 deps.py의 모듈 레벨에서 만들어졌다.
    `InMemorySaver()`는 그래도 됐다 — 자원을 안 잡으니까. 그런데 Postgres 체크포인터는
    **커넥션 풀**이고, 풀은 (1) 이벤트 루프가 있어야 열 수 있고 (2) 닫을 자리가 있어야 한다.
    import 시점에는 둘 다 없다. 그래서 생성 시점을 여기로 옮겼다.
    (deps.py의 옛 주석은 이 전환을 "여기 한 줄"이라고 낙관했는데, 한 줄이 아니었다.)

    ★ yield 앞이 기동, 뒤가 종료다 ★ `async with`가 그 둘을 짝지어 준다 —
    예외가 나도 finally처럼 닫힌다. 예전 `@app.on_event("startup"/"shutdown")`은
    둘이 따로 떨어져 있어서 "연 것과 닫는 것"이 코드상 멀었고, 지금은 deprecated다.

    ★ 여기서 DDL을 돌리지 않는다 ★ `checkpointer.setup()`을 부르는 예제가 많지만
    이 저장소는 안 그런다 — CLAUDE.md의 "마이그레이션은 절대 컨테이너 시작 시 자동
    실행되지 않는다"와 같은 규칙이다. 테이블은 `python -m app.db.checkpointer_setup`이
    만든다. 롤링 업데이트 중 파드 여럿이 동시에 DDL을 돌리는 일도 이걸로 사라진다.
    """
    async with checkpointer_scope() as checkpointer:
        # ★ app.state에 두는 이유 ★ 모듈 전역에 두면 테스트가 앱을 여러 개 만들 때
        # 서로의 그래프를 밟는다. state는 앱 인스턴스에 매달려 있어 수명이 정확히 앱과 같다.
        app.state.graph = build_app_graph(checkpointer)
        yield
        # 여기부터 종료. 그래프 자체는 정리할 게 없고, 풀은 checkpointer_scope가 닫는다.
        app.state.graph = None


def create_app() -> FastAPI:
    # 함수로 감싸두면 테스트할 때마다 독립된 FastAPI 인스턴스를 새로 만들 수 있어 편리하다.
    app = FastAPI(title=settings.project_name, lifespan=lifespan)

    # CORS: 브라우저가 다른 origin(예: localhost:5173)에서 이 API(localhost:8000)를
    # 호출할 수 있도록 허용하는 설정. 로컬 dev에서 프론트/백엔드 포트가 다르기 때문에 필요하다.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 라우터 등록: health는 접두사 없이(/health), items는 /api/v1 접두사를 붙여(/api/v1/items) 노출.
    app.include_router(health.router)
    app.include_router(items.router, prefix=settings.api_v1_prefix)
    app.include_router(chat.router, prefix=settings.api_v1_prefix)
    # M11: 문서 업로드/상태. chat과 같은 /api/v1 접두어를 공유한다.
    app.include_router(documents.router, prefix=settings.api_v1_prefix)

    return app


# 모듈이 import될 때 실제로 사용할 앱 인스턴스를 한 번 생성해둔다.
app = create_app()
