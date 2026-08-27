# 그래프가 쓸 수 있는 "능력" 모음. 흐름(graph.py)과 분리한다.
#
# 왜 graph.py 안에 두지 않았나: 도구는 그래프의 구조가 아니라 그래프가 손을 뻗는
# 바깥 세상이다. 지금은 1개뿐이라 과해 보이지만 M3에서 문서 검색 도구가 붙고,
# 그때 graph.py에 도구 구현이 섞여 있으면 "흐름을 보려고 연 파일에서 zoneinfo와
# Qdrant 코드를 읽게" 된다. 덤: 모듈 레벨 함수라 테스트에서 그래프 없이 단독 호출된다.
from datetime import datetime
from zoneinfo import ZoneInfo

from langchain_core.tools import tool


@tool
def get_current_time(timezone: str = "Asia/Seoul") -> str:
    """지정한 타임존의 현재 시각을 ISO 8601 문자열로 돌려준다.

    Args:
        timezone: IANA 타임존 이름. 예: "Asia/Seoul", "UTC", "America/New_York"
    """
    # ★ 위 docstring은 사람이 아니라 모델이 읽는다 ★
    # 실측: Args 섹션까지 통째로 도구의 description이 되어 모델에게 전송된다.
    # 모델이 도구를 안 부르거나 엉뚱하게 부르면, 로직이 아니라 저 글을 먼저 고친다.
    # 타입 힌트(timezone: str)와 기본값은 JSON Schema로 변환되어 인자 모양이 된다.
    #
    # ★ 도구의 인자는 사용자가 아니라 LLM이 만든다 = 신뢰할 수 없는 입력이다 ★
    # 여기서는 모르는 이름이면 ZoneInfo가 예외를 던지는 것으로 충분하다.
    # 하지만 파일 경로·SQL·셸 명령을 받는 도구였다면 이 줄이 그대로 취약점이 된다
    # ("사용자가 시킨 게 아니라 모델이 만든 값"이라는 게 방어가 되지 않는다 —
    #  모델은 문서에 심어둔 문장에 설득당할 수 있다). M12에서 정면으로 다룬다.
    return datetime.now(ZoneInfo(timezone)).isoformat()


# 그래프에 넘길 목록. 여기에 추가하는 것만으로 모델이 쓸 수 있게 된다.
TOOLS = [get_current_time]
