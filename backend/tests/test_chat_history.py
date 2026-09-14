# 대화 복원 테스트. (M5-3)
#
# ★ 왜 이 기능이 M5-2 다음인가 ★ M5-2에서 대화가 Postgres에 남게 됐는데,
# **화면은 그 사실을 전혀 모른다.** 새로고침하면 브라우저 메모리가 비고, 그러면
# 서버에 멀쩡히 있는 대화가 사용자에게는 사라진 것과 똑같다.
# "데이터를 durable하게 만드는 것"과 "사용자가 그 durability를 체감하는 것"은 다른 일이고,
# 후자를 안 하면 전자는 **아무도 모르는 개선**이 된다.
#
# 여기서 검증하는 것 두 가지:
#   1. LangChain 메시지 → AI SDK UIMessage 변환이 맞는가 (순수 함수)
#   2. GET /chat/{id}/messages가 체크포인터를 읽어 그걸 돌려주는가 (라우터)
import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver

from app.api.deps import get_graph
from app.core.ai_sdk import to_ui_messages
from app.graph import build_graph
from app.main import app
from app.rag.base import RetrievedChunk
from tests.test_chat import FakeChatModel, _msg, _wire


@pytest.fixture
def chat_graph():
    """가짜 모델 + 빈 체크포인터로 만든 그래프를 주입한다.

    ★ test_chat.py의 fake_graph를 import해 오지 않았다 ★ pytest의 fixture는 이름으로
    찾는 물건이라 import해도 ruff가 "재정의"로 보고(F811), 무엇보다 **그 fixture가
    test_chat.py의 전역 CALLS를 비우는 부수효과까지 들고 온다.** 이 파일은 그 전역을
    쓰지 않으므로, 필요한 것만 다섯 줄로 다시 만드는 편이 의존을 줄인다.
    체크포인터를 fixture 안에서 만드는 이유는 test_chat.py와 같다 — 모듈 레벨에 두면
    테스트끼리 대화 상태가 샌다.
    """
    graph = build_graph(FakeChatModel(), retrieve_fn=lambda *_: [], checkpointer=InMemorySaver())
    app.dependency_overrides[get_graph] = lambda: graph
    yield graph
    del app.dependency_overrides[get_graph]


# --- 변환 (순수 함수) ---------------------------------------------------------


def test_converts_human_and_ai_turns():
    ui = to_ui_messages([HumanMessage("안녕", id="h1"), AIMessage("반가워요", id="a1")])

    assert ui == [
        {"id": "h1", "role": "user", "parts": [{"type": "text", "text": "안녕"}]},
        {"id": "a1", "role": "assistant", "parts": [{"type": "text", "text": "반가워요"}]},
    ]


def test_drops_tool_and_system_messages():
    # ★ 화면에 보여줄 것만 남긴다 ★ ToolMessage는 모델에게 건네줄 재료지 사람이 읽을
    # 글이 아니다 — chat.py의 스트림이 AIMessageChunk만 통과시키는 것과 같은 판단이고,
    # **같은 규칙을 두 경로(스트리밍·복원)가 따로 구현하고 있다는 점**이 중요하다.
    # 한쪽만 고치면 "새로고침하면 없던 게 나타나는" 형태로 어긋난다.
    ui = to_ui_messages(
        [
            SystemMessage("너는 도우미다"),
            HumanMessage("서울 몇 시야?", id="h1"),
            ToolMessage("2026-09-14T10:00", tool_call_id="t1"),
            AIMessage("오전 10시입니다", id="a1"),
        ]
    )

    assert [m["role"] for m in ui] == ["user", "assistant"]


