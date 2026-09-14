# FastAPI 라우터에서 공통으로 쓰는 의존성(dependency)을 모아두는 파일.
import asyncio
import logging
from functools import partial
from typing import Annotated

from fastapi import Depends, Header, Request
from langchain_anthropic import ChatAnthropic
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.graph import build_graph
from app.rag.access import DEFAULT_TENANT, Principal
from app.rag.base import TOP_K, RetrievedChunk
from app.rag.factory import get_store
from app.rag.rerank import rerank
from app.rag.retriever import retrieve
from app.rag.rewrite import rewrite_query

logger = logging.getLogger(__name__)

# DbSession이라는 타입 별칭을 만들어두면, 라우터 함수 파라미터에서
# `db: DbSession`이라고만 써도 FastAPI가 자동으로 get_db()를 호출해 세션을 주입해준다.
DbSession = Annotated[Session, Depends(get_db)]


def get_principal(
    x_tenant_id: Annotated[str | None, Header()] = None,
    x_roles: Annotated[str | None, Header()] = None,
) -> Principal:
    """요청자의 권한. (M12)

    ★★ 여기가 실제 인증이 들어갈 자리다 ★★
    지금은 헤더를 그대로 믿는다 - 누구나 `X-Tenant-Id: other`를 보내면 남의 테넌트를
    볼 수 있다. **이 상태는 보안이 아니라 배선일 뿐이다.**

    실무에서는 이 함수가:
      1) Authorization 헤더의 JWT를 검증하고(서명·만료·issuer)
      2) 그 토큰의 클레임에서 tenant_id와 roles를 꺼낸다
    헤더를 그대로 쓰는 지금 구조와 **함수 시그니처는 같다** - 그래서 인증을 붙일 때
    이 함수 하나만 바꾸면 되고, 호출하는 쪽(chat.py)은 손대지 않는다.
    권한을 요청 경로의 한 곳으로 모아두는 것 자체가 그 교체를 싸게 만든다.
    """
    roles = frozenset(r.strip() for r in (x_roles or "").split(",") if r.strip())
    return Principal(tenant_id=x_tenant_id or DEFAULT_TENANT, roles=roles)


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]

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

# ★★ M5-2: 체크포인터가 모듈 레벨에서 사라졌다 ★★
# 2b부터 여기에 `_checkpointer = InMemorySaver()` 한 줄이 있었고, 그 아래에
# "실무에서는 AsyncPostgresSaver를 쓴다. 전환 비용은 (a) 의존성 (b) 여기 한 줄
# (c) setup() 뿐이다"라고 적어뒀었다. **(b)가 한 줄이 아니었다.**
#
# 커넥션 풀은 (1) 이벤트 루프가 있어야 열 수 있고 (2) 닫을 자리가 있어야 한다.
# 모듈 import 시점에는 둘 다 없다. 그래서 체크포인터도, 그것을 물고 있는 그래프도
# **lifespan으로 옮겼다**(app/main.py). 옛 주석이 낙관적이었던 것을 기록으로 남긴다 —
# "한 줄이면 된다"는 추정은 그 줄을 실제로 써볼 때까지만 유효하다.
#
# 옮긴 값: 앱이 살아 있는 동안만 풀이 열려 있고, 종료할 때 정확히 닫힌다.
# 잃은 것: `from app.api.deps import _graph`처럼 import만으로 그래프를 얻을 수 없다.
# (그래도 되는 이유 — 그래프가 필요한 곳은 라우터뿐이고, 라우터는 Depends로 받는다.)


# ★ 3-4: 예고한 대로 이 한 줄만 바뀌었다 ★
# 3-3a에서 `_store = PgVectorStore()`였고, 지금은 settings.vector_store를 읽는
# 팩토리 호출이다. graph.py도 chat.py도 retriever.py도 테스트도 한 줄 안 바뀌었다 —
# 2b에서 체크포인터를, 2c에서 도구를 인자로 밀어냈을 때와 같은 성질이 회수된 지점이다.
#
# 모듈 레벨에서 한 번만 만든다: QdrantStore는 HTTP 커넥션을 들고 있어서 요청마다
# 새로 만들면 연결이 요청 수만큼 생긴다(_model·_checkpointer와 같은 이유).
_store = get_store()


