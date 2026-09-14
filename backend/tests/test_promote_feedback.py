# 👎 → 골든셋 편입 절차 테스트. (M13-d)
#
# ★ Langfuse를 부르지 않는다 ★ 대역 클라이언트를 넣어 "우리가 응답을 어떻게 읽는가"만 본다.
# conftest의 _langfuse_off가 실제 전송을 막고 있기도 하지만, 그 앞에 이 설계가 있다:
# 네트워크를 타는 부분(fetch)과 해석하는 부분(extract/select/draft)을 나눠두면
# 해석 규칙을 키 없이도 전부 검증할 수 있다.
#
# ★ 이 파일에서 가장 중요한 테스트는 맨 아래 test_draft_rows_are_rejected... 이다 ★
# 초안이 골든셋 검증을 **통과하면 안 된다**는 것이 이 절차의 안전장치다.
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from evals.promote_feedback import (
    Downvote,
    extract_answer,
    extract_question,
    fetch_downvotes,
    select_new,
    to_draft,
)
from evals.run_retrieval import Case, validate_dataset

NOW = datetime(2026, 9, 14, 10, 0, tzinfo=UTC)


# --- 트레이스에서 질문/답 꺼내기 ------------------------------------------------


def test_extract_question_reads_the_graph_input():
    # chat.py가 그래프에 넣는 모양 그대로다 (app/api/routes/chat.py:110).
    trace_input = {
        "messages": [{"role": "user", "content": "파이썬 버전 어떻게 관리해?"}],
        "principal": {"tenant_id": "default"},
    }

    assert extract_question(trace_input) == "파이썬 버전 어떻게 관리해?"


def test_extract_question_handles_content_parts():
    # Anthropic/LangChain은 content를 문자열이 아니라 파트 리스트로 두기도 한다.
    # 문자열만 가정하면 여기서 조용히 None이 되어 "피드백은 있는데 질문이 없다"가 된다.
    trace_input = {"messages": [{"role": "user", "content": [{"type": "text", "text": "안녕"}]}]}

    assert extract_question(trace_input) == "안녕"


def test_extract_question_takes_the_last_user_turn():
    trace_input = {
        "messages": [
            {"role": "user", "content": "첫 질문"},
            {"role": "assistant", "content": "답"},
            {"role": "human", "content": "그거 프로덕션에서는?"},
        ]
    }

    assert extract_question(trace_input) == "그거 프로덕션에서는?"


def test_extract_question_returns_none_for_an_unknown_shape():
    # ★ 추측해서 문자열을 만들지 않는다 ★ str(trace_input)으로 때우면 골든셋에
    # {"messages": [...]} 같은 쓰레기 질문이 들어간다. None이면 리포트에 "질문을
    # 못 읽었다"로 남아 사람이 트레이스를 열어본다.
    assert extract_question({"foo": "bar"}) is None
    assert extract_question(None) is None
    assert extract_question("그냥 문자열") is None


def test_extract_answer_reads_the_graph_output():
    assert extract_answer({"messages": [{"role": "assistant", "content": "그건 이렇다"}]}) == (
        "그건 이렇다"
    )


# --- Langfuse에서 👎만 골라오기 --------------------------------------------------


def fake_score(score_id: str, trace_id: str, value: bool) -> SimpleNamespace:
    return SimpleNamespace(
        id=score_id,
        value=value,
        comment=None,
        timestamp=NOW,
        subject=SimpleNamespace(kind="trace", id=trace_id),
    )


def fake_client(pages: list[list[SimpleNamespace]], traces: dict) -> SimpleNamespace:
    """scores_v3.get_many_v3와 trace.get만 흉내 내는 대역."""
    calls = {"cursors": []}

    def get_many_v3(*, cursor=None, **kwargs):
        calls["cursors"].append(cursor)
        index = 0 if cursor is None else int(cursor)
        is_last = index == len(pages) - 1
        return SimpleNamespace(
            data=pages[index],
            meta=SimpleNamespace(cursor=None if is_last else str(index + 1)),
        )

    def get_trace(trace_id, **kwargs):
        return traces[trace_id]

    client = SimpleNamespace(
        api=SimpleNamespace(
            scores_v3=SimpleNamespace(get_many_v3=get_many_v3),
            trace=SimpleNamespace(get=get_trace),
        )
    )
    client.calls = calls
    return client


def fake_trace(question: str, answer: str) -> SimpleNamespace:
    return SimpleNamespace(
        input={"messages": [{"role": "user", "content": question}]},
        output={"messages": [{"role": "assistant", "content": answer}]},
        html_path="/project/p1/traces/t1",
    )


