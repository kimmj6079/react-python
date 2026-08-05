# FastAPI 앱의 진입점(entry point). `uvicorn app.main:app`으로 이 파일의 app 객체를 띄운다.
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import chat, health, items
from app.core.config import settings


def create_app() -> FastAPI:
    # 함수로 감싸두면 테스트할 때마다 독립된 FastAPI 인스턴스를 새로 만들 수 있어 편리하다.
    app = FastAPI(title=settings.project_name)

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

    return app


# 모듈이 import될 때 실제로 사용할 앱 인스턴스를 한 번 생성해둔다.
app = create_app()
