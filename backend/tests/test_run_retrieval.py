# 평가 러너의 "숫자 만들기" 부분만 떼어 검증한다. (M13-d)
#
# ★ 검색을 돌리지 않는다 ★ compute_metrics는 이미 판정이 끝난 bool 리스트를 받아
# 집계만 한다(metrics.py와 같은 설계). 그래서 임베딩 모델도 벡터 DB도 없이 테스트된다.
#
# ★ 왜 이걸 따로 테스트하나 ★ 이 함수가 만든 딕셔너리를 **표와 게이트가 동시에** 본다.
# 여기가 틀리면 화면의 표와 CI의 판정이 서로 다른 숫자를 말하게 되고, 그 순간
# "CI는 빨간데 내 화면은 초록"이 되어 아무도 게이트를 안 믿는다.
from evals.run_retrieval import Case, compute_metrics


def row(case_id: str, kind: str, by_content: list[bool], *, answerable: bool = True) -> dict:
    """run_retrieval.main()이 만드는 행과 같은 모양을 손으로 만든다."""
    case = Case(
        id=case_id,
        kind=kind,
        question="q",
        expected_sources=["CLAUDE.md"] if answerable else [],
        expected_substrings=["정답"] if answerable else [],
    )
    return {"case": case, "by_content": by_content, "by_source": by_content}


def test_reports_each_kind_and_an_overall_row():
    rows = [
        row("n01", "normal", [True, False, False]),  # 1등
        row("n02", "normal", [False, True, False]),  # 2등
        row("k01", "keyword", [True, False, False]),  # 1등
    ]

    result = compute_metrics(rows, top_k=5)

    assert result["normal"] == {"n": 2, "hit@1": 0.5, "hit@k": 1.0, "mrr": 0.75}
    assert result["keyword"] == {"n": 1, "hit@1": 1.0, "hit@k": 1.0, "mrr": 1.0}
    assert result["overall"]["n"] == 3


def test_excludes_unanswerable_from_the_numbers():
    # 정답 청크가 없는 질문은 MRR이 정의되지 않는다. 넣으면 전부 0.0으로 잡혀
    # "검색이 나쁘다"처럼 보이는데, 실제로는 애초에 잴 수 없는 질문이다.
    rows = [
        row("n01", "normal", [True, False]),
        row("u01", "unanswerable", [False, False], answerable=False),
    ]

    result = compute_metrics(rows, top_k=5)

    assert result["overall"]["n"] == 1
    assert "unanswerable" not in result


def test_omits_kinds_that_have_no_cases():
    # ★ 게이트와 맞물리는 지점이다 ★ 골든셋에서 keyword를 전부 지우면 여기에 keyword
    # 키가 아예 없어야 하고, 그래야 gate.check가 "측정 안 됨" 위반으로 잡는다.
    # 여기서 0.0으로 채워 내보내면 게이트는 "지표가 0으로 떨어졌다"고 말하고,
    # 원인이 "코드가 나빠졌다"인지 "골든셋이 사라졌다"인지 구분할 수 없게 된다.
    result = compute_metrics([row("n01", "normal", [True])], top_k=5)

    assert set(result) == {"normal", "overall"}


def test_hit_at_k_honours_top_k():
    rows = [row("n01", "normal", [False, False, True])]  # 3등

    assert compute_metrics(rows, top_k=2)["overall"]["hit@k"] == 0.0
    assert compute_metrics(rows, top_k=3)["overall"]["hit@k"] == 1.0
