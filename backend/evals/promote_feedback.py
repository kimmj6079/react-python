# 👎가 붙은 대화를 골든셋 편입 후보로 뽑아낸다. (M13-d)
#
# 실행 (backend/에서):
#   uv run python -m evals.promote_feedback                 # 최근 30일
#   uv run python -m evals.promote_feedback --days 7
#   uv run python -m evals.promote_feedback --out ../drafts.jsonl
#
# ★ 로드맵이 원형으로 닫히는 마지막 한 칸이다 ★
# M4가 "무슨 일이 있었는가"(트레이스)를 남겼고, M6이 "얼마나 잘하는가"(골든셋)를 쟀고,
# 13-a가 "사용자가 이 답을 어떻게 봤는가"(👍/👎)를 붙였다. 그런데 **셋이 이어져 있지
# 않으면 각각은 그냥 데이터다.** 이 스크립트가 👎 → 골든셋의 화살표를 만든다.
# 그 화살표가 생기는 순간 회귀 테스트가 내가 상상한 질문이 아니라 **실제로 실패한
# 질문**에 대해 돌기 시작하고, 골든셋이 스스로 자란다.
#
# ★★ 자동으로 dataset.jsonl에 쓰지 않는다 ★★
# 가장 하고 싶어지는 일이고, 하면 안 되는 일이다. 이유 세 가지:
#   1. 골든셋은 **자(尺)** 다. 자가 스스로 늘어나면 어제 잰 값과 오늘 잰 값을 비교할 수
#      없다. M6을 만든 이유가 그 비교였다.
#   2. 정답(expected_substrings)은 사람이 문서를 읽고 정해야 한다. 모델이 정하면
#      "모델이 낸 답을 모델이 채점하는" 구조가 되어 지표가 거짓말을 시작한다.
#   3. 👎는 "검색이 틀렸다"일 수도 "말투가 마음에 안 든다"일 수도 있다. 후자를
#      검색 골든셋에 넣으면 영원히 못 맞히는 케이스가 생긴다.
# 그래서 이 스크립트는 **받은편지함(inbox)** 만 만든다. 마이그레이션을 컨테이너 시작 시
# 자동 실행하지 않는 것과 정확히 같은 판단이다 — 되돌리기 어려운 변경은 명시적 단계로 둔다.
import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.core.config import settings
from app.core.tracing import FEEDBACK_SCORE_NAME, get_langfuse_client
from evals.run_retrieval import Case, load_dataset

EVALS_DIR = Path(__file__).resolve().parent
INBOX_DIR = EVALS_DIR / "inbox"

# 한 번에 가져올 score 수. 무료 티어에서 페이지가 커봐야 손해가 없고,
# 작으면 왕복만 늘어난다.
PAGE_SIZE = 100


@dataclass(frozen=True)
class Downvote:
    """👎 하나와 그 대화의 내용.

    question이 None이면 "👎는 있는데 질문을 못 읽었다"는 뜻이다. 버리지 않는다 —
    버리면 그 실패가 영영 안 보인다.
    """

    trace_id: str
    question: str | None
    answer: str | None
    comment: str | None
    timestamp: datetime | None
    html_path: str | None


# ---------------------------------------------------------------------------
# 트레이스 해석 — 네트워크를 모르는 순수 함수들
# ---------------------------------------------------------------------------


def _content_to_text(content) -> str | None:
    """LangChain/Anthropic의 content를 문자열로. 파트 리스트도 받는다.

    ★ 문자열만 가정하면 조용히 실패한다 ★ content는 `"안녕"` 일 수도
    `[{"type": "text", "text": "안녕"}]` 일 수도 있다(모델·버전에 따라). 후자를
    못 읽으면 에러가 아니라 **질문이 없는 피드백**이 쌓인다.
    """
    if isinstance(content, str):
        return content or None
    if isinstance(content, list):
        parts = [
            part.get("text")
            for part in content
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        ]
        joined = "".join(p for p in parts if p)
        return joined or None
    return None


def _last_message_text(payload, roles: set[str]) -> str | None:
    """messages 리스트에서 뒤에서부터 해당 역할의 첫 발화를 찾는다."""
    if isinstance(payload, dict):
        messages = payload.get("messages")
    elif isinstance(payload, list):
        messages = payload
    else:
        return None

    if not isinstance(messages, list):
        return None

    for message in reversed(messages):
        if not isinstance(message, dict):
            continue
        # LangChain은 직렬화 방식에 따라 "role" 또는 "type"을 쓴다. 둘 다 본다.
        role = message.get("role") or message.get("type")
        if role in roles:
            text = _content_to_text(message.get("content"))
            if text:
                return text
    return None


