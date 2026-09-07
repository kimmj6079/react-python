# Langfuse 트레이싱 배선. (M4)
#
# ★ 이 파일이 존재하는 이유 = "가림막을 걷는 것" ★
# 2a에서 LangChain을 도입하며 "추상화 층이 하나 늘어 무슨 요청이 나가는지가 한 겹
# 가려진다"를 대가로 적어뒀다. M3에서 retrieve 노드가 붙으면서 가려진 것이 더 늘었다 —
# 검색이 무엇을 가져왔는지, 시스템 프롬프트가 실제로 어떻게 조립됐는지, 도구 왕복에
# 토큰이 얼마나 들었는지를 볼 방법이 없다. 그 가림막을 걷는 것이 M4다.
#
# ★ 배선이 두 단계인 것이 v3/v4의 핵심 변화다 (scripts/probe_langfuse.py 실측 ④) ★
#   1) Langfuse(public_key, secret_key, host) 클라이언트를 프로세스에 하나 만든다
#   2) 요청마다 CallbackHandler()를 만들어 RunnableConfig의 callbacks에 넣는다
# v2에서는 CallbackHandler가 자격증명을 직접 받았다. 인터넷 예제 대부분이 v2 기준이라
# 그대로 베끼면 TypeError가 난다 — 문서가 아니라 설치된 패키지에게 물어본 이유다.
import logging

from langfuse import Langfuse
from langfuse.langchain import CallbackHandler

from app.core.config import settings

logger = logging.getLogger(__name__)

# 프로세스당 하나. Langfuse 클라이언트는 백그라운드 전송 스레드와 큐를 들고 있어서
# 요청마다 만들면 스레드가 요청 수만큼 생긴다(deps.py의 _model·_store와 같은 이유).
#
# import 시점이 아니라 첫 사용 시점에 만든다(lazy). rag/embedding.py가 모델 로딩을
# lazy로 둔 것과 같은 판단이다: 키가 없는 pytest·CI에서 "import만 했는데 네트워크
# 클라이언트가 뜨는" 일이 없어야 한다.
_client: Langfuse | None = None


def get_langfuse_client() -> Langfuse:
    """Langfuse 클라이언트 싱글턴. 키가 없으면 부르면 안 된다(is_enabled로 먼저 거른다)."""
    global _client
    if _client is None:
        # ★ 자격증명을 명시적으로 넘긴다 ★ 안 넘기면 Langfuse가 환경변수를 직접 읽는데,
        # 그러면 "설정은 Settings 한 곳에서만"이라는 이 저장소의 원칙(alembic/env.py,
        # deps.py의 ChatAnthropic(api_key=...))이 깨진다. 값이 어디서 왔는지 추적할 수
        # 있어야 "왜 트레이스가 안 쌓이지"를 5분 안에 푼다.
        _client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
        logger.info("Langfuse 트레이싱 활성화 (host=%s)", settings.langfuse_host)
    return _client


def get_callbacks() -> list[CallbackHandler]:
    """RunnableConfig의 `callbacks`에 그대로 넣을 리스트. 키가 없으면 빈 리스트다.

    ★ 키가 없을 때 "빈 핸들러"가 아니라 "빈 리스트"를 주는 이유 ★
    실측(probe_langfuse.py ⑤): 키 없이 CallbackHandler()를 만들어도 예외가 아니라
    stderr 경고 한 줄이고 핸들러는 만들어진다("Client will be disabled"). 즉 그대로
    써도 앱은 돌아간다. 그런데 그러면
      (a) 요청마다 그 경고가 찍혀 로그가 더러워지고
      (b) "트레이싱이 켜졌는가"가 코드 어디에서도 분명하지 않다.
    빈 리스트를 주면 LangChain이 콜백을 아예 안 부르므로 오버헤드가 진짜 0이 된다.

    ★ 요청마다 새로 만드는 이유 ★
    핸들러는 실행 중인 run들을 self._runs(OrderedDict)와 self.last_trace_id에 들고
    다닌다(실측). 하나를 공유하면 동시 요청들의 트레이스가 서로 섞인다 —
    에러가 아니라 "대시보드에서 남의 대화가 내 트레이스 안에 보이는" 형태로 드러난다.
    생성 자체는 I/O가 없어서 싸다(비싼 것은 위의 클라이언트다).
    """
    if not settings.langfuse_enabled:
        return []
    get_langfuse_client()  # 첫 호출에서 클라이언트를 준비시킨다
    return [CallbackHandler()]


def trace_metadata(session_id: str) -> dict[str, str]:
    """Langfuse가 알아보는 메타데이터 키로 변환한다.

    실측: 핸들러는 metadata에서 `langfuse_session_id` / `langfuse_user_id` /
    `langfuse_tags` 세 키만 특별 취급한다(CallbackHandler.py:496~520).
    **키 이름을 틀리면 에러가 아니라 그냥 평범한 메타데이터로 저장된다** —
    대시보드의 Sessions 뷰에서 대화가 묶이지 않는 것으로만 드러난다.

    thread_id를 그대로 session_id로 쓴다. 이 한 줄 덕분에 Langfuse Sessions 뷰의
    묶음이 우리 체크포인터의 대화 단위와 정확히 일치한다 — 트레이스 하나를 보다가
    "이 대화의 앞 턴은 뭐였지"로 바로 넘어갈 수 있다.

    user_id는 아직 없다. 인증이 없어서 넣을 값이 없기 때문이고, M12에서
    멀티테넌시를 다룰 때 `langfuse_user_id`가 여기 함께 들어온다.
    """
    return {"langfuse_session_id": session_id}