def test_drops_an_ai_message_that_only_carries_a_tool_call():
    # 도구를 부르기로 결정한 턴은 본문이 비어 있다. 그대로 넣으면 화면에 빈 말풍선이
    # 생긴다 — 에러가 아니라 "이상한 UI"라서 테스트가 없으면 배포까지 간다.
    calling = AIMessage(
        "", id="a0", tool_calls=[{"name": "get_current_time", "args": {}, "id": "t1"}]
    )

    ui = to_ui_messages([HumanMessage("몇 시야?", id="h1"), calling, AIMessage("10시", id="a1")])

    assert [m["id"] for m in ui] == ["h1", "a1"]


def test_generates_an_id_when_the_message_has_none():
    # LangChain 메시지의 id는 Optional이다. 없으면 React가 key로 쓸 값이 없어져
    # 리스트 렌더가 어긋난다(경고만 나고 화면은 이상해진다).
    ui = to_ui_messages([HumanMessage("안녕")])

    assert ui[0]["id"]


def test_attaches_sources_to_the_last_assistant_message():
    # ★ 마지막 것에만 붙는 이유 ★ State의 `retrieved`는 매 턴 덮어써진다 —
    # 즉 체크포인터에 남아 있는 것은 **가장 최근 턴이 무엇을 봤는지**뿐이다.
    # 그걸 이전 턴들에 뿌리면 "3턴 전 답변에 방금 검색한 출처가 붙는" 거짓말이 된다.
    chunk = RetrievedChunk(
        source="CLAUDE.md",
        chunk_index=3,
        content="본문",
        heading_path="CLAUDE.md > 개요",
        distance=0.1,
    )

    ui = to_ui_messages(
        [
            HumanMessage("첫 질문", id="h1"),
            AIMessage("첫 답", id="a1"),
            HumanMessage("둘째 질문", id="h2"),
            AIMessage("둘째 답", id="a2"),
        ],
        sources=[chunk],
    )

    assert len(ui[1]["parts"]) == 1  # 첫 답에는 안 붙는다
    assert ui[3]["parts"][1]["type"] == "source-document"
    assert ui[3]["parts"][1]["sourceId"] == "CLAUDE.md#3"


def test_empty_history_is_an_empty_list():
    assert to_ui_messages([]) == []


# --- 라우터 -------------------------------------------------------------------


def test_returns_the_conversation_stored_on_the_server(client, chat_graph):
    # 먼저 한 턴을 주고받아 체크포인터에 쌓는다.
    client.post("/api/v1/chat", json=_wire(_msg("m1", "user", "안녕"), chat_id="t-restore"))

    response = client.get("/api/v1/chat/t-restore/messages")

    assert response.status_code == 200
    messages = response.json()["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[0]["parts"][0]["text"] == "안녕"


def test_an_unknown_thread_is_an_empty_conversation_not_a_404(client, chat_graph):
    # ★ 404가 아닌 이유 ★ "아직 아무 말도 안 한 새 대화"와 "없는 대화"를 서버가
    # 구분할 방법이 없다. 그리고 새 대화는 **정상 상태**다 — 브라우저가 새 id로
    # 처음 접속할 때마다 404를 받으면 프론트가 그걸 에러로 다뤄야 하고,
    # 그러면 정상 흐름에 에러 처리가 섞인다.
    response = client.get("/api/v1/chat/처음-보는-스레드/messages")

    assert response.status_code == 200
    assert response.json()["messages"] == []


def test_threads_stay_isolated(client, chat_graph):
    # M5-3이 만든 것은 "읽기" 경로다. 2b에서 격리를 확인했던 쓰기 경로와 별개로
    # 여기서도 스레드 경계가 지켜지는지 본다 — 새 경로는 새 유출 통로다.
    client.post("/api/v1/chat", json=_wire(_msg("m1", "user", "A의 비밀"), chat_id="thread-a"))
    client.post("/api/v1/chat", json=_wire(_msg("m2", "user", "B의 질문"), chat_id="thread-b"))

    a = client.get("/api/v1/chat/thread-a/messages").json()["messages"]

    assert [p["text"] for m in a for p in m["parts"] if p["type"] == "text"][0] == "A의 비밀"
    assert all("B의 질문" not in str(m) for m in a)
