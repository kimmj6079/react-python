# 회귀 게이트: 이번 실행의 지표를 "기록된 기준선"과 비교해 통과/실패를 가른다. (M13-d)
#
# ★ 왜 별도 파일인가 ★ run_retrieval.py는 검색을 돌리고 표를 그린다. 그 안에
# 임계값 비교를 섞으면 "측정"과 "판정"이 한 함수에 붙어서, 판정 규칙을 테스트하려면
# 임베딩 모델을 띄워야 한다. metrics.py가 "무엇이 정답인가"와 "어떻게 점수 매기나"를
# 나눈 것과 정확히 같은 분리이고, 그래서 이 파일은 API도 DB도 모른다.
#
# ★ 이 파일이 지키는 것은 숫자가 아니라 "규율"이다 ★
# M7~M13은 전부 "개선"이었고, 각 단계마다 M6 하네스로 before/after를 쟀다. 그런데
# 그 측정은 **사람이 기억할 때만** 돌아간다. 3개월 뒤 청킹 상수를 한 줄 고치는 사람은
# BASELINE-M7.md를 읽지 않는다. 게이트는 그 규율을 사람의 기억에서 CI로 옮기는 장치다.
from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

EVALS_DIR = Path(__file__).resolve().parent
THRESHOLDS = EVALS_DIR / "thresholds.json"


class BaselineNotRecorded(RuntimeError):
    """기준선이 아직 기록되지 않았다.

    ★ 이것을 "통과"로 처리하면 안 된다 ★ floors가 비어 있으면 비교할 것이 없으니
    위반도 0건이고, 그대로 두면 **한 번도 보정한 적 없는 게이트가 영원히 초록을 낸다.**
    저울을 사서 영점을 안 맞춰놓고 "0kg이 나오니 정상"이라고 말하는 것과 같다.
    M11에서 인입 실패에 200을 주는 것을 금지한 것과 같은 종류의 판단이다.
    """


@dataclass(frozen=True)
class Violation:
    """기준선을 못 넘긴 지표 하나.

    measured가 None이면 "나빠졌다"가 아니라 **"재지 못했다"** 는 뜻이다(그룹이
    통째로 없거나, 기준선 파일의 지표 이름에 오타가 있거나). 둘을 같은 타입으로
    표현하되 리포트에서 다르게 찍는다 — 원인이 다르면 고치는 법도 다르기 때문이다.
    """

    group: str
    metric: str
    measured: float | None
    baseline: float
    floor: float


@dataclass(frozen=True)
class Thresholds:
    """thresholds.json을 그대로 담는 값 객체.

    ★ config와 recorded를 나눠 둔 것이 실수로 배운 설계다 ★ 기록일을 처음에는
    config 안에 넣었는데, config는 **매 실행 비교되는 값**이라 `config_mismatches`가
    "recorded: 기준선='2026-09-14' · 이번 실행=None"으로 항상 걸렸다. 게이트가 늘
    빨간불이면 사람들은 게이트를 끈다. **비교 대상(config)과 기록용 메타데이터
    (recorded)는 같은 자루에 담으면 안 된다.**
    """

    config: dict
    tolerance: float
    floors: dict[str, dict[str, float]] | None
    recorded: str | None = None


def load(path: Path = THRESHOLDS) -> Thresholds:
    """기준선 파일을 읽는다. floors가 null이어도 **정상적인 파일**이다.

    ★ "파일이 깨졌다"와 "아직 안 쟀다"를 구분한다 ★ 여기서 둘을 같이 죽이면,
    기준선을 기록하려고 --write-baseline을 돌리는 순간 파일을 못 읽어서 실패한다.
    읽기는 성공시키고, 실패는 check()에서 낸다.
    """
    if not path.is_file():
        raise SystemExit(f"기준선 파일이 없다: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    return Thresholds(
        config=raw.get("config") or {},
        tolerance=float(raw.get("tolerance") or 0.0),
        floors=raw.get("floors"),
        recorded=raw.get("recorded"),
    )


