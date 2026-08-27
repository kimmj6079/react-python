# FastAPI 라우터에서 공통으로 쓰는 의존성(dependency)을 모아두는 파일.
from typing import Annotated

from fastapi import Depends
from langchain_anthropic import ChatAnthropic
from langgraph.checkpoint.memory import InMemorySaver
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

# ★ 2b: 대화 상태의 저장소 ★
# 이 객체 하나가 "모든 스레드의 모든 대화"를 들고 있다. 모듈 레벨에 두는 게
# 필수다 — 요청마다 새로 만들면 매번 빈 저장소라 아무것도 기억하지 못한다.
# (그런데도 에러는 안 난다. "매번 첫 턴처럼 행동"할 뿐이다.)
#
# ★ InMemorySaver의 한계를 알고 쓴다 ★ 이름 그대로 파이썬 프로세스 메모리다.
#   1) --reload가 소스 변경을 감지해 재시작하면 전 대화가 사라진다.
#      개발 중에 "왜 갑자기 기억을 못 하지?"의 90%가 이것이다.
#   2) uvicorn --workers 2 이상이면 요청이 워커에 흩어지는데 워커마다 별도
#      메모리라 대화가 뒤죽박죽 된다. k8s에서 replicas를 2로 올려도 같다.
#      → 즉 이 상태로는 절대 스케일아웃할 수 없다.
#   3) 지우는 코드가 없어서 스레드가 쌓이기만 한다. 프로세스가 오래 살면 누수다.
#
# 실무에서는 langgraph-checkpoint-postgres의 AsyncPostgresSaver를 쓴다. 이
# 저장소에는 이미 Postgres가 있으니 전환 비용은 (a) 의존성 추가 (b) 여기 한 줄
# (c) 체크포인터 테이블 생성(setup()) 뿐이다 — build_graph도 chat.py도 안 바뀐다.
# 학습 단계에서 InMemorySaver로 시작하는 이유는 "체크포인터 개념"과 "DB 스키마
# 마이그레이션"이라는 미지수 두 개를 동시에 열지 않기 위해서다.
_checkpointer = InMemorySaver()

_graph = build_graph(_model, checkpointer=_checkpointer)


def get_graph() -> CompiledStateGraph:
    # 함수로 한 겹 감싸는 이유는 M1의 get_anthropic_client()와 같다:
    # pytest에서 app.dependency_overrides로 가짜 그래프로 교체하기 위함이다.
    # 라우터가 _graph를 직접 import하면 그 교체가 불가능해진다.
    return _graph


Graph = Annotated[CompiledStateGraph, Depends(get_graph)]