def extract_question(trace_input) -> str | None:
    """트레이스 입력에서 사용자 질문을 꺼낸다. 모르는 모양이면 None.

    ★ 추측해서 문자열을 만들지 않는다 ★ `str(trace_input)`으로 때우면 골든셋 후보에
    `{'messages': [...]}` 같은 것이 들어간다. None이면 리포트에 "질문을 못 읽었다"로
    남고 사람이 트레이스를 연다 — **조용히 틀린 값보다 시끄러운 빈 값이 낫다.**
    """
    return _last_message_text(trace_input, {"user", "human"})


def extract_answer(trace_output) -> str | None:
    """트레이스 출력에서 모델 답변을 꺼낸다."""
    text = _last_message_text(trace_output, {"assistant", "ai"})
    if text:
        return text
    # 그래프 출력이 messages가 아니라 문자열 하나일 수도 있다.
    return trace_output if isinstance(trace_output, str) and trace_output else None


def normalize(question: str) -> str:
    """중복 판정용 정규화. 공백을 접고 대소문자를 없앤다.

    ★ 일부러 여기까지만 한다 ★ 물음표를 떼거나 조사를 정규화하면 서로 다른 질문이
    합쳐질 수 있다. 중복을 놓치는 쪽(초안이 한 줄 더 생긴다)이 서로 다른 질문을
    합치는 쪽(실패 사례를 잃는다)보다 훨씬 싸다.
    """
    return re.sub(r"\s+", " ", question).strip().casefold()


def select_new(downvotes: list[Downvote], known: list[Case]) -> list[Downvote]:
    """이미 골든셋에 있는 질문과 서로 중복인 질문을 걸러낸다. 순서는 유지한다."""
    seen = {normalize(case.question) for case in known}
    selected: list[Downvote] = []
    for vote in downvotes:
        if vote.question is None:
            # 중복 여부를 판단할 수 없다. 사람이 보게 남긴다.
            selected.append(vote)
            continue
        key = normalize(vote.question)
        if key in seen:
            continue
        seen.add(key)
        selected.append(vote)
    return selected


def to_draft(vote: Downvote, *, index: int, host: str) -> dict:
    """골든셋 초안 한 줄. ★ 일부러 "그대로 쓰면 실패하는" 모양이다 ★

    id와 kind에 `TODO`가 박혀 있고 정답이 비어 있다. 이 줄을 그대로 dataset.jsonl에
    붙여넣으면 run_retrieval.validate_dataset이 "모르는 kind" + "정답이 비어 있다"로
    죽는다. 즉 **검토를 건너뛴 편입은 구조적으로 불가능하다** —
    tests/test_promote_feedback.py가 그 성질을 못 박는다.

    `_review`는 골든셋 스키마에 없는 필드다. 사람이 판단할 때 필요한 것(그때 무슨 답을
    했는가, 트레이스 링크)을 담고, 편입할 때 통째로 지운다.
    """
    return {
        "id": f"TODO-f{index:02d}",
        "kind": "TODO",
        "question": vote.question or "",
        "expected_sources": [],
        "expected_substrings": [],
        "expected_answer": "",
        "_review": {
            "trace_id": vote.trace_id,
            "trace_url": f"{host.rstrip('/')}{vote.html_path}" if vote.html_path else None,
            "downvoted_at": vote.timestamp.isoformat() if vote.timestamp else None,
            "comment": vote.comment,
            "answer": vote.answer,
        },
    }


# ---------------------------------------------------------------------------
# Langfuse에서 가져오기 — 여기만 네트워크를 탄다
# ---------------------------------------------------------------------------


def _trace_id_of(score) -> str | None:
    """score가 어느 트레이스에 붙었는지.

    ★ v4에서 모양이 바뀐 자리다 ★ 예전 score에는 `traceId`가 평평하게 있었는데,
    v3 API의 ScoreV3는 `subject: {kind: "trace", id: ...}`로 감쌌다(실측:
    langfuse/api/scores_v3/types/score_subject_v3.py). 둘 다 받아두면 SDK를
    올릴 때 이 스크립트가 조용히 빈 결과를 내지 않는다.
    """
    subject = getattr(score, "subject", None)
    if subject is not None and getattr(subject, "kind", None) == "trace":
        return getattr(subject, "id", None)
    return getattr(score, "trace_id", None)


