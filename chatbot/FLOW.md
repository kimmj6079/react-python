# 챗봇 요청 흐름 지도

> 메시지 하나가 브라우저에서 출발해 화면에 글자로 돌아오기까지, **어느 파일의 어느 줄을 지나는지**
> 정리한 문서다. 스터디 중 "이건 어디서 하는 거지?"가 생길 때 여기서 찾는다.
>
> **기준 시점: M2-2b 완료 (2026-08-27)** — 마일스톤이 끝날 때마다 갱신한다.
> 진행 순서와 각 단계의 결정·함정 기록은 [README.md](./README.md)에 있다.

---

## 1. 한 장으로 보는 흐름

```
[브라우저 :5173]                              [FastAPI :8000]
Chat.tsx
  chatId = generateId()   ← 대화 세션 id를 컴포넌트가 소유
  sendMessage({ text })
     │
     ▼
transport.ts
  prepareChatRequest()  ─── POST /api/v1/chat ────▶ main.py        CORS → 라우터
  { id, messages: [마지막 1개], … }                      │
     ▲                                                   ▼
     └ 히스토리를 안 보낸다                          schemas/chat.py  본문 검증
                                                         │
                                                   deps.py          그래프 주입
                                                         │
                                                   routes/chat.py   추출 · 가드 · thread_id
                                                         │
                                                   graph.py         START→call_model→END
                                                         │        ▲
                                                         │        └─ InMemorySaver
                                                         │           (이전 대화 복원 · 저장)
                                                         ▼
                                                   ChatAnthropic ──▶ Anthropic API
                                                         │
                                                   routes/chat.py   chunk.text 추출
                                                         │
                                                   core/ai_sdk.py   SSE 포맷
     ◀──────────── text/event-stream ────────────────────┘
useChat 파서 → messages[].parts → 화면 렌더
```

핵심은 **각 층이 옆 층의 관심사를 모른다**는 것이다.

- `core/ai_sdk.py`는 "누가 토큰을 만드는지" 모른다 → 2a(LangGraph)에도 2b(체크포인터)에도 한 줄 안 바뀌었다
- `graph.py`는 "HTTP"를 모른다 → 테스트에서 그래프만 따로 돌릴 수 있다
- `routes/chat.py`는 "SSE 바이트"를 모른다 → 와이어 포맷이 바뀌어도 라우터는 그대로다
- `call_model` 노드는 받은 메시지가 **이번 요청에서 온 것인지 체크포인터가 복원한 것인지 모른다**

### 2b에서 바뀐 것 한 줄

**"대화를 누가 기억하는가"가 브라우저에서 서버로 넘어왔다.** 2a까지는 프론트가 매 요청에 히스토리
전체를 실어 보냈다. 지금은 **새 메시지 1개 + `thread_id`**만 보내고, 히스토리는 서버의 체크포인터가
들고 있다.

---

## 2. 파일별 역할

| 파일 | 한 줄 역할 | 핵심 심볼 | 이 파일을 고칠 때 |
|---|---|---|---|
| [Chat.tsx](../frontend/src/components/chat/Chat.tsx) | 화면 · 입력 · **세션 id 소유** | `chatId`:38, `useChat`:43, `submit`:74 | UI/UX가 바뀔 때 |
| [transport.ts](../frontend/src/components/chat/transport.ts) | **무엇을 보낼지**(와이어 계약) | `prepareChatRequest`:18, `chatTransport`:44 | 요청 본문이 바뀔 때 |
| [client.ts](../frontend/src/api/client.ts) | 백엔드 **주소**만 관리 | `CHAT_API_URL`:12 | 엔드포인트가 늘 때 |
| [main.py](../backend/app/main.py) | CORS + 라우터 등록 | `add_middleware`:15, `include_router`:26 | 라우터 · 허용 오리진 추가 |
| [schemas/chat.py](../backend/app/schemas/chat.py) | 요청 본문의 **모양 계약** | `UIMessage`:12, `ChatRequest`:26 | 프론트 요청 포맷이 바뀔 때 |
| [api/deps.py](../backend/app/api/deps.py) | 무거운 객체 **1회 생성 + 주입** | `_model`:30, `_checkpointer`:55, `get_graph`:60 | 모델 · **저장소** 교체 지점 |
| [api/routes/chat.py](../backend/app/api/routes/chat.py) | HTTP ↔ 그래프 **접착** | `chat`:26, `config`:51, `text_deltas`:56 | 토큰을 **어디서** 얻을지 바뀔 때 |
| [graph.py](../backend/app/graph.py) | 대화 **흐름** 정의 | `State`:16, `build_graph`:34, `compile`:74 | 노드 · 엣지가 늘 때 |
| [core/ai_sdk.py](../backend/app/core/ai_sdk.py) | AI SDK **와이어 포맷** | `latest_user_text`:43, `ui_message_stream`:86 | `ai` 패키지 버전이 바뀔 때 |
| [core/config.py](../backend/app/core/config.py) | 설정 · 시크릿 단일 소스 | `anthropic_model`, `anthropic_api_key` | 모델 교체 · 새 시크릿 |

