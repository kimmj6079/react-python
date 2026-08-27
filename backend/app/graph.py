# LangGraph 그래프 정의. "대화 상태를 들고 LLM을 부르는 흐름"만 담당한다.
# HTTP도 SSE 와이어 포맷도 모른다 — 그건 각각 api/routes/chat.py와 core/ai_sdk.py의 일이다.
# 타입을 ChatAnthropic이 아니라 BaseChatModel로
# 2b에서 이 파일이 바뀐 곳은 build_graph의 인자 하나와 compile 한 줄, 총 두 군데다.
# 노드도 엣지도 2a 그대로다 — "대화를 기억한다"는 기능이 노드가 아니라 컴파일
# 옵션으로 들어온다. LangGraph를 쓰는 이유 중 하나가 이것이다.
from typing import Annotated, Any, TypedDict

from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph


class State(TypedDict):
    # 그래프가 노드 사이로 넘기는 데이터의 모양.
    #
    # Annotated의 두 번째 항목 add_messages는 "리듀서"다. 노드가
    # {"messages": [새 메시지]}를 반환하면 기존 리스트를 덮어쓰는 게 아니라
    # add_messages가 이어붙인다. 리듀서를 빼먹으면 노드가 반환한 값이 통째로
    # 덮어써서 히스토리가 매번 날아간다 — LangGraph 초보의 1번 실수다.
    #
    # ★ 2b에서 이 리듀서가 하는 일이 하나 늘었다 ★
    # 체크포인터가 복원한 "이전 대화 전체" 위에 이번 턴의 새 메시지를
    # 이어붙이는 것도 같은 리듀서다. 그래서 라우터는 새 메시지 1개만 넣으면
    # 되고, 히스토리를 조립하는 코드를 우리가 짤 일이 없다.
    #
    # 덤: add_messages는 {"role": ..., "content": ...} dict를 LangChain 메시지
    # 객체(HumanMessage/AIMessage)로 알아서 변환한다(실측 확인).
    messages: Annotated[list, add_messages]


def build_graph(
    model: BaseChatModel,
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    # 모델을 인자로 받는 이유는 M1의 get_anthropic_client()와 같다 —
    # 테스트에서 가짜 모델로 갈아끼우기 위해서다. 이 모듈 안에서
    # ChatAnthropic()을 직접 만들면 import되는 순간 진짜 모델로 고정된다.
    #
    # checkpointer를 인자로 받는 이유도 정확히 같다. 여기서 InMemorySaver()를
    # 직접 만들어버리면 (1) 테스트끼리 대화 상태가 새는 것을 막을 방법이 없고,
    # (2) 나중에 AsyncPostgresSaver로 바꿀 때 이 파일을 고쳐야 한다.
    # "무엇에 저장하는가"는 배선 결정이지 그래프 구조 결정이 아니다.
    #
    # 타입을 InMemorySaver가 아니라 BaseCheckpointSaver로 잡은 것도 같은 맥락.
    # 저장소를 Postgres로 바꿔도 이 시그니처는 안 바뀐다.
    #
    # 기본값이 None인 이유: 체크포인터 없이도 그래프는 완전히 동작한다(2a가 그랬다).
    # 시그니처가 그 사실을 그대로 말해주게 둔다 — 2c에서 그래프 구조만 단독으로
    # 테스트할 때 실제로 쓰게 된다.

    async def call_model(state: State) -> dict[str, Any]:
        # 2a에서 한 글자도 안 바뀌었다.
        # 노드는 자기가 받은 state["messages"]가 이번 HTTP 요청에서 온 것인지
        # 체크포인터가 디스크(지금은 메모리)에서 복원한 것인지 모른다.
        # 알 필요도 없다 — 그 구분은 그래프 런타임의 일이다.
        response = await model.ainvoke(state["messages"])
        return {"messages": [response]}

    builder = StateGraph(State)
    # 노드 이름은 문자열이다. 이 이름이 스트리밍 메타데이터의 langgraph_node로
    # 그대로 나오므로, 나중에 "어느 노드의 토큰인가"를 구분할 때 쓰인다.
    builder.add_node("call_model", call_model)

    # START/END는 그래프의 입구·출구를 뜻하는 상수다. 명시적으로 이어야 한다.
    builder.add_edge(START, "call_model")
    builder.add_edge("call_model", END)

    # 2a에서 "여기에 checkpointer가 들어간다"고 적어둔 바로 그 자리다.
    # checkpointer=None을 넘기면 compile은 2a와 완전히 동일한 그래프를 만든다
    # (실측: 체크포인터 없는 그래프에 config를 줘도 조용히 무시된다).
    return builder.compile(checkpointer=checkpointer)
