# 챗봇 요청 흐름 지도

> 메시지 하나가 브라우저에서 출발해 화면에 글자로 돌아오기까지, **어느 파일의 어느 줄을 지나는지**
> 정리한 문서다. 스터디 중 "이건 어디서 하는 거지?"가 생길 때 여기서 찾는다.
>
> **기준 시점: M2-2a 완료 (2026-08-26)** — 마일스톤이 끝날 때마다 갱신한다.
> 진행 순서와 각 단계의 결정·함정 기록은 [README.md](./README.md)에 있다.

---

## 1. 한 장으로 보는 흐름

```
[브라우저 :5173]                              [FastAPI :8000]
Chat.tsx
  sendMessage({ text })
     │
     ▼
DefaultChatTransport ───── POST /api/v1/chat ────▶ main.py        CORS → 라우터
  (히스토리 전체 JSON)                                   │
                                                         ▼
                                                   schemas/chat.py  본문 검증
                                                         │
                                                   deps.py          그래프 주입
                                                         │
                                                   routes/chat.py   변환 · 가드
                                                         │
                                                   graph.py         START→call_model→END
                                                         │
                                                   ChatAnthropic ──▶ Anthropic API
                                                         │
                                                   routes/chat.py   chunk.text 추출
                                                         │
                                                   core/ai_sdk.py   SSE 포맷
     ◀──────────── text/event-stream ────────────────────┘
useChat 파서 → messages[].parts → 화면 렌더
```

핵심은 **각 층이 옆 층의 관심사를 모른다**는 것이다.

- `core/ai_sdk.py`는 "누가 토큰을 만드는지" 모른다 → M2에서 LangGraph로 갈아탈 때 한 줄도 안 바뀌었다
- `graph.py`는 "HTTP"를 모른다 → 테스트에서 그래프만 따로 돌릴 수 있다
- `routes/chat.py`는 "SSE 바이트"를 모른다 → 와이어 포맷이 바뀌어도 라우터는 그대로다

---

## 2. 파일별 역할

| 파일 | 한 줄 역할 | 핵심 심볼 | 이 파일을 고칠 때 |
|---|---|---|---|
| [Chat.tsx](../frontend/src/components/chat/Chat.tsx) | 화면 · 입력 · 전송 | `transport`:16, `useChat`:29, `submit`:59 | UI/UX가 바뀔 때 |
| [client.ts](../frontend/src/api/client.ts) | 백엔드 **주소**만 관리 | `CHAT_API_URL`:12 | 엔드포인트가 늘 때 |
| [main.py](../backend/app/main.py) | CORS + 라우터 등록 | `add_middleware`:15, `include_router`:26 | 라우터 · 허용 오리진 추가 |
| [schemas/chat.py](../backend/app/schemas/chat.py) | 요청 본문의 **모양 계약** | `UIMessage`:12, `ChatRequest`:26 | 프론트 요청 포맷이 바뀔 때 |
| [api/deps.py](../backend/app/api/deps.py) | 무거운 객체 **1회 생성 + 주입** | `_model`:29, `get_graph`:39 | 모델 설정 · 테스트 교체 지점 |
| [api/routes/chat.py](../backend/app/api/routes/chat.py) | HTTP ↔ 그래프 **접착** | `chat`:26, `text_deltas`:41 | 토큰을 **어디서** 얻을지 바뀔 때 |
| [graph.py](../backend/app/graph.py) | 대화 **흐름** 정의 | `State`:15, `build_graph`:29 | 노드 · 엣지가 늘 때 |
| [core/ai_sdk.py](../backend/app/core/ai_sdk.py) | AI SDK **와이어 포맷** | `to_anthropic_messages`:43, `ui_message_stream`:80 | `ai` 패키지 버전이 바뀔 때 |
| [core/config.py](../backend/app/core/config.py) | 설정 · 시크릿 단일 소스 | `anthropic_model`, `anthropic_api_key` | 모델 교체 · 새 시크릿 |

---

## 3. 요청 경로 (올라가는 길)