### 프론트에도 같은 선을 그었다

`transport.ts`는 2b에서 `Chat.tsx`를 쪼개 만든 파일이다. 백엔드에서 `core/ai_sdk.py`(와이어 포맷)와
`api/routes/chat.py`(HTTP)를 나눈 것과 **같은 선**이다. 덤으로 `prepareChatRequest`가 순수 함수가 되어
React 없이 테스트된다(`transport.test.ts`).

---

## 3. 요청 경로 (올라가는 길)

| # | 위치 | 하는 일 | 실패하면 |
|---|---|---|---|
| 1 | `Chat.tsx:81` `sendMessage({text})` | 훅이 로컬 히스토리에 추가 | — |
| 2 | `transport.ts:18` `prepareChatRequest` | **본문을 직접 조립** — `messages`를 `slice(-1)`로 1개만 | `id`·`trigger` 누락 시 **422** |
| 3 | `main.py:15` CORS 미들웨어 | Origin 검사 | CORS 에러 |
| 4 | `main.py:26` 라우터 | `/api/v1` + `/chat` 매칭 | 404 |
| 5 | `deps.py:60` `get_graph()` | 그래프 주입 (**테스트가 여기서 교체**) | — |
| 6 | `schemas/chat.py:26` `ChatRequest` | 본문 검증 (타입 · 필수 · Literal) | **422** |
| 7 | `chat.py:29` `latest_user_text()` | **마지막 user 메시지 하나만** 추출 | — |
| 8 | `chat.py:35` 가드 | 텍스트가 없거나 마지막이 user가 아니면 차단 | **400** |
| 9 | `chat.py:51` `config` | `payload.id` → `thread_id` (**어느 대화인가**) | — |
| 10 | `chat.py:84` `return StreamingResponse` | **200 헤더 전송** | — |

### ⚠ 10번이 분기점이다

10번 **전에** 터지면 정상적인 4xx로 돌려줄 수 있다.
10번 **후에** 터지면 클라이언트에는 "200 헤더 + 빈 본문 + 연결 끊김"으로 보인다 — HTTP에서 가장
진단하기 어려운 실패 형태다.

`chat.py:29`의 추출과 `chat.py:35`의 가드가 **일부러 10번 앞에** 있는 이유가 이것이다.
async generator는 lazy해서 안에 넣으면 200이 나간 뒤에야 실행된다.

### 2번이 2b에서 생긴 줄이다

`prepareSendMessagesRequest`가 반환한 `body`는 SDK 기본 본문을 **대체한다(병합 아님, 실측)**.
그래서 `id`·`trigger`·`messageId`를 우리가 직접 넣어야 한다 — 빼먹으면 6번에서 422다.

---

## 4. 응답 경로 (내려오는 길) — 200 이후

