# 회귀 게이트 테스트. (M13-d)
#
# ★ 이 파일도 metrics.py와 같은 이유로 존재한다 ★ 게이트는 "이번 변경이 지표를
# 떨어뜨렸는가"를 판정하는 장치다. 게이트가 틀리면 **떨어진 것을 초록으로 통과시키거나,
# 멀쩡한 것을 빨강으로 막는다.** 둘 다 계측기가 아예 없는 것보다 나쁘다 —
# 없으면 사람이 의심이라도 하는데, 틀린 게이트는 의심을 없앤다.
#
# 순수 함수라 API도 DB도 부르지 않는다. CI에서 그대로 돈다.
import json

import pytest

from evals.gate import (
    BaselineNotRecorded,
    Thresholds,
    check,
    config_mismatches,
    format_report,
    load,
    save,
)

# 아래 테스트들이 공유하는 "기록된 기준선". 실제 thresholds.json의 floors와 같은 모양이다.
FLOORS = {
    "normal": {"hit@k": 0.92, "mrr": 0.778},
    "keyword": {"hit@k": 1.00, "mrr": 1.000},
    "overall": {"n": 19, "hit@k": 0.95, "mrr": 0.860},
}


def measured(**overrides) -> dict[str, dict[str, float]]:
    """기준선과 정확히 같은 값에서 출발해, 필요한 것만 덮어쓴다."""
    base = {group: dict(metrics) for group, metrics in FLOORS.items()}
    for group, metrics in overrides.items():
        base.setdefault(group, {}).update(metrics)
    return base


def test_passes_when_every_metric_meets_its_floor():
    assert check(measured(), FLOORS) == []


def test_metric_exactly_at_the_floor_passes():
    # 경계는 통과시킨다. 기준선을 방금 기록한 직후 같은 실행을 돌리면 값이 정확히
    # 같은데, 그때 실패하면 게이트를 아무도 안 믿게 된다.
    assert check(measured(overall={"mrr": 0.860}), FLOORS) == []


def test_flags_a_metric_below_its_floor():
    violations = check(measured(overall={"mrr": 0.700}), FLOORS)

    assert [(v.group, v.metric) for v in violations] == [("overall", "mrr")]
    assert violations[0].measured == 0.700
    assert violations[0].baseline == 0.860


def test_tolerance_absorbs_noise_sized_drops():
    # M10에서 못 박은 규칙: MRR ±0.02는 노이즈다. 그 폭 안의 하락으로 CI를 빨갛게
    # 만들면 개발자가 "또 그거야"라며 게이트를 꺼버린다 — 꺼진 게이트는 없는 게이트다.
    assert check(measured(overall={"mrr": 0.845}), FLOORS, tolerance=0.02) == []

    # 폭을 넘어가면 잡는다.
    assert len(check(measured(overall={"mrr": 0.830}), FLOORS, tolerance=0.02)) == 1


def test_missing_group_is_a_violation_not_a_pass():
    # ★ 이 테스트가 이 파일의 핵심이다 ★ 골든셋에서 keyword 케이스를 전부 지우면
    # 측정 결과에 keyword 그룹이 아예 없어진다. "없으니 비교할 것도 없다"로 넘기면
    # **골든셋을 지우는 것이 게이트를 통과하는 가장 쉬운 방법**이 된다.
    incomplete = measured()
    del incomplete["keyword"]

    violations = check(incomplete, FLOORS)

    assert [(v.group, v.metric) for v in violations] == [
        ("keyword", "hit@k"),
        ("keyword", "mrr"),
    ]
    assert all(v.measured is None for v in violations)


def test_missing_metric_is_a_violation_not_a_pass():
    # thresholds.json에 오타("mrrr")를 내면 측정값에 그 키가 없다. 조용히 넘기면
    # 그 지표는 영영 안 걸린다 — 골든셋 오타가 영원히 0점을 만드는 것과 같은 종류의
    # 조용한 실패다(run_retrieval.validate_dataset이 그걸 막는 이유).
    violations = check(measured(), {"overall": {"mrrr": 0.5}})

    assert len(violations) == 1
    assert violations[0].measured is None


def test_one_kind_can_fail_while_overall_passes():
    # ★ 종류별로 거는 이유 ★ keyword는 7건뿐이라 전멸해도 전체 평균은 멀쩡해 보인다.
    # 전체에만 게이트를 걸면 M8 하이브리드 검색이 통째로 망가져도 CI가 초록이다.
    violations = check(measured(keyword={"mrr": 0.10}), FLOORS)

    assert [(v.group, v.metric) for v in violations] == [("keyword", "mrr")]