async def _retrieve(query: str, principal: Principal) -> list[RetrievedChunk]:
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
    # ★ M10: 그라운딩 게이트 ★ 설정이 켜져 있을 때만 임계값을 넘긴다.
    # None이면 retrieve 안에서 게이트 자체가 없는 것과 같다 - 평가 스크립트가
    # 게이트 없이 도는 경로와 정확히 같은 코드를 쓴다.
    max_distance = settings.grounding_max_distance if settings.grounding_enabled else None

    if not settings.rerank_enabled:
        return await asyncio.to_thread(
            partial(retrieve, _store, query, principal, TOP_K, max_distance=max_distance)
        )

    # ★ 게이트는 리랭킹 **앞**이다 ★ 뒤에 두면 근거도 없는 20개 후보에 LLM을
    # 20번 부른 뒤에 버리게 된다. 거절할 질문일수록 빨리 거절하는 것이 싸다.
    candidates = await asyncio.to_thread(
        partial(
            retrieve,
            _store,
            query,
            principal,
            settings.rerank_candidates,
            max_distance=max_distance,
        )
    )
    if not candidates:
        # 게이트가 걸렸거나 필터가 전부 걸러냈다. **여기서 이미 LLM 20번을 아낀다** —
        # M10에서 "게이트는 리랭킹 앞"이라고 위치를 고른 값이 지연 예산에서 회수된다.
        return []

    # ★ M13-b: 스킵 조건 ★ 후보가 top_k보다 많지 않으면 순서를 바로잡을 이유가 적다.
    # 조용히 넘어가지 않고 로그를 남긴다 — "리랭킹이 켜져 있는데 왜 리랭킹 로그가 없지?"를
    # 나중에 추적하는 것보다, 발동 사실을 그때 찍어두는 편이 항상 싸다.
    if len(candidates) < settings.rerank_min_candidates:
        logger.info(
            "리랭킹 스킵: 후보 %d개 < %d개",
            len(candidates),
            settings.rerank_min_candidates,
        )
        return candidates[:TOP_K]

    return await rerank(query, candidates, TOP_K)


async def _rewrite(question: str, history: list[dict[str, str]]) -> str:
    # graph.py가 받는 rewrite_fn의 구현체. 설정이 꺼져 있으면 원문을 그대로 쓴다 —
    # "기능을 끈다"와 "히스토리가 없다"는 다른 이유이고, 전자는 여기서, 후자는
    # rewrite_query() 안에서 각각 판단한다.
    if not settings.query_rewrite_enabled:
        return question
    return await rewrite_query(question, history)


def build_app_graph(checkpointer) -> CompiledStateGraph:
    """이 앱이 쓰는 그래프를 만든다. lifespan이 딱 한 번 부른다. (M5-2)

    ★ 체크포인터만 인자로 받는다 ★ 모델·검색·재작성은 여전히 이 파일이 고른다.
    lifespan에게 넘긴 것은 "언제 만들고 언제 버릴지"뿐이고, "무엇으로 만들지"는
    그대로 deps.py의 책임이다 — main.py가 ChatAnthropic을 알아야 할 이유가 없다.
    """
    return build_graph(
        _model,
        retrieve_fn=_retrieve,
        checkpointer=checkpointer,
        rewrite_fn=_rewrite,
    )


def get_graph(request: Request) -> CompiledStateGraph:
    # 함수로 한 겹 감싸는 이유는 M1의 get_anthropic_client()와 같다:
    # pytest에서 app.dependency_overrides로 가짜 그래프로 교체하기 위함이다.
    # (M5-2에서 인자가 하나 생겼지만 교체 방식은 그대로다 — dependency_overrides는
    #  원래 시그니처를 보지 않으므로 `lambda: fake_graph`가 계속 통한다.)
    graph = getattr(request.app.state, "graph", None)
    if graph is None:
        # ★ 조용히 None을 주지 않는다 ★ 그러면 라우터 안쪽 깊은 곳에서
        # AttributeError로 만나고, 원인이 "lifespan을 안 거쳤다"라는 것을 알아보기 어렵다.
        # 가장 흔한 원인: TestClient를 `with` 없이 쓰면 lifespan이 안 돈다.
        raise RuntimeError(
            "그래프가 없다 — lifespan이 실행되지 않았다. "
            "TestClient는 `with TestClient(app) as c:` 형태여야 lifespan이 돈다."
        )
    return graph


Graph = Annotated[CompiledStateGraph, Depends(get_graph)]