| # | 위치 | 하는 일 |
|---|---|---|
| 11 | `ai_sdk.py:95~101` | `start` → `start-step` → `text-start` 3개를 먼저 내보냄 |
| 12 | `chat.py:69` `graph.astream(input, config, stream_mode="messages")` | 그래프 실행 시작 |
| 13 | **`InMemorySaver`** | `thread_id`로 **이전 대화 복원** |
| 14 | `graph.py:16` `add_messages` 리듀서 | 복원된 히스토리 **뒤에** 새 메시지를 이어붙임 |
| 15 | `graph.py:54` `call_model` | `model.ainvoke(state["messages"])` — 히스토리 전체를 받는다 |
| 16 | `ChatAnthropic` (`streaming=True`) | Anthropic SSE 수신 → 콜백으로 토큰 방출 |
| 17 | `chat.py:69` | `(AIMessageChunk, metadata)` 2-튜플 수신 |
| 18 | `chat.py:82` `yield chunk.text` | 텍스트만 추출 |
| 19 | `ai_sdk.py:109` | `data: {"type":"text-delta","id":"0","delta":"..."}\n\n` |
| 20 | **`InMemorySaver`** | 노드 종료 후 **갱신된 대화 저장** (다음 턴의 13번이 이걸 읽는다) |
| 21 | `ai_sdk.py:111~121` | `text-end` → `finish-step` → `finish` → `[DONE]` |
| 22 | `useChat` 파서 | `messages[].parts` 갱신 → 리렌더 |
| 23 | `Chat.tsx:168` | assistant면 `ReactMarkdown`, user면 문자열 그대로 |

**16~19번이 토큰 하나마다 반복된다.**

**13·14·20번이 2b에서 생긴 줄이고, 셋 다 우리가 짠 코드가 아니다.** 체크포인터와 리듀서가 한다 —
`chat.py`가 하는 일은 `config` 한 줄을 넘기는 것뿐이다.

---

## 5. 데이터 모양이 바뀌는 지점

| 단계 | 모양 | 어디서 |
|---|---|---|
| 브라우저 상태 | `UIMessage { id, role, parts[] }` **전체 히스토리** | `useChat` |
| HTTP 본문 | `{ id, messages: [마지막 1개], trigger, messageId }` | `transport.ts:35` |
| 검증 후 | `ChatRequest` (Pydantic 객체) | `schemas/chat.py:26` |
| 추출 후 | `str` (마지막 user 발화) | `ai_sdk.py:43` |
| 그래프 입력 | `{"messages": [{"role":"user","content": text}]}` | `chat.py:69` |
| **그래프 내부** | 복원된 히스토리 + 새 메시지 = `HumanMessage`/`AIMessage` 리스트 | **체크포인터 + `add_messages`** |
| 스트림 청크 | `(AIMessageChunk, metadata)` | `astream(stream_mode="messages")` |
| 델타 | `str` | `chunk.text` |
| 와이어 | `data: {...}\n\n` | `ai_sdk.py:75` |
| 화면 | `parts[]` → JSX | `Chat.tsx:168` |

**"브라우저 상태"와 "HTTP 본문"이 처음으로 어긋나는 것**이 2b의 전부다. 화면에는 대화 전체가 있지만
서버로는 마지막 하나만 간다. 화면의 히스토리는 이제 **표시용 사본**이지 정본이 아니다.

### 함정 3개

**① 클라이언트 히스토리를 안 버리면 조용히 중복 누적된다.**
체크포인터가 복원한 히스토리 **위에** 클라이언트가 보낸 같은 대화가 한 번 더 붙는다 —
`[u1,a1,u1,a1,u2]`. **에러가 안 난다.** 토큰 비용만 두 배가 되고 모델이 "방금 같은 말을 두 번
했다"고 착각할 뿐이다. `latest_user_text()`(`ai_sdk.py:43`)가 마지막 하나만 뽑는 이유다.

**② `astream`의 `config`는 2번째 위치 인자다.**
```python
astream(input, config=None, *, stream_mode=...)
```
`stream_mode`부터 키워드 전용이라 순서를 헷갈리면 `TypeError`로 바로 걸린다.

**③ `chunk.content`가 아니라 `chunk.text`.**
```python
AIMessageChunk(content=[{'type':'text','text':'AAA'}, {'type':'tool_use', ...}])
  .content -> list   # 도구 호출 / citations가 붙으면 리스트가 된다
  .text    -> 'AAA'  # 텍스트 블록만 이어붙여 항상 str
```
M2-2c에서 도구를 붙이는 순간 리스트로 바뀐다.