def test_groups_without_a_floor_are_not_gated():
    # multiturn은 재작성(LLM)이 있어야 의미가 있어 무료 게이트에서 뺀다.
    # 기준선에 없는 그룹은 측정값이 아무리 나빠도 실패시키지 않는다.
    extra = measured(multiturn={"hit@k": 0.0, "mrr": 0.0})

    assert check(extra, FLOORS) == []


def test_unrecorded_baseline_raises_instead_of_passing():
    # ★ 빈 기준선은 "통과"가 아니라 "고장"이다 ★ floors가 없는데 0건 위반으로
    # 초록을 주면, 한 번도 보정한 적 없는 게이트가 영원히 초록을 낸다.
    # M11에서 "조용한 200"을 금지한 것과 정확히 같은 판단이다.
    with pytest.raises(BaselineNotRecorded):
        check(measured(), None)


def test_config_mismatch_is_reported():
    # top_k를 20으로 올리면 hit@k는 당연히 올라간다. 기준선이 k=5에서 기록됐는데
    # k=20으로 측정한 값과 비교하면, 게이트는 "개선됐다"고 말하면서 아무것도 안 지킨다.
    problems = config_mismatches({"store": "qdrant", "top_k": 20}, {"store": "qdrant", "top_k": 5})

    assert len(problems) == 1
    assert "top_k" in problems[0]

    assert config_mismatches({"store": "qdrant", "top_k": 5}, {"store": "qdrant", "top_k": 5}) == []


def test_report_shows_numbers_and_marks_failures():
    violations = check(measured(keyword={"mrr": 0.10}), FLOORS)

    report = format_report(measured(keyword={"mrr": 0.10}), FLOORS, 0.02, violations)

    assert "keyword" in report
    assert "0.100" in report  # 측정값
    assert "0.778" in report  # 다른 그룹의 기준선도 함께 찍힌다(실패한 줄만 찍지 않는다)
    assert "✗" in report


def test_report_formats_numbers_the_same_way_everywhere():
    # 표와 실패 상세가 같은 숫자를 다르게 찍으면(19 vs 19.000) 두 줄이 서로 다른
    # 값처럼 읽힌다. 포맷은 한 군데(_number)에서만 정한다.
    violations = check({"overall": {"n": 12}}, {"overall": {"n": 19}})

    report = format_report({"overall": {"n": 12}}, {"overall": {"n": 19}}, 0.0, violations)

    assert "19.000" not in report
    assert "12.000" not in report


def test_report_shows_counts_as_whole_numbers():
    # n은 "19.000건"이 아니라 "19건"이다. 리포트는 사람이 읽는 문서라, 단위가 없는
    # 숫자에 소수점 셋째 자리가 붙으면 눈이 한 번 더 멈춘다.
    report = format_report({"overall": {"n": 19}}, {"overall": {"n": 19}}, 0.02, [])

    assert "| 19 |" in report
    assert "19.000" not in report


def test_load_reads_config_tolerance_and_floors(tmp_path):
    path = tmp_path / "thresholds.json"
    path.write_text(
        json.dumps({"config": {"top_k": 5}, "tolerance": 0.02, "floors": FLOORS}),
        encoding="utf-8",
    )

    thresholds = load(path)

    assert thresholds.config == {"top_k": 5}
    assert thresholds.tolerance == 0.02
    assert thresholds.floors == FLOORS


def test_recorded_date_is_metadata_not_config(tmp_path):
    # ★ 실제로 밟은 함정이다 ★ 기록일을 config 안에 넣었더니 config_mismatches가
    # "recorded: 기준선='2026-09-14' · 이번 실행=None"으로 **매 실행마다** 걸렸다.
    # 게이트가 항상 빨간불이면 사람들은 게이트를 끈다. 설정(비교 대상)과
    # 메타데이터(기록용)는 같은 자루에 담으면 안 된다.
    path = tmp_path / "thresholds.json"
    save(
        Thresholds(config={"top_k": 5}, tolerance=0.02, floors=FLOORS, recorded="2026-09-14"),
        path,
    )

    loaded = load(path)

    assert loaded.config == {"top_k": 5}
    assert loaded.recorded == "2026-09-14"
    assert config_mismatches({"top_k": 5}, loaded.config) == []


def test_load_accepts_an_unrecorded_baseline(tmp_path):
    # 기준선을 아직 안 기록한 상태도 **유효한 파일**이다. 읽기는 성공하고,
    # 실패는 check()에서 난다 — "파일이 깨졌다"와 "아직 안 쟀다"는 다른 사건이다.
    path = tmp_path / "thresholds.json"
    path.write_text(json.dumps({"config": {}, "tolerance": 0.02, "floors": None}), encoding="utf-8")

    assert load(path).floors is None