def save(thresholds: Thresholds, path: Path = THRESHOLDS) -> None:
    """기준선 파일을 쓴다. 사람이 읽고 리뷰할 파일이라 들여쓰기를 준다.

    ★ 이 파일은 반드시 git에 커밋된다 ★ 기준선을 바꾸는 것은 "이 정도면 됐다"는
    판단이고, 그 판단은 코드 변경과 똑같이 리뷰를 거쳐야 한다. 파일이 아니라
    환경변수나 CI 설정 화면에 두면 그 판단이 기록에서 사라진다.
    """
    path.write_text(
        json.dumps(
            {
                "recorded": thresholds.recorded,
                "config": thresholds.config,
                "tolerance": thresholds.tolerance,
                "floors": thresholds.floors,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def config_mismatches(measured: Mapping, recorded: Mapping) -> list[str]:
    """측정 설정이 기준선을 기록할 때의 설정과 같은지 본다.

    ★ 설정이 다르면 비교 자체가 무의미하다 ★ top_k를 5에서 20으로 올리면 hit@k는
    거의 무조건 올라간다. 기준선이 k=5인데 k=20으로 측정하면 게이트는 초록을 내면서
    **아무것도 지키지 않는다.** 이건 "게이트가 없는 것"보다 나쁘다 — 없으면 사람이
    의심이라도 하는데, 잘못된 초록은 의심을 없앤다.

    기록된 키만 본다. 기준선에 없는 키는 그때 신경 쓰지 않기로 한 값이다.
    """
    problems = []
    for key, expected in recorded.items():
        actual = measured.get(key)
        if actual != expected:
            problems.append(f"{key}: 기준선={expected!r} · 이번 실행={actual!r}")
    return problems


def check(
    measured: Mapping[str, Mapping[str, float]],
    floors: Mapping[str, Mapping[str, float]] | None,
    tolerance: float = 0.0,
) -> list[Violation]:
    """기록된 기준선을 못 넘긴 지표를 전부 돌려준다. 빈 리스트 = 통과.

    ★ 기준선이 권위를 갖는다(측정값이 아니라) ★ 순회 대상이 floors인 것이 이 함수의
    핵심 결정이다. 측정값을 순회하면 **골든셋에서 케이스를 지우는 것이 게이트를
    통과하는 가장 쉬운 방법**이 된다 — 그룹이 사라지면 비교도 사라지니까.
    floors를 순회하면 사라진 그룹이 measured=None인 위반으로 남는다.

    ★ tolerance는 노이즈 폭이다 ★ M10에서 "MRR ±0.02는 노이즈"라고 못 박았고,
    13-b에서 지연은 20~30%가 노이즈라고 정했다. 노이즈 폭 안의 하락으로 빨간불을
    내면 개발자가 게이트를 꺼버린다 — **꺼진 게이트는 없는 게이트다.**
    반대로 폭을 너무 키우면 진짜 회귀를 놓치므로, 폭 자체를 파일에 적어 리뷰 대상으로 둔다.
    """
    if floors is None:
        raise BaselineNotRecorded(
            "기준선이 기록되지 않았다. 먼저 실제 실행으로 기록한다:\n"
            "  uv run python -m evals.run_retrieval --write-baseline"
        )

    violations: list[Violation] = []
    for group, metrics in floors.items():
        for metric, baseline in metrics.items():
            floor = baseline - tolerance
            value = (measured.get(group) or {}).get(metric)
            if value is None or value < floor:
                violations.append(
                    Violation(
                        group=group,
                        metric=metric,
                        measured=value,
                        baseline=float(baseline),
                        floor=floor,
                    )
                )
    return violations


def _number(value: float) -> str:
    """지표는 소수 셋째 자리까지, 건수(n)는 정수로.

    사소해 보이지만 리포트는 **몇 주 뒤에 사람이 읽는 문서**다. "19.000건"은 눈을 한 번
    멈추게 하고, 멈추는 지점이 쌓이면 아무도 표를 끝까지 안 읽는다.
    n에 허용폭(0.02)을 뺀 하한은 18.98이라 소수로 나오는데, 그건 의도한 대로다 —
    카운트에 노이즈 폭을 적용하면 사실상 "정확히 일치"가 된다.
    """
    return str(int(value)) if float(value).is_integer() else f"{value:.3f}"


def format_report(
    measured: Mapping[str, Mapping[str, float]],
    floors: Mapping[str, Mapping[str, float]] | None,
    tolerance: float,
    violations: list[Violation],
) -> str:
    """통과/실패를 한 표로. ★ 실패한 줄만 찍지 않는다 ★

    실패만 찍으면 통과했을 때 화면이 비어서 "게이트가 돌긴 했나"를 알 수 없다.
    CI 로그는 몇 주 뒤에 읽히는 문서이기도 하므로, 그때 무엇을 어떤 기준으로
    비교했는지가 그 로그 안에 다 있어야 한다.
    """
    failed = {(v.group, v.metric) for v in violations}
    lines = [
        f"## 회귀 게이트 (노이즈 허용폭 ±{tolerance})",
        "",
        "| 그룹 | 지표 | 이번 실행 | 기준선 | 하한 | |",
        "|---|---|---:|---:|---:|---|",
    ]
    for group, metrics in (floors or {}).items():
        for metric, baseline in metrics.items():
            value = (measured.get(group) or {}).get(metric)
            shown = "측정 안 됨" if value is None else _number(value)
            mark = "✗" if (group, metric) in failed else "✓"
            lines.append(
                f"| {group} | {metric} | {shown} | {_number(baseline)} "
                f"| {_number(baseline - tolerance)} | {mark} |"
            )
    lines.append("")
    if violations:
        lines.append(f"**실패: {len(violations)}건**")
        for v in violations:
            if v.measured is None:
                # 원인이 다르면 고치는 법도 다르다. "나빠졌다"가 아니라 "사라졌다"이므로
                # 코드가 아니라 골든셋이나 기준선 파일을 봐야 한다.
                lines.append(
                    f"- `{v.group}.{v.metric}` — **측정값이 없다.** "
                    "골든셋에서 케이스가 사라졌거나 기준선 파일의 지표 이름이 틀렸다."
                )
            else:
                lines.append(
                    f"- `{v.group}.{v.metric}` — {_number(v.measured)} < {_number(v.floor)} "
                    f"(기준선 {_number(v.baseline)} − 허용폭 {tolerance})"
                )
    else:
        lines.append("**통과** — 기록된 기준선을 모두 넘겼다.")
    return "\n".join(lines)
