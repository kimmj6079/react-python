# 검색 품질 지표. (M6)
#
# ★ 이 파일만 pytest 대상이다 ★ evals/ 나머지는 실제 임베딩·LLM API를 부르므로 CI에서
# 돌면 안 되지만(chatbot/README.md의 CI 경고), 지표 계산은 API를 안 부르는 순수 함수다.
# 그리고 **지표 계산이 틀리면 그 뒤 모든 판단이 틀린다** — M7~M13이 전부 이 숫자를 보고
# "좋아졌다/나빠졌다"를 결정하므로, 계측기 자체는 반드시 테스트한다.
#
# ★ 설계: "무엇이 정답인가"와 "어떻게 점수 매기나"를 분리했다 ★
# 이 파일의 함수들은 검색 결과가 무엇인지 전혀 모른다. 받는 것은 `relevance` —
# 상위 k개 각각이 정답인지 아닌지를 담은 bool 리스트뿐이다.
#   [False, True, False, ...]   # 2등이 정답
# 판정(파일명이 맞나? 내용이 들어있나?)은 run_retrieval.py가 하고, 여기는 채점만 한다.
# 덕분에 M8에서 하이브리드 검색이 들어와 판정 방식이 바뀌어도 이 파일은 안 바뀐다 —
# graph.py가 retrieve_fn을 인자로 받는 것과 같은 사고방식이다.
from collections.abc import Sequence


def hit_at_k(relevance: Sequence[bool], k: int) -> bool:
    """상위 k개 안에 정답이 하나라도 있는가.

    "몇 개나 맞췄나"가 아니라 **"하나라도 들어왔나"** 라는 점이 중요하다. RAG에서는
    정답 청크 하나만 프롬프트에 들어가면 모델이 답할 수 있으므로, 재현율(recall)이
    정밀도보다 훨씬 중요하다. 그래서 이 이진 판정이 RAG 검색의 표준 지표다.

    k가 리스트 길이보다 커도 에러가 아니라 있는 만큼만 본다 — top_k=5 설정에서
    hit@10을 계산해달라고 하면 "5개 중에 있나"가 되는 게 자연스럽다.
    """
    if k <= 0:
        raise ValueError(f"k는 1 이상이어야 한다 (받은 값: {k})")
    return any(relevance[:k])


def reciprocal_rank(relevance: Sequence[bool]) -> float:
    """첫 정답의 순위의 역수. 1등이면 1.0, 2등이면 0.5, 없으면 0.0.

    hit@k가 "들어왔나"만 본다면 이건 **"얼마나 위에 들어왔나"** 를 본다. 둘 다 필요하다:
    hit@5는 그대로인데 MRR이 떨어졌다면 정답이 5등에서 1등으로 밀려 내려간 것이고,
    그건 프롬프트 앞쪽이 잡음으로 채워졌다는 뜻이라 답변 품질이 나빠진다
    (M8 리랭킹이 정확히 이 숫자를 올리려고 하는 일이다).

    ★ 정답이 없으면 0.0이다 — 이게 조용한 함정이 될 수 있다 ★
    "정답이 없는 질문"(unanswerable)까지 여기에 넣으면 전부 0.0이 되어 평균을 끌어내린다.
    그건 검색이 나쁜 게 아니라 애초에 잴 수 없는 질문인데도. run_retrieval.py가
    unanswerable을 이 계산에서 제외하는 이유다.
    """
    for index, is_relevant in enumerate(relevance):
        if is_relevant:
            return 1.0 / (index + 1)
    return 0.0


def mean(values: Sequence[float]) -> float:
    """빈 리스트를 0.0으로 돌려주는 평균.

    statistics.mean은 빈 입력에 StatisticsError를 던진다. 여기서는 "해당 종류의 질문이
    골든셋에 하나도 없다"가 정상 상황이라(예: multiturn은 M9에서야 생긴다) 예외 대신
    0.0을 준다. 대신 표에 건수(n)를 반드시 함께 찍어서 "0.0인데 n=0"을 구분할 수 있게 한다 —
    n을 안 찍으면 "지표가 0이다(나쁘다)"와 "잴 게 없었다"가 화면에서 똑같아 보인다.
    """
    if not values:
        return 0.0
    return sum(values) / len(values)