def fetch_downvotes(client, *, since: datetime | None = None, page_size: int = PAGE_SIZE):
    """👎 score를 전부 가져와 그 대화 내용까지 붙인다.

    ★ 커서를 끝까지 따라간다 ★ 페이지네이션을 빼먹으면 **에러 없이 첫 페이지만** 본다.
    그러면 "👎가 별로 없네"로 넘어가고 절차 전체가 반쪽만 돈다. 조용한 실패라
    테스트로 못 박아뒀다(test_follows_the_cursor_to_the_last_page).

    ★ 값 필터를 서버가 아니라 여기서 한다 ★ get_many_v3에 value=0을 줄 수도 있지만,
    BOOLEAN score의 value는 SDK 버전에 따라 bool/float이 오간다. 서버 필터가 조용히
    0건을 돌려주는 것보다, 다 받아서 우리가 거르는 편이 안전하다(수백 건 규모라 싸다).
    """
    downvotes: list[Downvote] = []
    cursor: str | None = None
    while True:
        page = client.api.scores_v3.get_many_v3(
            name=FEEDBACK_SCORE_NAME,
            from_timestamp=since,
            limit=page_size,
            cursor=cursor,
        )
        for score in page.data:
            if getattr(score, "value", None):  # True/1 = 👍
                continue
            trace_id = _trace_id_of(score)
            if not trace_id:
                continue
            downvotes.append(_with_trace(client, score, trace_id))

        cursor = getattr(page.meta, "cursor", None)
        if not cursor:
            return downvotes


def _with_trace(client, score, trace_id: str) -> Downvote:
    """트레이스를 읽어 질문·답을 채운다. 못 읽어도 👎 자체는 남긴다.

    ★ 한 건의 실패로 전체를 죽이지 않는다 ★ 트레이스는 보존 기간이 지나 사라질 수
    있다. 그때 스크립트가 예외로 죽으면 사람은 "이거 안 되네" 하고 다시는 안 돌린다 —
    **절차는 돌아가지 않으면 없는 것과 같다.**
    """
    try:
        trace = client.api.trace.get(trace_id)
    except Exception as exc:  # noqa: BLE001 - SDK가 어떤 예외를 던지든 절차는 계속된다
        print(f"  ! 트레이스를 못 읽었다 ({trace_id}): {exc}", file=sys.stderr)
        return Downvote(
            trace_id=trace_id,
            question=None,
            answer=None,
            comment=getattr(score, "comment", None),
            timestamp=getattr(score, "timestamp", None),
            html_path=None,
        )
    return Downvote(
        trace_id=trace_id,
        question=extract_question(getattr(trace, "input", None)),
        answer=extract_answer(getattr(trace, "output", None)),
        comment=getattr(score, "comment", None),
        timestamp=getattr(score, "timestamp", None),
        html_path=getattr(trace, "html_path", None),
    )


# ---------------------------------------------------------------------------


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="👎 대화를 골든셋 편입 후보로 뽑는다 (M13-d)")
    parser.add_argument("--days", type=int, default=30, help="최근 며칠 (기본 30)")
    parser.add_argument(
        "--out", default=None, help="초안 파일 경로 (기본: evals/inbox/<날짜>.jsonl)"
    )
    args = parser.parse_args()

    if not settings.langfuse_enabled:
        raise SystemExit("LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY가 필요하다 (backend/.env)")

    since = datetime.now(UTC) - timedelta(days=args.days)
    client = get_langfuse_client()

    print(f"👎 조회: 최근 {args.days}일 (score 이름 = {FEEDBACK_SCORE_NAME})")
    downvotes = fetch_downvotes(client, since=since)
    print(f"  받은 👎: {len(downvotes)}건")

    known = load_dataset()
    new = select_new(downvotes, known)
    print(f"  골든셋에 없는 질문: {len(new)}건 (골든셋 {len(known)}건과 대조)")

    if not new:
        print("\n편입할 후보가 없다. (좋은 소식이거나, 아직 👎가 안 쌓였거나)")
        return

    out = Path(args.out) if args.out else INBOX_DIR / f"{datetime.now():%Y%m%d}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = [to_draft(v, index=i, host=settings.langfuse_host) for i, v in enumerate(new, start=1)]
    out.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8"
    )

    print(f"\n초안 {len(rows)}건 → {out}")
    print("\n다음 할 일 (사람이 한다):")
    print("  1. 각 줄의 _review.trace_url을 열어 무엇이 잘못됐는지 본다")
    print("  2. kind를 normal|keyword|unanswerable|multiturn 중 하나로 고친다")
    print("  3. expected_sources / expected_substrings를 문서에서 직접 찾아 채운다")
    print("  4. id를 n13·k08처럼 다음 번호로 바꾸고 _review를 지운다")
    print("  5. evals/dataset.jsonl에 붙인 뒤 --write-baseline으로 기준선을 다시 기록한다")
    print("     (골든셋이 커지면 예전 기준선과는 비교 대상이 달라진다)")


if __name__ == "__main__":
    main()
