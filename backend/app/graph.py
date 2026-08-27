# LangGraph 그래프 정의. "대화 상태를 들고 LLM을 부르는 흐름"만 담당한다.
# HTTP도 SSE 와이어 포맷도 모른다 — 그건 각각 api/routes/chat.py와 core/ai_sdk.py의 일이다.
#
# ★ 2c에서 이 그래프가 처음으로 직선이 아니게 됐다 ★
# 2a·2b까지는 START→call_model→END 한 줄이라 사실 LangGraph 없이도 됐다.
# 조건부 엣지(분기)와 사이클이 생기는 지금이 "그래프를 왜 쓰는가"가 처음
# 드러나는 지점이다. 상태(2b)와 흐름(2c)을 라이브러리가 들고 있으므로,
# 우리가 짜는 것은 노드와 엣지뿐이다.
from typing import Annotated, Any, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from app.tools import TOOLS


class State(TypedDict):
    # 그래프가 노드 사이로 넘기는 데이터의 모양.
    #
    # Annotated의 두 번째 항목 add_messages는 "리듀서"다. 노드가
    # {"messages": [새 메시지]}를 반환하면 기존 리스트를 덮어쓰는 게 아니라
    # add_messages가 이어붙인다. 리듀서를 빼먹으면 노드가 반환한 값이 통째로
    # 덮어써서 히스토리가 매번 날아간다 — LangGraph 초보의 1번 실수다.
    #
    # 2b에서 이 리듀서가 하는 일이 하나 늘었다: 체크포인터가 복원한 "이전 대화
    # 전체" 위에 이번 턴의 새 메시지를 이어붙이는 것도 같은 리듀서다.
    #
    # ★ 2c에서 또 하나 늘었다 ★ ToolNode가 반환하는 ToolMessage를 이어붙이는
    # 것도 이 리듀서다. 즉 "모델의 도구 호출 → 도구 결과 → 모델의 최종 답변"이
    # 한 리스트에 순서대로 쌓인다. 그 순서가 곧 Anthropic API가 요구하는
    # tool_use / tool_result 짝이라, 우리가 맞춰줄 일이 없다.
    #
    # 덤: add_messages는 {"role": ..., "content": ...} dict를 LangChain 메시지
    # 객체(HumanMessage/AIMessage)로 알아서 변환한다(실측 확인).
    messages: Annotated[list, add_messages]


def build_graph(
    model: BaseChatModel,
    checkpointer: BaseCheckpointSaver | None = None,
    tools: list[BaseTool] | None = None,
) -> CompiledStateGraph:
    # 모델을 인자로 받는 이유는 M1의 get_anthropic_client()와 같다 —
    # 테스트에서 가짜 모델로 갈아끼우기 위해서다. 이 모듈 안에서
    # ChatAnthropic()을 직접 만들면 import되는 순간 진짜 모델로 고정된다.
    #
    # checkpointer(2b)와 tools(2c)를 인자로 받는 이유도 정확히 같다.
    # 타입을 구현체가 아니라 BaseCheckpointSaver / BaseTool로 잡은 것도 같은 맥락 —
    # 저장소를 Postgres로 바꾸거나 도구를 늘려도 이 시그니처는 안 바뀐다.
    #
    # 기본값을 [TOOLS]가 아니라 None으로 둔 것은 mutable default를 피하는
    # 관용구다. 리스트를 기본값에 직접 쓰면 모든 호출이 같은 객체를 공유해서,
    # 누군가 한 번 append하면 그 뒤 모든 호출이 오염된다.
    if tools is None:
        tools = TOOLS

    # ★ 2c의 핵심 ① — 모델에게 도구 목록을 알려준다 ★
    # 실측: 원본 model은 안 바뀌고 새 객체(_ChatModelBinding)가 나온다.
    # 그래서 deps.py의 _model을 여러 그래프가 공유해도 안전하다.
    #
    # 부작용 하나를 알고 간다: bind_tools를 한 순간부터 AIMessageChunk.content가
    # 도구를 쓰든 안 쓰든 "항상 리스트"가 된다(실측). 2a에서 .content 대신
    # .text를 써둔 덕에 chat.py는 이 변화에 아무 영향이 없다.
    model_with_tools = model.bind_tools(tools)

    async def call_model(state: State) -> dict[str, Any]:
        # 2a·2b에서 한 글자도 안 바뀌었다(bind된 모델을 쓰는 것만 빼면).
        # 노드는 자기가 받은 state["messages"]가 이번 HTTP 요청에서 온 것인지,
        # 체크포인터가 복원한 것인지, 방금 도구가 만든 것인지 모른다.
        response = await model_with_tools.ainvoke(state["messages"])
        return {"messages": [response]}

    builder = StateGraph(State)
    builder.add_node("call_model", call_model)

    # ★ 노드 이름이 반드시 "tools"여야 한다 ★
    # tools_condition이 문자열 "tools"를 하드코딩해서 반환하기 때문이다(실측:
    # 반환 타입이 Literal['tools', '__end__']). 다른 이름을 쓰려면
    # add_conditional_edges의 3번째 인자로 {"tools": "내가_지은_이름"} 매핑을 준다.
    #
    # ToolNode는 "AIMessage의 tool_calls를 읽어 실제 함수를 부르고 그 결과를
    # ToolMessage로 만들어 State에 넣는" 일을 대신한다. 직접 짜면 tool_call_id
    # 짝맞추기·예외 처리·병렬 호출까지 우리가 해야 한다.
    builder.add_node("tools", ToolNode(tools))

    builder.add_edge(START, "call_model")

    # ★ 2c의 핵심 ② — 여기가 분기다 ★
    # add_edge(고정 연결)와 달리, 매 실행마다 tools_condition이 상태를 보고
    # 다음 노드를 정한다. 마지막 AIMessage에 tool_calls가 있으면 "tools"로,
    # 없으면 "__end__"로 (실측). END를 직접 import해서 이을 필요가 없어졌다.
    builder.add_conditional_edges("call_model", tools_condition)

    # ★ 2c의 핵심 ③ — 여기가 사이클이다 ★
    # 도구를 실행했으면 결과를 들고 모델로 되돌아온다. 모델이 그 결과를 읽어야
    # 최종 답변이 나오기 때문이다. 모델이 또 도구를 부르면 또 돈다.
    # 무한루프는 LangGraph의 recursion_limit(기본 25)이 막는다 —
    # 넘으면 GraphRecursionError다. config에 넣어 조절할 수 있다.
    builder.add_edge("tools", "call_model")

    # compile()이 검증(도달 못 하는 노드, 끊긴 엣지)을 하고 실행 가능한 객체를 만든다.
    return builder.compile(checkpointer=checkpointer)
