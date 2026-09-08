# FastAPI 라우터에서 공통으로 쓰는 의존성(dependency)을 모아두는 파일.
import asyncio
from typing import Annotated

from fastapi import Depends
from langchain_anthropic import ChatAnthropic
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.graph import build_graph
from app.rag.base import TOP_K, RetrievedChunk
from app.rag.factory import get_store
from app.rag.rerank import rerank
from app.rag.retriever import retrieve
from app.rag.rewrite import rewrite_query

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


# ★ 3-4: 예고한 대로 이 한 줄만 바뀌었다 ★
# 3-3a에서 `_store = PgVectorStore()`였고, 지금은 settings.vector_store를 읽는
# 팩토리 호출이다. graph.py도 chat.py도 retriever.py도 테스트도 한 줄 안 바뀌었다 —
# 2b에서 체크포인터를, 2c에서 도구를 인자로 밀어냈을 때와 같은 성질이 회수된 지점이다.
#
# 모듈 레벨에서 한 번만 만든다: QdrantStore는 HTTP 커넥션을 들고 있어서 요청마다
# 새로 만들면 연결이 요청 수만큼 생긴다(_model·_checkpointer와 같은 이유).
_store = get_store()


async def _retrieve(query: str) -> list[RetrievedChunk]:
    # graph.py가 받는 retrieve_fn의 실제 구현체.
    #
    # ★ 이 함수에서 SQLAlchemy가 사라졌다 ★ 3-2b에는 with SessionLocal()이 있었다 —
    # 즉 "그래프는 저장소를 모른다"고 써놓고 그 바로 옆 파일이 Postgres를 알고
    # 있었다. 이제 세션은 PgVectorStore 안에만 있고, deps.py가 아는 것은 "store를
    # 하나 골라 retrieve에 넘긴다"뿐이다.
    #
    # 함수를 한 겹 남겨두는 이유: graph.py의 retrieve_fn 타입이
    # Callable[[str], list[RetrievedChunk]]라 "질문 하나 받아 청크 리스트를 주는"
    # 모양이어야 하는데, store.search는 벡터를 받는다. 임베딩을 끼워 넣는 이 한 줄이
    # 두 모양을 잇는 어댑터다.
    # ★ M8-b: 검색이 2단이 됐다 ★
    #   1) 하이브리드로 넉넉히 뽑는다(재현율)  2) 리랭킹으로 순서를 바로잡는다(정밀도)
    # 리랭킹이 꺼져 있으면 1단만 돌고 예전과 완전히 같다 — 켜고 끄는 것이 설정 한 줄이라
    # M6 하네스로 A/B를 돌릴 수 있다.
    if not settings.rerank_enabled:
        return await asyncio.to_thread(retrieve, _store, query, TOP_K)

    candidates = await asyncio.to_thread(retrieve, _store, query, settings.rerank_candidates)
    return await rerank(query, candidates, TOP_K)


async def _rewrite(question: str, history: list[dict[str, str]]) -> str:
    # graph.py가 받는 rewrite_fn의 구현체. 설정이 꺼져 있으면 원문을 그대로 쓴다 —
    # "기능을 끈다"와 "히스토리가 없다"는 다른 이유이고, 전자는 여기서, 후자는
    # rewrite_query() 안에서 각각 판단한다.
    if not settings.query_rewrite_enabled:
        return question
    return await rewrite_query(question, history)


_graph = build_graph(
    _model,
    retrieve_fn=_retrieve,
    checkpointer=_checkpointer,
    rewrite_fn=_rewrite,
)


def get_graph() -> CompiledStateGraph:
    # 함수로 한 겹 감싸는 이유는 M1의 get_anthropic_client()와 같다:
    # pytest에서 app.dependency_overrides로 가짜 그래프로 교체하기 위함이다.
    # 라우터가 _graph를 직접 import하면 그 교체가 불가능해진다.
    return _graph


Graph = Annotated[CompiledStateGraph, Depends(get_graph)]