---

## 6. 층이 나뉜 덕에 앞으로 안 바뀌는 것

| 단계 | 바뀌는 파일 | 안 바뀌는 파일 |
|---|---|---|
| **2c** 도구 | `graph.py`만 | 나머지 전부 |
| **M3** RAG | `graph.py`(+`retrieve` 노드) · `rag/*` 신규 | `ai_sdk.py` · `chat.py` · 프론트 |
| **M4** 트레이싱 | `core/tracing.py` 신규 · `chat.py` 한 줄(`config`에 `callbacks` 추가) | 대부분 |
| **영속 체크포인터** | `deps.py` 한 줄(`AsyncPostgresSaver`) | `graph.py` · `chat.py` · 프론트 |

`ai_sdk.py`가 어느 줄에도 없다. M1-1c에서 `ui_message_stream(deltas: AsyncIterable[str])`로
"누가 토큰을 만드는가"를 인자로 밀어낸 설계가 2a·2b를 지나 계속 값을 하는 중이다.

**2b가 프론트까지 번진 유일한 단계였다.** 다른 단계는 백엔드 안에서 끝나는데, 2b는 클라이언트와
서버의 **역할 분담 자체**를 바꿨기 때문이다. 그 전환이 끝났으므로 2c부터는 다시 백엔드 안에서 끝난다.

### `config`가 확장 지점이다

`chat.py:51`의 `{"configurable": {"thread_id": ...}}`는 LangGraph 전용이 아니라 LangChain 공통의
`RunnableConfig`다. M4의 Langfuse `callbacks`, `tags`, `recursion_limit`이 전부 **같은 dict에**
들어간다 — 그래서 M4가 "`chat.py` 한 줄"로 끝난다.

---

## 7. 테스트가 어디를 끊어서 보는가

| 테스트 | 교체하는 것 | 검증 범위 | 개수 |
|---|---|---|---|
| [tests/test_chat.py](../backend/tests/test_chat.py) | `get_graph` → 가짜 모델 + **새 `InMemorySaver`** | 3~23번 전 구간 (Anthropic만 제외) | 21 |
| [transport.test.ts](../frontend/src/components/chat/transport.test.ts) | 없음 (순수 함수) | 2번 — **본문을 어떻게 조립하는가** | 3 |
| [App.test.tsx](../frontend/src/App.test.tsx) | 없음 (스모크) | 화면이 그려지는지만 | 1 |
| [capture-wire.mjs](../frontend/scripts/capture-wire.mjs) | 가짜 LLM | AI SDK가 만드는 **정답 바이트** 캡처 | — |

**같은 것을 두 곳에서 검증하지 않는다.** 와이어 포맷은 백엔드 테스트가 바이트 단위로, 요청 본문은
`transport.test.ts`가 순수 함수로, 화면은 `App.test.tsx`가 본다. 양쪽에서 검증하면 포맷이 바뀔 때
고칠 곳만 두 배가 된다.

### 2b에서 늘어난 5개 (16 → 21)

| 테스트 | 이게 없으면 놓치는 것 |
|---|---|
| `test_client_history_is_ignored` | 클라이언트가 보낸 히스토리가 중복 누적 (**2a의 `test_full_history_is_forwarded`를 대체 — 명세가 뒤집혔다**) |
| `test_second_turn_remembers_first` | 2b가 아예 동작 안 함 |
| `test_threads_are_isolated` | 남의 대화가 내 문맥에 섞임 |
| `test_checkpointer_stores_the_conversation` | "저장이 안 된 것"과 "저장은 됐는데 안 실리는 것"을 구분 못 함 |
| `test_last_message_must_be_user` | 재생성 요청이 조용히 중복 답변을 저장 |
| `test_real_graph_has_a_checkpointer` | **실제** 그래프에 체크포인터를 안 물려도 통과 |

체크포인터는 **fixture 안에서** 매번 새로 만든다. 모듈 레벨에 두면 테스트끼리 대화 상태가 새서
"단독 실행은 통과, 전체 실행은 실패"가 된다.

