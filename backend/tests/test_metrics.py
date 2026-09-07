# 지표 계산 유닛 테스트. (M6)
#
# ★ evals/ 중 유일하게 pytest가 도는 파일이다 ★ API를 안 부르는 순수 함수라 CI에
# 넣어도 안전하고, **지표가 틀리면 M7~M13의 모든 판단이 틀리므로** 계측기 자체를
# 먼저 검증한다. "저울을 사면 먼저 아는 무게를 올려본다"와 같은 일이다.
import pytest

from evals.metrics import hit_at_k, mean, reciprocal_rank


@pytest.mark.parametrize(
    ("relevance", "k", "expected"),
    [
        ([True, False, False], 1, True),  # 1등이 정답
        ([False, True, False], 1, False),  # 2등이라 hit@1은 실패
        ([False, True, False], 3, True),  # hit@3은 성공
        ([False, False, False], 5, False),  # 아예 없음
        ([False, False, True], 5, True),  # k가 리스트보다 커도 있는 만큼만 본다
        ([], 5, False),  # 검색 결과 자체가 없음
    ],
)
def test_hit_at_k(relevance, k, expected):
    assert hit_at_k(relevance, k) is expected


def test_hit_at_k_rejects_bad_k():
    # k=0을 조용히 False로 돌려주면 "지표가 0인데 왜지"를 헤매게 된다.
    # 계측기의 잘못된 사용은 시끄럽게 죽는 편이 낫다.
    with pytest.raises(ValueError, match="1 이상"):
        hit_at_k([True], 0)


@pytest.mark.parametrize(
    ("relevance", "expected"),
    [
        ([True, False, False], 1.0),  # 1등 -> 1/1
        ([False, True, False], 0.5),  # 2등 -> 1/2
        ([False, False, True], pytest.approx(1 / 3)),  # 3등 -> 1/3
        ([False, False, False], 0.0),  # 없음
        ([], 0.0),  # 검색 결과 없음
        ([True, True, True], 1.0),  # ★ "첫" 정답만 본다 - 여러 개여도 1.0
    ],
)
def test_reciprocal_rank(relevance, expected):
    assert reciprocal_rank(relevance) == expected


def test_hit_and_rr_disagree_on_purpose():
    # ★ 두 지표를 왜 둘 다 보는지를 못 박는 테스트 ★
    # 같은 hit@5(성공)인데 MRR은 5배 차이가 난다. hit@5만 보면 두 설정이 똑같아
    # 보이지만, 아래쪽은 정답이 5등이라 프롬프트 앞부분이 잡음으로 채워진 상태다.
    # M8 리랭킹이 정확히 이 차이를 줄이려고 하는 일이다.
    good = [True, False, False, False, False]
    bad = [False, False, False, False, True]

    assert hit_at_k(good, 5) is hit_at_k(bad, 5) is True
    assert reciprocal_rank(good) == 1.0
    assert reciprocal_rank(bad) == 0.2


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ([1.0, 0.0], 0.5),
        ([0.5], 0.5),
        ([], 0.0),  # 빈 입력은 예외가 아니라 0.0 (해당 종류가 골든셋에 없는 정상 상황)
    ],
)
def test_mean(values, expected):
    assert mean(values) == expected