| # | 위치 | 하는 일 | 실패하면 |
|---|---|---|---|
| 1 | `Chat.tsx:66` `sendMessage({text})` | 훅이 로컬 히스토리에 추가 | — |
| 2 | `DefaultChatTransport` (ai 패키지 내부) | `{id, messages, trigger, messageId}` JSON 조립 → `fetch` | `Failed to fetch` |
| 3 | `main.py:15` CORS 미들웨어 | Origin 검사 | CORS 에러 |
| 4 | `main.py:26` 라우터 | `/api/v1` + `/chat` 매칭 | 404 |
| 5 | `deps.py:39` `get_graph()` | 그래프 주입 (**테스트가 여기서 교체**) | — |
| 6 | `schemas/chat.py:26` `ChatRequest` | 본문 검증 (타입 · 필수 · Literal) | **422** |
| 7 | `chat.py:30` `to_anthropic_messages()` | `parts` → `{role, content}`, `system`·빈 텍스트 제거 | — |
| 8 | `chat.py:36` 가드 | 텍스트가 0개면 차단 | **400** |
| 9 | `chat.py:56` `return StreamingResponse` | **200 헤더 전송** | — |

### ⚠ 9번이 분기점이다

9번 **전에** 터지면 정상적인 4xx로 돌려줄 수 있다.
9번 **후에** 터지면 클라이언트에는 "200 헤더 + 빈 본문 + 연결 끊김"으로 보인다 — HTTP에서 가장
진단하기 어려운 실패 형태다.

`chat.py:30`의 변환과 `chat.py:36`의 가드가 **일부러 9번 앞에** 있는 이유가 이것이다.
async generator는 lazy해서 안에 넣으면 200이 나간 뒤에야 실행된다.

---

## 4. 응답 경로 (내려오는 길) — 200 이후

| # | 위치 | 하는 일 |
|---|---|---|
| 10 | `ai_sdk.py:89~95` | `start` → `start-step` → `text-start` 3개를 먼저 내보냄 |
| 11 | `chat.py:45` `graph.astream(stream_mode="messages")` | 그래프 실행 시작 |
| 12 | `graph.py:37` `call_model` | `model.ainvoke(state["messages"])` |
| 13 | `ChatAnthropic` (`streaming=True`) | Anthropic SSE 수신 → 콜백으로 토큰 방출 |
| 14 | `chat.py:45` | `(AIMessageChunk, metadata)` 2-튜플 수신 |
| 15 | `chat.py:54` `yield chunk.text` | 텍스트만 추출 |
| 16 | `ai_sdk.py:103` | `data: {"type":"text-delta","id":"0","delta":"..."}\n\n` |
| 17 | `ai_sdk.py:105~115` | `text-end` → `finish-step` → `finish` → `[DONE]` |
| 18 | `useChat` 파서 | `messages[].parts` 갱신 → 리렌더 |
| 19 | `Chat.tsx:136` | assistant면 `ReactMarkdown`, user면 문자열 그대로 |

**12~16번이 토큰 하나마다 반복된다.**

---

## 5. 데이터 모양이 바뀌는 지점

| 단계 | 모양 | 어디서 |
|---|---|---|
| 브라우저 상태 | `UIMessage { id, role, parts[] }` | `useChat` |
| HTTP 본문 | `{ id, messages[], trigger, messageId }` | `DefaultChatTransport` |
| 검증 후 | `ChatRequest` (Pydantic 객체) | `schemas/chat.py:26` |
| 변환 후 | `[{"role": ..., "content": ...}, ...]` | `ai_sdk.py:43` |
| **그래프 진입** | `HumanMessage` / `AIMessage` | **`add_messages`가 자동 변환** |
| 스트림 청크 | `(AIMessageChunk, metadata)` | `astream(stream_mode="messages")` |
| 델타 | `str` | `chunk.text` |
| 와이어 | `data: {...}\n\n` | `ai_sdk.py:69` |
| 화면 | `parts[]` → JSX | `Chat.tsx:135` |

### 함정 2개

**① `add_messages`가 dict를 알아서 변환한다.**
`{"role","content"}` dict를 넘기면 `HumanMessage`/`AIMessage`로 바꿔준다. 덕분에 M2에서
`ai_sdk.to_anthropic_messages()`를 안 고쳐도 됐다. **공짜로 얻은 건데, 모르면 "왜 되지?"가 된다.**