`capture-wire.mjs`는 테스트가 아니라 **정답지 생성기**다. `ai` 패키지 버전을 올리면 이걸 다시 돌려
`test_chat.py`의 `EXPECTED_SSE`와 대조한다.

---

## 8. 문제가 생겼을 때 어디를 보나

| 증상 | 먼저 볼 곳 |
|---|---|
| `Failed to fetch` | 서버가 떠 있는가 → `curl localhost:8000/api/v1/chat/health` |
| 422 | `transport.ts:18` — `id`·`trigger`·`messageId`를 빠뜨렸는가 (body는 병합이 아니라 **대체**다) |
| 400 `expected a non-empty user message` | 마지막 메시지가 user가 아니거나 텍스트 파트가 없다 |
| **이전 턴을 기억 못 함** | ① Network → Payload의 `id`가 매 요청 같은가 ② `deps.py:57`에 `checkpointer=`가 있는가 |
| **갑자기 기억을 잃음** | `--reload`가 재시작했다. `InMemorySaver`는 프로세스 메모리다 — 코드 문제가 아니다 |
| **새 대화인데 옛날 얘기를 함** | `Chat.tsx:127`이 `setMessages([])`로 되돌아갔는가 (화면만 비우고 서버는 그대로) |
| 남의 대화가 섞임 | `thread_id`가 겹쳤다 → `chat.py:51` |
| 200인데 화면이 백지 | 브라우저 콘솔 + `npx tsc -b` (렌더 중 런타임 에러) |
| 글자가 흐르지 않고 **툭** 나타남 | `deps.py:30` — `ChatAnthropic(streaming=True)` 확인 |
| EventStream 탭이 안 보임 | 응답 `content-type`이 `text/event-stream`인가 |

### 체크포인터를 직접 열어보는 법

```python
graph.get_state({"configurable": {"thread_id": "t-demo"}}).values["messages"]
```

손댄 적 없는 스레드는 `values == {}`다(실측). `test_checkpointer_stores_the_conversation`이
이 API를 그대로 쓴다.

### curl 2턴으로 백엔드만 끊어서 보기

브라우저가 이상할 때, 프론트 문제인지 서버 문제인지 먼저 가른다:

```bash
# 1턴
curl -s -N -X POST http://localhost:8000/api/v1/chat -H "Content-Type: application/json" \
  -d '{"id":"t-demo","messages":[{"id":"m1","role":"user","parts":[{"type":"text","text":"내 색은 teal이야"}]}],"trigger":"submit-message","messageId":"m1"}'

# 2턴 — 같은 id, 새 메시지만. 색을 기억하면 서버는 정상이다
curl -s -N -X POST http://localhost:8000/api/v1/chat -H "Content-Type: application/json" \
  -d '{"id":"t-demo","messages":[{"id":"m2","role":"user","parts":[{"type":"text","text":"내 색이 뭐라고?"}]}],"trigger":"submit-message","messageId":"m2"}'
```

**`id`를 다른 값으로 바꿔 한 번 더 돌려서 "모른다"고 답하는 것까지 확인한다.** 성공 케이스만으로는
체크포인터 덕인지 모델이 운 좋게 맞춘 것인지 구분할 수 없다.

---

## 갱신 규칙

이 문서는 **줄 번호를 포함**하므로 코드가 움직이면 어긋난다. 마일스톤이 끝날 때
(= [README.md](./README.md)의 체크박스를 채울 때) 함께 갱신한다.

줄 번호를 다시 뽑는 명령:

```bash
cd backend
grep -n "def \|async for\|yield\|return StreamingResponse\|raise HTTP\|config = " app/api/routes/chat.py
grep -n "^def \|^async def \|^UI_MESSAGE\|^DONE\|yield sse" app/core/ai_sdk.py
grep -n "class \|def \|add_node\|add_edge\|compile" app/graph.py
grep -n "^_model\|^_graph\|^_checkpointer\|^def \|^Graph" app/api/deps.py

cd ../frontend
grep -n "chatTransport\|useChat(\|function submit\|sendMessage(\|setChatId" src/components/chat/Chat.tsx
grep -n "export \|api:\|messages:" src/components/chat/transport.ts
```
