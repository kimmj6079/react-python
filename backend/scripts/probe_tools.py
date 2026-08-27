# 2c 실측 스크립트. "추측하지 말고 직접 찍어본다" — M1-1b/1d, M2-2a와 같은 방식이다.
#
# 실행: cd backend && uv run python scripts/probe_tools.py
# 실제 Anthropic을 호출한다(짧은 질문 2개, 비용은 무시할 수준).
#
# 확인하려는 것 5가지. 전부 2c-2/2c-3에서 판단이 갈리는 지점이다.
#   ① @tool이 만든 객체의 표면 — 모델에게 무엇이 보이나
#   ② bind_tools가 무엇을 돌려주나 — 원본 모델이 바뀌나, 새 객체인가
#   ③ tools_condition의 반환값 — 노드 이름을 마음대로 지어도 되나
#   ④ 도구를 부를 때 AIMessageChunk.content가 정말 리스트가 되나 (FLOW.md 함정 ③)
#   ⑤ ★ stream_mode="messages"에 도구 노드의 메시지도 섞여 나오나 ★
#      이게 새면 도구 실행 결과가 그대로 채팅창에 뜬다.
import asyncio
from datetime import datetime
from typing import Annotated, Any, TypedDict
from zoneinfo import ZoneInfo

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from langgraph.graph import START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition

from app.core.config import settings


# @tool 데코레이터가 평범한 함수를 LangChain 도구 객체로 감싼다.
# ★ docstring이 장식이 아니다 ★ 이 글이 그대로 모델에게 전송되어 "이 도구를
# 언제 쓸지"를 판단하는 유일한 근거가 된다. 타입 힌트는 인자 스키마가 된다.
# 즉 이 함수의 시그니처와 docstring은 코드 문서가 아니라 프롬프트의 일부다.
@tool
def get_current_time(timezone: str = "Asia/Seoul") -> str:
    """지정한 타임존의 현재 시각을 ISO 8601 문자열로 돌려준다.

    Args:
        timezone: IANA 타임존 이름. 예: "Asia/Seoul", "UTC", "America/New_York"
    """
    return datetime.now(ZoneInfo(timezone)).isoformat()


class State(TypedDict):
    messages: Annotated[list, add_messages]


def probe_tool_surface() -> None:
    print("=" * 72)
    print("① @tool이 만든 객체의 표면 — 모델에게 보이는 것")
    print("=" * 72)
    print("type        :", type(get_current_time).__name__)
    print("name        :", get_current_time.name)
    print("description :", get_current_time.description)
    print("args        :", get_current_time.args)
    # 도구는 그냥 부를 수 없고 invoke()로 부른다. 인자는 dict다.
    print("invoke      :", get_current_time.invoke({"timezone": "UTC"}))
    print()


def probe_bind(model: BaseChatModel) -> None:
    print("=" * 72)
    print("② bind_tools가 돌려주는 것")
    print("=" * 72)
    bound = model.bind_tools([get_current_time])
    print("원본       :", type(model).__name__)
    print("bound      :", type(bound).__name__)
    print("같은 객체? :", bound is model)  # False면 원본은 그대로 = 재사용 안전
    print()


def probe_condition() -> None:
    print("=" * 72)
    print("③ tools_condition의 반환값 — 노드 이름을 정할 수 있나")
    print("=" * 72)
    plain = AIMessage(content="안녕하세요")
    calling = AIMessage(
        content="",
        tool_calls=[{"name": "get_current_time", "args": {"timezone": "Asia/Seoul"}, "id": "c1"}],
    )
    print("도구콜 없음 ->", repr(tools_condition({"messages": [plain]})))
    print("도구콜 있음 ->", repr(tools_condition({"messages": [calling]})))
    print()


async def probe_stream(model: BaseChatModel) -> None:
    print("=" * 72)
    print("④⑤ 도구가 붙은 그래프의 stream_mode='messages'에 무엇이 흐르나")
    print("=" * 72)

    bound = model.bind_tools([get_current_time])

    async def call_model(state: State) -> dict[str, Any]:
        return {"messages": [await bound.ainvoke(state["messages"])]}

    builder = StateGraph(State)
    builder.add_node("call_model", call_model)
    # 노드 이름이 반드시 "tools"여야 한다. tools_condition이 문자열 "tools"를
    # 하드코딩해서 반환하기 때문이다(③에서 눈으로 확인한다).
    builder.add_node("tools", ToolNode([get_current_time]))

    builder.add_edge(START, "call_model")
    # ★ 여기서 그래프가 처음으로 직선이 아니게 된다 ★
    # add_edge(고정)가 아니라 add_conditional_edges(분기)다. 매 실행마다
    # tools_condition이 상태를 보고 "tools"로 갈지 END로 갈지 정한다.
    builder.add_conditional_edges("call_model", tools_condition)
    # 그리고 도구를 실행한 뒤에는 모델로 되돌아온다 = 사이클. 모델이 도구 결과를
    # 보고 최종 답변을 만들어야 하기 때문이다. 여기서 또 도구를 부르면 한 번 더 돈다.
    builder.add_edge("tools", "call_model")

    graph = builder.compile()

    for question in ["안녕! 짧게 인사만 해줘", "서울 지금 몇 시야? 짧게 답해줘"]:
        print(f"\n--- 질문: {question}")
        async for chunk, meta in graph.astream(
            {"messages": [HumanMessage(question)]},
            stream_mode="messages",
        ):
            node = str(meta.get("langgraph_node"))
            print(
                f"  [{node:<10}] {type(chunk).__name__:<16} "
                f"content={type(chunk.content).__name__:<5} text={chunk.text!r}"
            )


async def main() -> None:
    # deps.py와 같은 설정을 쓴다. max_tokens만 줄였다(실측이라 긴 답이 필요 없다).
    model = ChatAnthropic(
        model=settings.anthropic_model,
        api_key=settings.anthropic_api_key,
        max_tokens=512,
        streaming=True,
    )
    probe_tool_surface()
    probe_bind(model)
    probe_condition()
    await probe_stream(model)


if __name__ == "__main__":
    asyncio.run(main())
