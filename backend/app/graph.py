# LangGraph 그래프 정의. "대화 상태를 들고 LLM을 부르는 흐름"만 담당한다.
# HTTP도 SSE 와이어 포맷도 모른다 — 그건 각각 api/routes/chat.py와 core/ai_sdk.py의 일이다.
#
# 노드가 하나뿐이라 지금은 그래프를 쓰는 이득이 잘 안 보인다. 정상이다.
# 2a는 "동작을 바꾸지 않고 배선만 옮기는" 단계이고, 메모리(2b)와 도구(2c)가
# 붙기 시작하면 이 구조가 필요해진다.
from typing import Annotated, Any, TypedDict

from langchain_core.language_models import BaseChatModel
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
    # 덤: add_messages는 {"role": ..., "content": ...} dict를 LangChain 메시지
    # 객체(HumanMessage/AIMessage)로 알아서 변환한다(실측 확인). 덕분에
    # ai_sdk.to_anthropic_messages()를 한 줄도 안 고치고 그대로 쓴다.
    messages: Annotated[list, add_messages]


def build_graph(model: BaseChatModel) -> CompiledStateGraph:
    # 모델을 인자로 받는 이유는 M1의 get_anthropic_client()와 같다 —
    # 테스트에서 가짜 모델로 갈아끼우기 위해서다. 이 모듈 안에서
    # ChatAnthropic()을 직접 만들면 import되는 순간 진짜 모델로 고정된다.
    #
    # 타입을 ChatAnthropic이 아니라 BaseChatModel로 잡은 것도 같은 맥락이다.
    # 프로바이더를 바꾸거나 가짜를 넣어도 이 함수는 안 바뀐다.

    async def call_model(state: State) -> dict[str, Any]:
        # 노드는 "State 전체"가 아니라 "바뀔 부분만" dict로 반환한다.
        # 반환한 키만 리듀서를 거쳐 병합된다. state를 직접 수정하지 않는다.
        response = await model.ainvoke(state["messages"])
        return {"messages": [response]}

    builder = StateGraph(State)
    # 노드 이름은 문자열이다. 이 이름이 스트리밍 메타데이터의 langgraph_node로
    # 그대로 나오므로, 나중에 "어느 노드의 토큰인가"를 구분할 때 쓰인다.
    builder.add_node("call_model", call_model)

    # START/END는 그래프의 입구·출구를 뜻하는 상수다. 명시적으로 이어야 한다.
    builder.add_edge(START, "call_model")
    builder.add_edge("call_model", END)

    # compile()이 검증(도달 못 하는 노드, 끊긴 엣지 등)을 하고 실행 가능한
    # 객체를 만든다. 2b에서 여기에 checkpointer=InMemorySaver()가 들어간다.
    return builder.compile()
