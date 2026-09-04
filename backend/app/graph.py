# LangGraph 그래프 정의. "대화 상태를 들고 LLM을 부르는 흐름"만 담당한다.
# HTTP도 SSE 와이어 포맷도 모른다 — 그건 각각 api/routes/chat.py와 core/ai_sdk.py의 일이다.
#
# ★ 2c에서 이 그래프가 처음으로 직선이 아니게 됐다 ★
# 2a·2b까지는 START→call_model→END 한 줄이라 사실 LangGraph 없이도 됐다.
# 조건부 엣지(분기)와 사이클이 생기는 지금이 "그래프를 왜 쓰는가"가 처음
# 드러나는 지점이다. 상태(2b)와 흐름(2c)을 라이브러리가 들고 있으므로,
# 우리가 짜는 것은 노드와 엣지뿐이다.
#
# ★ 3-2b에서 노드가 하나 더 늘었다 — retrieve ★
# START → retrieve → call_model ⇄ tools 순서. retrieve는 이 그래프가 "어느
# 저장소에서" 검색하는지 모른다 — build_graph가 retrieve_fn으로 주입받는
# Callable[[str], list[RetrievedChunk]] 하나만 안다. 3-3에서 Qdrant 구현이
# 생겨도 이 파일은 한 글자도 안 바뀐다 — model·checkpointer·tools를 인자로
# 받는 것과 정확히 같은 이유다.
import asyncio
import logging
from collections.abc import Callable
from typing import Annotated, Any, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from app.rag.retriever import RetrievedChunk
from app.tools import TOOLS

logger = logging.getLogger(__name__)


# retrieve 노드가 검색한 문서를 모델에게 어떻게 보여줄지 정하는 템플릿.
# tools.py의 docstring이 "도구를 부를지 말지"를 좌우하는 레버였다면, 이 템플릿은
# "검색 결과를 얼마나 신뢰할지"를 좌우하는 레버다 — 답이 이상하면 로직이 아니라
# 여기부터 고친다.
SYSTEM_PROMPT_TEMPLATE = """다음은 사용자의 질문과 관련이 있을 수 있는 문서 발췌다. \
관련이 있으면 이 내용을 근거로 답하고 출처(파일명)를 함께 밝혀라. 관련이 없거나 \
답하기에 근거가 부족하면 억지로 끼워 맞추지 말고 모른다고 답하라.

{context}"""


def _format_context(chunks: list[RetrievedChunk]) -> str:
    # 검색 결과가 없으면 빈 문자열을 돌려주고, call_model은 그걸 보고 시스템
    # 프롬프트 자체를 안 붙인다. "컨텍스트 없음"과 "관련 없는 컨텍스트"를
    # 다르게 다룬다 — 후자는 모델이 스스로 무시하도록 프롬프트가 유도하고,
    # 전자는 애초에 프롬프트를 늘리지 않는다.
    if not chunks:
        return ""
    return "\n\n".join(f"[출처: {c.source}]\n{c.content}" for c in chunks)


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

    # ★ 3-2b에서 늘었다 ★ 리듀서가 없다 = 기본 동작인 "마지막에 쓴 값으로
    # 덮어쓰기"다. messages와 다르게 쌓이지 않는다 — 매 턴 retrieve 노드가
    # 이번 질문 기준으로 통째로 새로 채운다. 체크포인터가 State 전체를
    # 저장하므로 이 값도 함께 저장되긴 하지만, 리스트가 아니라 문자열
    # 스칼라라 messages처럼 무한히 커지는 문제는 없다. call_model은 이 값을
    # 시스템 프롬프트 재료로만 쓰고 messages에는 넣지 않으므로, 대화
    # 히스토리 자체는 검색 결과로 오염되지 않는다.
    retrieved_context: str


