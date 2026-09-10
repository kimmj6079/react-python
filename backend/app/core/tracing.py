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


# ---------------------------------------------------------------------------
# M13: 피드백 루프 — 사용자의 👍/👎를 트레이스에 붙인다
# ---------------------------------------------------------------------------
# ★ 로드맵이 여기서 원형으로 닫힌다 ★
# M4에서 "무슨 일이 있었는가"(트레이스)를 남겼고, M6에서 "얼마나 잘하는가"(골든셋)를
# 쟀다. 둘 사이에 빠져 있던 것이 **"실제 사용자가 이 답을 어떻게 봤는가"** 다.
# 골든셋 24건은 내가 상상한 질문이고, 👎가 붙은 대화는 상상하지 못한 질문이다.
# 그것을 골든셋에 편입하면 회귀 테스트가 실사용에서 자라기 시작한다.
#
# ★ 저장소를 새로 만들지 않는다 ★ 피드백용 테이블 + 모델 + 마이그레이션을 만들고
# 싶어지지만, Langfuse에는 score라는 1급 개념이 이미 있고 트레이스와 같은 화면에서
# 묶여 보인다. "피드백만 있고 그때 무슨 문맥을 썼는지는 모르는" 표를 새로 만드는 것은
# 손해다 — M4를 붙여둔 값이 여기서 회수된다.
FEEDBACK_SCORE_NAME = "user-feedback"


def trace_id_of(callbacks: list[CallbackHandler]) -> str | None:
    """이번 요청이 만든 Langfuse 트레이스의 id. 트레이싱이 꺼져 있으면 None.

    ★ 핸들러의 내부 속성을 chat.py가 알게 두지 않는다 ★ 라우터가
    `callbacks[0].last_trace_id`를 직접 읽으면, Langfuse SDK가 속성 이름을 바꾸는 날
    라우터가 깨진다. 트레이싱 배선의 세부는 이 파일 안에만 둔다 — get_callbacks()가
    "빈 리스트"라는 표현을 여기서만 아는 것과 같은 규칙이다.

    ★ 언제 채워지는가(실측) ★ CallbackHandler.py:638·1250 — 관측(span/generation)을
    **시작**할 때 대입된다. 즉 그래프의 첫 노드가 돌기 시작하면 이미 값이 있다.
    "스트림이 끝나야 알 수 있다"가 아니므로, finish 프레임에 실을 시점에는 항상 있다.
    """
    for handler in callbacks:
        trace_id = getattr(handler, "last_trace_id", None)
        if trace_id:
            return trace_id
    return None


def record_feedback(trace_id: str, *, positive: bool, comment: str | None = None) -> None:
    """👍/👎를 그 트레이스의 score로 남긴다.

    ★ data_type을 BOOLEAN으로 잡은 이유 ★ 엄지 두 개는 값이 두 개뿐이다.
    NUMERIC(1/0)으로 두면 대시보드가 "평균 0.62" 같은 숫자를 보여주는데, 그건
    만족도가 아니라 그냥 긍정 비율이라 눈금이 오해를 부른다. BOOLEAN이면
    true/false 분포로 그려지고, 나중에 "👎만 필터"가 자연스럽다 — 그 필터가
    골든셋 편입 절차의 입구가 된다.
    (CATEGORICAL "up"/"down"도 가능하지만, 값이 정확히 둘일 때는 BOOLEAN이 더 좁다.
     좁은 타입을 고르는 것은 schemas/chat.py의 role: Literal과 같은 판단이다.)

    ★ flush()를 부르지 않는다 ★ Langfuse 클라이언트는 백그라운드 스레드가 배치로
    전송한다. 여기서 flush()를 부르면 사용자가 엄지를 누른 요청이 네트워크 왕복을
    기다리게 된다 — 관측성 때문에 사용자 경험을 깎는 전형적인 실수다.
    (반대로 **짧게 살고 죽는 프로세스**에서는 반드시 flush()해야 한다. CLI 스크립트가
     끝나면서 큐에 남은 이벤트가 통째로 사라지기 때문이다 — scripts/probe_langfuse.py
     가 flush()를 부르는 이유가 이것이고, 웹 서버는 계속 살아 있어 그럴 필요가 없다.)
    """
    if not settings.langfuse_enabled:
        # ★ 조용히 no-op 하지 않는다 ★ create_score()는 트레이싱이 꺼져 있으면
        # 아무 말 없이 return한다(실측: client.py "if not self._tracing_enabled").
        # 그대로 두면 "피드백 버튼은 눌리는데 어디에도 안 쌓이는" 상태가 되고,
        # 그건 M11에서 배운 "인입 실패를 조용히 삼키면 최악"과 정확히 같은 실패다.
        # 부르는 쪽(라우터)이 먼저 걸러야 하고, 여기까지 왔다면 그 가드가 깨진 것이다.
        raise RuntimeError("Langfuse가 꺼져 있어 피드백을 저장할 곳이 없다")

    get_langfuse_client().create_score(
        name=FEEDBACK_SCORE_NAME,
        value=1 if positive else 0,
        data_type="BOOLEAN",
        trace_id=trace_id,
        comment=comment,
        # ★ score_id를 결정론적으로 준다 ★ 안 주면 SDK가 매번 새 id를 만들어서,
        # 엄지를 두 번 누르면 점수가 두 개 쌓인다(👍 뒤에 👎를 누르면 둘 다 남는다).
        # 트레이스당 피드백은 하나라는 모델을 id로 표현한다 — M11에서 포인트 id를
        # uuid5로 만들어 재인입을 멱등으로 만든 것과 **완전히 같은 기법**이다.
        #
        # 인증이 붙으면 f"{trace_id}:{user_id}"가 되어 "사용자당 하나"로 넓어진다.
        # 지금은 사용자 개념 자체가 없으니 트레이스 하나가 곧 한 사람의 한 번이다.
        #
        # ★ 확인할 항목 ★ 같은 id로 다시 보냈을 때 서버가 덮어쓰는지(upsert)는
        # 대시보드에서 눈으로 봐야 한다. 여기서는 "덮어쓰라는 의도"까지만 표현한다.
        score_id=trace_id,
    )
    logger.info("피드백 기록: trace=%s positive=%s", trace_id, positive)