def test_keeps_only_thumbs_down():
    # 👍도 같은 이름(user-feedback)의 score다. 값으로 걸러야 한다 —
    # 안 그러면 "만족한 대화"가 회귀 테스트 후보로 올라온다.
    client = fake_client(
        [[fake_score("s1", "t1", False), fake_score("s2", "t2", True)]],
        {"t1": fake_trace("나쁜 답을 받은 질문", "나쁜 답")},
    )

    downvotes = fetch_downvotes(client)

    assert [d.trace_id for d in downvotes] == ["t1"]
    assert downvotes[0].question == "나쁜 답을 받은 질문"


def test_follows_the_cursor_to_the_last_page():
    # ★ 페이지네이션을 빼먹으면 조용히 첫 페이지만 본다 ★ 에러가 안 나기 때문에
    # "👎가 별로 없네"로 넘어가고, 절차 전체가 반쪽만 돈다.
    client = fake_client(
        [[fake_score("s1", "t1", False)], [fake_score("s2", "t2", False)]],
        {"t1": fake_trace("질문1", "답1"), "t2": fake_trace("질문2", "답2")},
    )

    downvotes = fetch_downvotes(client)

    assert [d.trace_id for d in downvotes] == ["t1", "t2"]
    assert client.calls["cursors"] == [None, "1"]


def test_survives_a_trace_that_cannot_be_read():
    # 트레이스가 지워졌거나 보존 기간이 지났을 수 있다. 한 건 때문에 절차 전체가
    # 죽으면 "그냥 안 돌린다"가 된다 — 건너뛰되 질문을 None으로 남겨 눈에 띄게 한다.
    def exploding_get(trace_id, **kwargs):
        raise RuntimeError("404")

    client = fake_client([[fake_score("s1", "t1", False)]], {})
    client.api.trace.get = exploding_get

    downvotes = fetch_downvotes(client)

    assert len(downvotes) == 1
    assert downvotes[0].question is None


# --- 골든셋과 대조 ---------------------------------------------------------------


def downvote(question: str | None, trace_id: str = "t1") -> Downvote:
    return Downvote(
        trace_id=trace_id,
        question=question,
        answer="답",
        comment=None,
        timestamp=NOW,
        html_path="/project/p1/traces/t1",
    )


def test_skips_questions_already_in_the_golden_set():
    known = [
        Case("n01", "normal", "파이썬 버전은 어떻게 관리해?", ["CLAUDE.md"], [".python-version"])
    ]

    # 공백과 대소문자만 다른 같은 질문은 같은 질문으로 본다.
    assert select_new([downvote("  파이썬 버전은   어떻게 관리해? ")], known) == []


def test_collapses_repeated_downvotes_of_the_same_question():
    # 같은 질문이 세 번 👎를 받았다고 골든셋에 세 줄이 들어가면 안 된다.
    votes = [downvote("같은 질문", "t1"), downvote("같은 질문", "t2"), downvote("다른 질문", "t3")]

    assert [d.question for d in select_new(votes, [])] == ["같은 질문", "다른 질문"]


def test_keeps_downvotes_whose_question_could_not_be_read():
    # 질문을 못 읽은 건은 "중복인지 아닌지"를 판단할 수 없다. 버리면 영영 안 보이므로
    # 남겨서 사람이 트레이스를 열어보게 한다.
    assert len(select_new([downvote(None)], [])) == 1


# --- 초안 행 --------------------------------------------------------------------


def test_draft_carries_the_trace_link_for_review():
    row = to_draft(downvote("왜 이렇게 답했지?"), index=1, host="https://cloud.langfuse.com")

    assert row["question"] == "왜 이렇게 답했지?"
    assert row["_review"]["trace_url"] == "https://cloud.langfuse.com/project/p1/traces/t1"
    assert row["_review"]["answer"] == "답"


def test_draft_rows_are_rejected_by_the_golden_set_validator():
    # ★ 이 절차의 안전장치다 ★ 초안을 그대로 dataset.jsonl에 붙여넣으면
    # validate_dataset이 시끄럽게 죽어야 한다. 통과해버리면 정답이 비어 있는 케이스가
    # 골든셋에 섞여 **영원히 0점**이 되고, 그 뒤 모든 지표가 조용히 낮아진다.
    row = to_draft(downvote("검토 안 한 질문"), index=1, host="https://cloud.langfuse.com")

    case = Case(
        id=row["id"],
        kind=row["kind"],
        question=row["question"],
        expected_sources=row["expected_sources"],
        expected_substrings=row["expected_substrings"],
    )

    with pytest.raises(SystemExit):
        validate_dataset([case])