def build_graph(
    model: BaseChatModel,
    retrieve_fn: Callable[[str], list[RetrievedChunk]],
    checkpointer: BaseCheckpointSaver | None = None,
    tools: list[BaseTool] | None = None,
) -> CompiledStateGraph:
    # 모델을 인자로 받는 이유는 M1의 get_anthropic_client()와 같다 —
    # 테스트에서 가짜 모델로 갈아끼우기 위해서다. 이 모듈 안에서
    # ChatAnthropic()을 직접 만들면 import되는 순간 진짜 모델로 고정된다.
    #
    # checkpointer(2b)·tools(2c)·retrieve_fn(3-2b)을 인자로 받는 이유도 정확히
    # 같다. 타입을 구현체가 아니라 BaseCheckpointSaver / BaseTool /
    # Callable[[str], list[RetrievedChunk]]로 잡은 것도 같은 맥락 — 저장소를
    # Postgres로 바꾸거나 도구를 늘리거나(2c) 검색소를 Qdrant로 바꿔도(3-3)
    # 이 시그니처는 안 바뀐다.
    #
    # ★ retrieve_fn만 기본값이 없다 ★ model처럼 "이게 없으면 그래프가
    # 무의미한" 핵심 부품이기 때문이다. 기본값을 주고 그 기본이 조용히 진짜
    # DB를 부르게 만들면, 이걸 깜빡한 새 테스트가 CI에서 실제 Postgres를
    # 두드리는 사고가 난다 — checkpointer·tools처럼 "없어도 그래프가
    # 성립하는" 부품과는 성격이 다르다.
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

    async def retrieve(state: State) -> dict[str, Any]:
        # 이번 턴의 질문은 항상 state["messages"]의 마지막 원소다 — START
        # 직후 실행되는 이 노드가 도는 시점엔 이미 체크포인터 복원 +
        # add_messages 병합이 끝나 있다(FLOW.md의 13~14번과 같은 순서).
        # chat.py가 빈 텍스트를 이미 400으로 막아뒀으므로 여기서 다시
        # 검증하지 않는다.
        #
        # ★ retrieve_fn은 동기 함수다 — asyncio.to_thread로 이벤트 루프
        # 밖에서 돌린다 ★ DB 왕복과 fastembed의 CPU 추론(수십~수백ms)이 둘 다
        # 블로킹이라, 그대로 부르면 이 요청이 검색하는 동안 같은 프로세스의
        # 다른 모든 요청(다른 사용자의 스트리밍 포함)이 멈춘다.
        #
        # ★ 검색 실패가 턴 전체를 죽이지 않게 잡는다 ★ 여기서 예외를 그대로
        # 흘려보내면 astream()이 raise하고, 그 시점은 이미 200 헤더가 나간
        # 뒤라서(FLOW.md "10번이 분기점이다") 클라이언트엔 "헤더 정상 + 본문
        # 없음 + 연결 끊김"으로만 보인다 — 방금 DB가 죽었을 때 실제로 겪은
        # 것과 같은 실패 형태다. RAG는 "있으면 답을 더 잘하는" 보조 기능이지
        # 챗봇 자체의 필수 경로가 아니므로, 검색이 실패하면 빈 컨텍스트로
        # 대체하고 계속 진행한다 — 문서 근거 없는 답이 나갈 수 있지만, 최소한
        # 챗봇은 응답한다.
        query = state["messages"][-1].content
        try:
            chunks = await asyncio.to_thread(retrieve_fn, query)
        except Exception:
            logger.exception("retrieve_fn 실패 - 컨텍스트 없이 진행한다")
            chunks = []
        return {"retrieved_context": _format_context(chunks)}

    async def call_model(state: State) -> dict[str, Any]:
        # 2a·2b에서 한 글자도 안 바뀌었다(bind된 모델을 쓰는 것만 빼면).
        # 노드는 자기가 받은 state["messages"]가 이번 HTTP 요청에서 온 것인지,
        # 체크포인터가 복원한 것인지, 방금 도구가 만든 것인지 모른다.
        #
        # ★ 3-2b에서 늘어난 부분 ★ retrieved_context가 있으면 시스템 메시지를
        # 맨 앞에 "잠깐" 붙여서 모델에 넘긴다. state["messages"]에는 안 넣는다
        # — 새 리스트(messages = [system, *state["messages"]])를 만들 뿐 원본은
        # 그대로고, 반환값도 여전히 {"messages": [response]}뿐이라 체크포인터
        # 에는 시스템 메시지가 한 번도 안 쌓인다.
        messages = state["messages"]
        context = state.get("retrieved_context")
        if context:
            messages = [
                SystemMessage(content=SYSTEM_PROMPT_TEMPLATE.format(context=context)),
                *messages,
            ]

        response = await model_with_tools.ainvoke(messages)
        return {"messages": [response]}

    builder = StateGraph(State)
    builder.add_node("retrieve", retrieve)
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

    # ★ 3-2b — 시작이 곧장 call_model이 아니라 retrieve로 바뀌었다 ★
    # 도구 왕복(tools → call_model 사이클)에는 retrieve를 다시 태우지 않는다.
    # 검색은 "이번 턴 사용자의 질문"에 대한 것이지 도구 호출 중간 결과에
    # 대한 게 아니라서, 한 턴에 한 번만 하면 된다 — 그래서 사이클 엣지는
    # retrieve를 거치지 않고 곧장 call_model로 돌아간다(아래 tools→call_model).
    builder.add_edge(START, "retrieve")
    builder.add_edge("retrieve", "call_model")

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