**② `chunk.content`가 아니라 `chunk.text`.**
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
| **2b** 체크포인터 | `graph.py` · `chat.py` · `schemas/chat.py` · **`Chat.tsx`** | `ai_sdk.py` |
| **2c** 도구 | `graph.py`만 | 나머지 전부 |
| **M3** RAG | `graph.py`(+`retrieve` 노드) · `rag/*` 신규 | `ai_sdk.py` · `chat.py` |
| **M4** 트레이싱 | `core/tracing.py` 신규 · `chat.py` 한 줄 | 대부분 |

`ai_sdk.py`가 어느 줄에도 없다. M1-1c에서 `ui_message_stream(deltas: AsyncIterable[str])`로
"누가 토큰을 만드는가"를 인자로 밀어낸 설계가 계속 값을 하는 중이다.

반대로 **2b만 유일하게 프론트엔드까지 번진다.** 다른 단계는 백엔드 안에서 끝나는데, 2b는
클라이언트와 서버의 **역할 분담 자체**를 바꾸기 때문이다 — 그래서 "아키텍처 전환점"이라 부른다.

---

## 7. 테스트가 어디를 끊어서 보는가

| 테스트 | 교체하는 것 | 검증 범위 |
|---|---|---|
| [tests/test_chat.py](../backend/tests/test_chat.py) | `get_graph` → 가짜 모델로 만든 그래프 | 3~19번 전 구간 (Anthropic만 제외) |
| [App.test.tsx](../frontend/src/App.test.tsx) | 없음 (스모크) | 화면이 그려지는지만 |
| [capture-wire.mjs](../frontend/scripts/capture-wire.mjs) | 가짜 LLM | AI SDK가 만드는 **정답 바이트** 캡처 |

**같은 것을 두 곳에서 검증하지 않는다.** 와이어 포맷은 백엔드 테스트가 바이트 단위로 보고,
프론트는 화면만 본다. 양쪽에서 검증하면 포맷이 바뀔 때 고칠 곳만 두 배가 된다.

`capture-wire.mjs`는 테스트가 아니라 **정답지 생성기**다. `ai` 패키지 버전을 올리면 이걸 다시 돌려
`test_chat.py`의 `EXPECTED_SSE`와 대조한다 (실제로 `ai` 7.0.73 → 7.0.79 때 그렇게 확인했다).

---

## 8. 문제가 생겼을 때 어디를 보나

| 증상 | 먼저 볼 곳 |
|---|---|
| `Failed to fetch` | 서버가 떠 있는가 → `curl localhost:8000/api/v1/chat/health` |
| 422 | `schemas/chat.py` — 프론트가 보낸 본문과 스키마가 어긋남 |
| 400 `no text content` | `ai_sdk.py:43` — 텍스트 파트가 전부 걸러졌다 |
| 200인데 화면이 백지 | 브라우저 콘솔 + `npx tsc -b` (렌더 중 런타임 에러) |
| 글자가 흐르지 않고 **툭** 나타남 | `deps.py:29` — `ChatAnthropic(streaming=True)` 확인 |
| EventStream 탭이 안 보임 | 응답 `content-type`이 `text/event-stream`인가 |
| 이전 대화를 기억 못 함 | 프론트가 히스토리 전체를 보내는가 (Network → Payload) |

---

## 갱신 규칙

이 문서는 **줄 번호를 포함**하므로 코드가 움직이면 어긋난다. 마일스톤이 끝날 때
(= [README.md](./README.md)의 체크박스를 채울 때) 함께 갱신한다.

줄 번호를 다시 뽑는 명령:

```bash
cd backend
grep -n "def \|async for\|yield\|return StreamingResponse\|raise HTTP" app/api/routes/chat.py
grep -n "^def \|^async def \|^UI_MESSAGE\|^DONE" app/core/ai_sdk.py
grep -n "class \|def \|add_node\|add_edge" app/graph.py
grep -n "^_model\|^_graph\|^def \|^Graph" app/api/deps.py
```
