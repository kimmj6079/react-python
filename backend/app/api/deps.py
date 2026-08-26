# FastAPI 라우터에서 공통으로 쓰는 의존성(dependency)을 모아두는 파일.
from typing import Annotated

from fastapi import Depends
from langchain_anthropic import ChatAnthropic
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.graph import build_graph

# DbSession이라는 타입 별칭을 만들어두면, 라우터 함수 파라미터에서
# `db: DbSession`이라고만 써도 FastAPI가 자동으로 get_db()를 호출해 세션을 주입해준다.
DbSession = Annotated[Session, Depends(get_db)]

# 모델과 그래프는 모듈 레벨에 하나만 만들어 재사용한다. ChatAnthropic은 내부에
# HTTP 커넥션 풀을 들고 있고, 그래프 컴파일도 매 요청마다 할 이유가 없다.
#
# ★ streaming=True가 핵심이다 ★
# 기본값은 False이고, False여도 astream(stream_mode="messages")는 "에러 없이"
# 동작한다 — 다만 청크가 1개(완성된 답 전체)만 나온다. 화면에서는 글자가 흐르지
# 않고 툭 나타나는 것으로만 드러나서 원인을 찾기 매우 어렵다.
# (실측: streaming=False -> 청크 1개 / streaming=True -> 청크 3개)
#
# api_key를 명시적으로 넘기는 이유: 안 넘기면 ChatAnthropic이 환경변수를 직접
# 읽는데, 그러면 "DB/시크릿 설정은 Settings 한 곳에서만"이라는 이 저장소의
# 원칙(alembic/env.py와 같은 규칙)이 깨진다.
_model = ChatAnthropic(
    model=settings.anthropic_model,
    api_key=settings.anthropic_api_key,
    max_tokens=1024,
    streaming=True,
)

_graph = build_graph(_model)


def get_graph() -> CompiledStateGraph:
    # 함수로 한 겹 감싸는 이유는 M1의 get_anthropic_client()와 같다:
    # pytest에서 app.dependency_overrides로 가짜 그래프로 교체하기 위함이다.
    # 라우터가 _graph를 직접 import하면 그 교체가 불가능해진다.
    return _graph


Graph = Annotated[CompiledStateGraph, Depends(get_graph)]
