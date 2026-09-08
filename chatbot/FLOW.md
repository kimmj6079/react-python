# 챗봇 요청 흐름 지도

> 메시지 하나가 브라우저에서 출발해 화면에 글자로 돌아오기까지, **어느 파일의 어느 줄을 지나는지**
> 정리한 문서다. 스터디 중 "이건 어디서 하는 거지?"가 생길 때 여기서 찾는다.
>
> **기준 시점: M4 코드 완료 (2026-09-07)** — 마일스톤이 끝날 때마다 갱신한다.
> (M4는 Langfuse 키 등록·대시보드 육안 확인만 남았고 배선은 끝났다.)
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
                                    ┌──────────────────────▼──────────────────────┐
                                    │  graph.py                                    │
                                    │   START → rewrite → retrieve → call_model ⇄ tools│
                                    │              │         │          │    ▲     │
                                    │              │         │          ▼    └ 결과 복귀│
                                    │              │         │         END          │
                                    │              │         │                      │
                                    │              │         ├─ retrieved_context(str)│
                                    │              │         └─ retrieved(청크 목록)  │
                                    │    ▲         └─ search_query (재작성본)        │
                                    │    └─ InMemorySaver (복원 · 저장)              │
                                    └──────┬───────────────────────┬───────────────┘
                                           │                       │
                                  rag/retriever.py           ChatAnthropic ──▶ Anthropic API
                                    ① 임베딩 (dense+sparse)         │
                                    ② 그라운딩 게이트 (M10)          │
                                    ③ 하이브리드 검색               │
                                    ④ 리랭킹 (rag/rerank.py)        │
                                           │                       │
                                  rag/factory.py             routes/chat.py  AIMessageChunk만 통과
                                    get_store()                    │         + sources() (M10)
                                     ╱        ╲              core/ai_sdk.py  SSE 포맷
                            pgvector_store  qdrant_store           │         + source_part (M10)
                                 │              │                  │
                            Postgres        Qdrant                 │
     ◀──────────── text/event-stream ──────────────────────────────┘
useChat 파서 → messages[].parts ─┬─ text          → 본문 렌더
                                 └─ source-document → Citations.tsx (인용 카드)
```

핵심은 **각 층이 옆 층의 관심사를 모른다**는 것이다.

- `core/ai_sdk.py`는 "누가 토큰을 만드는지" 모른다 → M2·M3 어디서도 한 줄 안 바뀌었다
- `graph.py`는 "HTTP"도 "어느 저장소인지"도 모른다 → 3-3c에서 Qdrant가 생겨도 안 바뀌었다
- `routes/chat.py`는 "SSE 바이트"를 모른다 → 와이어 포맷이 바뀌어도 라우터는 그대로다
- `call_model` 노드는 받은 메시지가 요청에서 온 것인지, 체크포인터가 복원한 것인지,
  방금 도구가 만든 것인지 모른다
- `rag/base.py`(계약)는 **아무것도 import하지 않는다** — 그게 "계약"의 실체다
- `tools.py`는 그래프도 HTTP도 모른다 → 그냥 파이썬 함수다
- **아무도 "관측되고 있다"는 것을 모른다**(M4) → 트레이싱을 꺼도 코드 경로가 똑같다

### M4의 트레이싱은 이 그림 "옆"이 아니라 "위"에 있다

위 흐름도에 `tracing.py`가 안 보이는 게 정상이다. Langfuse는 데이터가 지나가는 길목에 끼어드는
것이 아니라, `chat.py`가 `RunnableConfig`에 콜백을 하나 얹어두면 **LangChain이 그래프 안의 모든
노드·모델·도구 호출에 그 콜백을 자동으로 상속시킨다.** 그래서:

```
POST /chat ── config = { configurable, callbacks, metadata } ──▶ graph.astream(...)
                              │
                              └── 이 하나가 아래 전부에 상속된다
                                    retrieve → call_model → tools → call_model
                                       │          │          │
                                       └──────────┴──────────┴──▶ Langfuse (비동기 배치 전송)
```

- **노드마다 계측 코드를 심을 일이 없다** — `graph.py`에 Langfuse라는 단어가 없다
- **트레이스 전송은 요청 응답과 분리돼 있다**(백그라운드 스레드 + 배치) — 사용자는 기다리지 않는다
- **키가 없으면 `callbacks`가 빈 리스트라 LangChain이 콜백을 아예 안 부른다** → 오버헤드 0

### M2~M4에서 바뀐 것 일곱 줄

| | 무엇이 바뀌었나 |
|---|---|
| **2a** | 토큰을 만드는 주체가 Anthropic 직접 호출 → LangGraph 그래프 (동작 완전 동일) |
| **2b** | **대화를 기억하는 주체**가 브라우저 → 서버(체크포인터). 프론트는 `thread_id` + 새 메시지 1개만 |
| **2c** | 그래프가 **직선에서 분기+사이클로**. 모델이 도구를 쓸지 스스로 정한다 |
| **3-1/3-2a** | 문서 → 청킹 → 임베딩 → pgvector 저장, 그리고 유사도 검색 |
| **3-2b** | 그래프 앞에 **`retrieve` 노드**. 매 턴 무조건 검색해 시스템 프롬프트로만 잠깐 쓴다 |
| **3-3/3-4** | 저장소가 **계약 하나 · 구현 둘**(pgvector/Qdrant). `deps.py` 한 줄로 갈아끼운다 |
| **M4** | 그래프 전체가 **Langfuse로 트레이싱**된다. `chat.py`의 `config`에 두 키를 더한 것이 전부 |
| **M6** | 흐름은 안 바뀌고 **평가 하네스**(`evals/`)가 옆에 생겼다. 이후 모든 변경의 판정 기준 |
| **M7** | 청킹이 "600자 자르기"에서 **구조 인식**으로. `heading_path`가 청크마다 붙는다 |
| **M8** | 검색이 **2단**이 됐다: 하이브리드(dense+BM25 RRF)로 넓게 → LLM 리랭킹으로 좁게 |
| **M9** | 그래프 맨 앞에 **`rewrite` 노드**. "그거 프로덕션에서는?"을 홀로 서는 질문으로 바꾼다 |
| **M10** | 근거를 **화면에 낸다**(인용 카드) + 근거가 약하면 컨텍스트를 비운다(그라운딩 게이트) |
| **M11** | 문서 인입이 **API**가 됐다. 업로드 · 멱등 업서트 · 백그라운드 잡 |
| **M12** | 검색에 **권한 필터**가 필수 인자로 들어간다. `Principal`이 요청부터 저장소까지 관통 |

---

## 2. 파일별 역할

### 요청을 처리하는 길

| 파일 | 한 줄 역할 | 핵심 심볼 | 이 파일을 고칠 때 |
|---|---|---|---|
| [Chat.tsx](../frontend/src/components/chat/Chat.tsx) | 화면 · 입력 · **세션 id 소유** | `useChat`:44, `submit`:75, `<Citations>`:180 | UI/UX가 바뀔 때 |
| [Citations.tsx](../frontend/src/components/chat/Citations.tsx) | **인용 카드** (M10) | `Citations`:17 | 출처를 어떻게 보여줄지 |
| [transport.ts](../frontend/src/components/chat/transport.ts) | **무엇을 보낼지**(와이어 계약) | `prepareChatRequest`:18, `chatTransport`:44 | 요청 본문이 바뀔 때 |
| [client.ts](../frontend/src/api/client.ts) | 백엔드 **주소**만 관리 | `CHAT_API_URL`:12 | 엔드포인트가 늘 때 |
| [main.py](../backend/app/main.py) | CORS + 라우터 등록 | `add_middleware`:15, `include_router`:26 | 라우터 · 허용 오리진 추가 |
| [schemas/chat.py](../backend/app/schemas/chat.py) | 요청 본문의 **모양 계약** | `UIMessage`:12, `ChatRequest`:26 | 프론트 요청 포맷이 바뀔 때 |
| [api/deps.py](../backend/app/api/deps.py) | 무거운 객체 **1회 생성 + 주입** + **검색 전략 조립** | `get_principal`:27, `_model`:62, `_checkpointer`:87, `_store`:97, `_retrieve`:100, `_rewrite`:143, `get_graph`:160 | 모델 · 저장소 교체, 검색 단계 추가 |
| [api/routes/chat.py](../backend/app/api/routes/chat.py) | HTTP ↔ 그래프 **접착** + **스트림 필터** | `chat`:29, `text_deltas`:76, `sources`:110 | 무엇을 화면에 내보낼지 바뀔 때 |
| [graph.py](../backend/app/graph.py) | 대화 **흐름** 정의 | `SYSTEM_PROMPT_TEMPLATE`:53, `NO_CONTEXT_PROMPT`:81, `State`:100, `build_graph`:148, `rewrite`:186, `retrieve`:221, `call_model`:261 | 노드 · 엣지가 늘 때 |
| [tools.py](../backend/app/tools.py) | 모델이 쓸 수 있는 **능력** | `get_current_time`:14, `TOOLS`:34 | 도구를 추가·수정할 때 |
| [core/ai_sdk.py](../backend/app/core/ai_sdk.py) | AI SDK **와이어 포맷** | `latest_user_text`:43, `sse`:75, `source_part`:86, `ui_message_stream`:122 | `ai` 패키지 버전이 바뀔 때 |
| [core/config.py](../backend/app/core/config.py) | 설정 · 시크릿 단일 소스 | `vector_store`, `hybrid_search`, `rerank_enabled`, `query_rewrite_enabled`, `grounding_max_distance`, `langfuse_enabled` | 모델 교체 · 기능 on/off · 새 시크릿 |
| [core/tracing.py](../backend/app/core/tracing.py) | **관측성** 배선 (M4) | `get_langfuse_client`:32, `get_callbacks`:49, `trace_metadata`:72 | 트레이싱 대상 · 꼬리표가 바뀔 때 |

### RAG — `app/rag/` (M3에서 생긴 층)

| 파일 | 한 줄 역할 | 핵심 심볼 | 무엇을 아는가 |
|---|---|---|---|
| [rag/base.py](../backend/app/rag/base.py) | **계약**. import가 없다 | `EMBEDDING_DIM`:35, `TOP_K`:42, `HYBRID_CANDIDATES`:48, `Chunk`:52, `RetrievedChunk`:79, `VectorStore`:110, `HybridStore`:170 | 아무것도 |
| [rag/access.py](../backend/app/rag/access.py) | **누가 요청했나** (M12) | `PUBLIC_ROLE`:18, `Principal`:25 | 권한 모델이 바뀔 때 |
| [rag/embedding.py](../backend/app/rag/embedding.py) | 임베딩 모델 단일 소스 (dense + sparse) | `MODEL_NAME`:18, `embed_passages`:36, `embed_query`:45, `SPARSE_MODEL_NAME`:72, `embed_sparse_query`:94 | fastembed |
| [rag/chunking.py](../backend/app/rag/chunking.py) | **구조 인식 청킹** (M7) | `MAX_TOKENS`:41, `MIN_TOKENS`:51, `token_length`:89, `heading_path_of`:94, `split_markdown`:131 | 청킹 전략이 바뀔 때 |
| [rag/factory.py](../backend/app/rag/factory.py) | **어느 저장소인가**를 정하는 유일한 곳 | `_BUILDERS`:18, `get_store`:24, `pop_store_arg`:38 | 구현 둘 다 |
| [rag/pgvector_store.py](../backend/app/rag/pgvector_store.py) | Postgres 구현 | `upsert_document`:28, `search`:71 | SQLAlchemy |
| [rag/qdrant_store.py](../backend/app/rag/qdrant_store.py) | Qdrant 구현 (+ 하이브리드) | `_ensure_collection`:68, `_create_access_indexes`:106, `upsert_document`:149, `_access_filter`:232, `search`:251, `search_hybrid`:272 | qdrant-client |
| [rag/retriever.py](../backend/app/rag/retriever.py) | 임베딩 → **게이트** → 검색 (짝 규칙) | `retrieve`:23 | 계약만 |
| [rag/rerank.py](../backend/app/rag/rerank.py) | LLM으로 **다시 줄 세우기** (M8) | `Relevance`:21, `_score`:49, `rerank`:71 | 정밀도를 손볼 때 |
| [rag/rewrite.py](../backend/app/rag/rewrite.py) | 대화형 질문 → **홀로 서는 질문** (M9) | `Rewritten`:24, `format_history`:50, `rewrite_query`:55 | 대화 맥락 처리 |
| [rag/ingest.py](../backend/app/rag/ingest.py) | 파일 → 청킹 → 임베딩 → store | `REPO_ROOT`:25, `ingest_text`:42, `insert_file`:129 | 계약만 |
| [rag/documents.py](../backend/app/rag/documents.py) | 업로드 **파싱 · 멱등 업서트** (M11) | `ALLOWED_SUFFIXES`:23, `parse`:26, `content_hash`:74, `run_ingest`:78, `upsert_record`:113 | 새 파일 형식 |

**저장소를 아는 파일은 정확히 셋이다** — `pgvector_store.py`(Postgres를 안다),
`qdrant_store.py`(Qdrant를 안다), `factory.py`(둘을 안다). 나머지 전부는 계약만 본다.

### `tools.py`와 `rag/`를 `graph.py` 밖에 둔 이유

도구도 검색도 **그래프의 구조**가 아니라 **그래프가 손을 뻗는 바깥 세상**이다.
`graph.py`를 열었을 때 "대화 흐름"을 보러 왔는데 Qdrant 코드를 읽게 되면 안 된다.
덤으로 모듈 레벨 함수·클래스라 그래프 없이 단독으로 테스트·실행된다
(`uv run python -m app.rag.retriever "질문"`).

---

## 3. 요청 경로 (올라가는 길)

| # | 위치 | 하는 일 | 실패하면 |
|---|---|---|---|
| 1 | `Chat.tsx:81` `sendMessage({text})` | 훅이 로컬 히스토리에 추가 | — |
| 2 | `transport.ts:18` `prepareChatRequest` | **본문을 직접 조립** — `messages`를 `slice(-1)`로 1개만 | `id`·`trigger` 누락 시 **422** |
| 3 | `main.py:15` CORS 미들웨어 | Origin 검사 | CORS 에러 |
| 4 | `main.py:26` 라우터 | `/api/v1` + `/chat` 매칭 | 404 |
| 5 | `deps.py:89` `get_graph()` | 그래프 주입 (**테스트가 여기서 교체**) | — |
| 6 | `schemas/chat.py:26` `ChatRequest` | 본문 검증 (타입 · 필수 · Literal) | **422** |
| 7 | `chat.py:31` `latest_user_text()` | **마지막 user 메시지 하나만** 추출 | — |
| 8 | `chat.py:37` 가드 | 텍스트가 없거나 마지막이 user가 아니면 차단 | **400** |
| 9 | `chat.py:64` `config` | `payload.id` → `thread_id` (**어느 대화인가**) + `callbacks`·`metadata`(M4) | — |
| 10 | `chat.py:104` `return StreamingResponse` | **200 헤더 전송** | — |

### ⚠ 10번이 분기점이다

10번 **전에** 터지면 정상적인 4xx로 돌려줄 수 있다.
10번 **후에** 터지면 클라이언트에는 "200 헤더 + 빈 본문 + 연결 끊김"으로 보인다 — HTTP에서 가장
진단하기 어려운 실패 형태다.

`chat.py:31`의 추출과 `chat.py:37`의 가드가 **일부러 10번 앞에** 있는 이유가 이것이다.
async generator는 lazy해서 안에 넣으면 200이 나간 뒤에야 실행된다.

**`graph.py:243`의 `except Exception`도 같은 이유로 존재한다** — 검색은 10번 뒤에 일어나므로,
DB가 죽었을 때 예외를 그대로 올리면 정확히 저 진단 불가능한 실패가 된다.
`graph.py:207`(재작성 실패)과 `rerank.py`의 폴백도 전부 같은 판단이다.

> ★ 이 관용구의 대가를 M9~M10에서 실제로 치렀다 ★ Anthropic 크레딧이 소진됐을 때
> 재작성도 리랭킹도 **조용히 폴백**해서 앱은 200을 계속 돌려줬다. 챗봇이 안 죽은 것은
> 설계대로였지만, **품질이 조용히 떨어진 것을 로그를 볼 때까지 몰랐다.**
> 실무라면 여기에 메트릭이 붙는다 — "폴백이 몇 % 발생했나"를 대시보드에서 보고
> 임계치를 넘으면 알람이 울려야 한다. **조용한 폴백은 조용한 장애다.**

---

## 4. 응답 경로 (내려오는 길) — 200 이후

**모든 턴이 검색을 거친다**(3-2b). 그 뒤 도구를 쓰느냐 아니냐는 **모델이 정한다**(2c).

### 공통 — 검색부터 모델 호출까지

| # | 위치 | 하는 일 |
|---|---|---|
| 11 | `ai_sdk.py:131~140` | `start` → `start-step` → `text-start` 3개를 먼저 내보냄 |
| 12 | `chat.py:89` `graph.astream(input, config, stream_mode="messages")` | 그래프 실행 시작 |
| 13 | **`InMemorySaver`** | `thread_id`로 **이전 대화 복원** |
| 14 | `graph.py:118` `add_messages` 리듀서 | 복원된 히스토리 **뒤에** 새 메시지를 이어붙임 |
| 15 | `graph.py:186` **`rewrite` 노드** (M9) | 히스토리가 있으면 LLM으로 질문을 홀로 서게 다시 쓴다. **첫 턴이면 LLM을 아예 안 부른다** |
| 16 | `graph.py:216` | `{"search_query": ...}` — 원문은 `messages`에 그대로 둔다 (**두 값이 다른 일을 한다**) |
| 17 | `graph.py:221` **`retrieve` 노드** | `state["search_query"]`(없으면 원문)가 검색어 |
| 18 | `graph.py:236~239` `iscoroutinefunction` 분기 | 리랭킹이 켜지면 `retrieve_fn`이 코루틴이다 — async면 `await`, 동기면 `to_thread` |
| 19 | `deps.py:100` `_retrieve` | **검색 전략을 조립하는 곳.** 게이트 · 후보 수 · 리랭킹 on/off |
| 20 | `retriever.py:23` `retrieve()` ① | `embed_query` — 임베딩은 **여기서 한 번만** |
| 21 | `retriever.py` **그라운딩 게이트** ② (M10) | `store.search(top_k=1)`의 **dense 거리**가 `grounding_max_distance`(0.18)보다 멀면 **`[]` 반환** |
| 22 | `qdrant_store.py:272` `search_hybrid` ③ (M8) | dense + BM25를 각각 뽑아 **RRF로 융합**. `_access_filter`(M12)가 두 prefetch **양쪽에** 걸린다 |
| 23 | `rerank.py:71` `rerank()` ④ (M8-b) | 후보 20개를 LLM이 0~10점으로 **병렬** 채점해 다시 줄 세운다 |
| 24 | `graph.py:90` `_format_context` | `[출처: X]\n내용` 으로 이어붙임 (**비면 빈 문자열**) |
| 25 | `graph.py:259` | `{"retrieved_context": ..., "retrieved": chunks}` — **`messages`에는 안 넣는다.** `retrieved`는 M10 인용 카드의 재료 |
| 26 | `graph.py:268~275` `call_model` | 컨텍스트가 있으면 `SYSTEM_PROMPT_TEMPLATE`(`<documents>`로 감쌈, M12), **없으면 `NO_CONTEXT_PROMPT`**(M10)를 맨 앞에 잠깐 붙임 |
| 27 | `graph.py:184` `bind_tools` 효과 | 요청에 **도구 설명서**(`tools` 파라미터)가 함께 실려 나감 |
| 28 | `ChatAnthropic` (`streaming=True`) | Anthropic SSE 수신 → 콜백으로 토큰 방출 |

**19~23번이 M8~M12에서 자란 부분이다.** 흐름도에서는 노드 하나(`retrieve`)인데 그 안이
4단계다 — 그리고 **`graph.py`는 그중 아무것도 모른다.** `retrieve_fn` 하나만 안다.

### 경로 A — 모델이 그냥 답한 경우

| # | 위치 | 하는 일 |
|---|---|---|
| 29 | `graph.py:314` `tools_condition` | `tool_calls`가 비었다 → **`"__end__"`** |
| 30 | `chat.py:102` 필터 | `AIMessageChunk`이므로 통과 |
| 31 | `chat.py:108` `yield chunk.text` | 텍스트만 추출 |
| 32 | `ai_sdk.py:148` | `data: {"type":"text-delta",...}\n\n` |
| 33 | `ai_sdk.py` `text-end` 직후 (M10) | **`sources_fn()` 호출** |
| 34 | `chat.py:110` `sources()` | `graph.get_state(config).values["retrieved"]`에서 **이번 턴이 실제로 본 청크**를 꺼내 `sourceId`로 중복 제거 |
| 35 | `ai_sdk.py:86` `source_part` | `{"type":"source-document","sourceId":...,"title":heading_path,...}` |
| 36 | `Citations.tsx:18` | `message.parts`에서 `source-document`만 골라 카드로 렌더 |

**33~34번의 순서가 M10 설계의 핵심이다.** 인용 데이터는 그래프가 다 돌아야 알 수 있는데
`ui_message_stream`은 그보다 **먼저** 만들어진다. 그래서 값이 아니라 **함수**(`sources_fn`)를
넘긴다 — 값을 넘기면 항상 빈 리스트가 되고, 그러면 **에러 없이 인용 카드만 안 나온다.**

### 경로 B — 모델이 도구를 부른 경우 ("서울 지금 몇 시야?")

| # | 위치 | 하는 일 |
|---|---|---|
| 29 | Anthropic | 텍스트 대신 **`tool_use` 블록** → 청크의 `.text`가 전부 `''` |
| 30 | `graph.py:314` `tools_condition` | `tool_calls`가 있다 → **`"tools"`** |
| 31 | `graph.py:295` `ToolNode` | `tools.py`의 **진짜 함수를 실행** |
| 32 | `chat.py:102` 필터 | **`ToolMessage`라서 `continue`** ← 여기서 막지 않으면 화면에 샌다 |
| 33 | `graph.py:321` `add_edge("tools","call_model")` | **사이클** — 결과를 들고 모델로 복귀 |
| 34 | `graph.py:261` `call_model` (2회차) | 도구 결과가 포함된 히스토리로 다시 호출 |
| 35 | `chat.py:108` | 이번엔 진짜 텍스트가 나온다 → `yield` |

**사이클은 `rewrite`도 `retrieve`도 다시 거치지 않는다** (`graph.py:321`이 `call_model`로 직행).
재작성과 검색은 "이번 턴 사용자의 질문"에 대한 것이라 **턴당 한 번씩**이면 된다.

> ★ M10에서 이 경로가 한 번 죽을 뻔했다 ★ 그라운딩을 "검색 점수가 낮으면 고정 거절문을
> 내고 END로 간다"는 **조기 반환 노드**로 만들 계획이었다. 그렇게 했으면 "서울 지금 몇 시야?"는
> 검색 결과가 당연히 비므로 **도구를 부르기도 전에 거절**된다 — 경로 B가 통째로 죽는다.
> 그래서 흐름을 끊는 대신 `NO_CONTEXT_PROMPT`로 **판단을 모델에게 넘겼다.**
> 그래프에 분기를 넣을 때는 "이 분기가 기존 경로 중 무엇을 막는가"를 먼저 봐야 한다.

### 공통 — 마무리

| # | 위치 | 하는 일 |
|---|---|---|
| 31 | **`InMemorySaver`** | 갱신된 대화 저장 (도구 왕복까지 통째로, **컨텍스트는 제외**) |
| 32 | `ai_sdk.py:111~118` | `text-end` → `finish-step` → `finish` → `[DONE]` |
| 33 | `useChat` 파서 | `messages[].parts` 갱신 → 리렌더 |
| 34 | `Chat.tsx:168` | assistant면 `ReactMarkdown`, user면 문자열 그대로 |

**경로 B에서 모델을 두 번 부른다** — 토큰 비용도 지연도 대략 두 배다. 도구를 붙이는 것이
공짜가 아니라는 뜻이고, M13의 지연 예산 표에서 이 비용을 실제로 계측한다.

---

## 5. 데이터 모양이 바뀌는 지점

| 단계 | 모양 | 어디서 |
|---|---|---|
| 브라우저 상태 | `UIMessage { id, role, parts[] }` **전체 히스토리** | `useChat` |
| HTTP 본문 | `{ id, messages: [마지막 1개], trigger, messageId }` | `transport.ts:35` |
| 검증 후 | `ChatRequest` (Pydantic 객체) | `schemas/chat.py:26` |
| 추출 후 | `str` (마지막 user 발화) | `ai_sdk.py:43` |
| 그래프 입력 | `{"messages": [{"role":"user","content": text}]}` | `chat.py:70` |
| **그래프 내부** | 복원된 히스토리 + 새 메시지 (`HumanMessage`/`AIMessage`/**`ToolMessage`**) | 체크포인터 + `add_messages` |
| **질문 벡터** | `list[float]` (1024차원, `"query: "` 접두어) | `embedding.py:45` |
| **검색 결과** | `list[RetrievedChunk]` — 저장소 중립 | `base.py:35` |
| **컨텍스트** | `str` (`[출처: X]\n내용` 을 `\n\n`으로 연결) | `graph.py:47` |
| **모델 입력** | `[SystemMessage(컨텍스트), *messages]` — **일회용 새 리스트** | `graph.py:165` |
| **API 요청** | messages + **`tools`(도구 설명서 JSON Schema)** | `bind_tools` |
| 스트림 청크 | `(AIMessageChunk \| ToolMessage, metadata)` | `astream(stream_mode="messages")` |
| 델타 | `str` | `chunk.text` |
| 와이어 | `data: {...}\n\n` | `ai_sdk.py:75` |
| 화면 | `parts[]` → JSX | `Chat.tsx:168` |

**"브라우저 상태"와 "HTTP 본문"이 어긋난다**(2b). 화면에는 대화 전체가 있지만 서버로는 마지막
하나만 간다 — 화면의 히스토리는 **표시용 사본**이지 정본이 아니다.

**"그래프 내부"에는 화면에 없는 것이 있다**(2c). 도구 호출과 그 결과(`AIMessage(content="")` +
`ToolMessage`)가 히스토리에 쌓이지만 사용자는 못 본다.

**"모델 입력"에는 체크포인터에 없는 것이 있다**(3-2b). 시스템 메시지는 매 턴 새로 조립되고
버려진다 — `messages`에 넣지 않으므로 저장되지 않는다.

### 저장소별 저장 모양 (M3-3)

| | pgvector | Qdrant |
|---|---|---|
| 단위 | `document_chunks` 테이블의 행 | 컬렉션의 point |
| 키 | `id`(serial) + `(source, chunk_index)` 컬럼 | **`uuid5(NAMESPACE_URL, f"{source}#{i}")`** |
| 벡터 | `embedding vector(1024)` 컬럼 | point의 `vector` |
| 원문·메타 | `source`/`chunk_index`/`content` 컬럼 | `payload` dict (스키마 없음) |
| 거리 | `cosine_distance` — **낮을수록 가깝다** | `score` — **높을수록 가깝다** |
| 계약으로 변환 | 그대로 | **`distance = 1.0 - score`** (`qdrant_store.py:150`) |

### 함정 7개

**① 클라이언트 히스토리를 안 버리면 조용히 중복 누적된다.**
체크포인터가 복원한 히스토리 **위에** 클라이언트가 보낸 같은 대화가 한 번 더 붙는다 —
`[u1,a1,u1,a1,u2]`. **에러가 안 난다.** 토큰 비용만 두 배가 되고 모델이 착각할 뿐이다.

**② `ToolMessage`가 스트림으로 샌다.**
`stream_mode="messages"`는 이름 그대로 "메시지"를 흘리지 LLM 토큰만 준다고 약속한 적이 없다.
`chat.py:96`에서 `isinstance(chunk, AIMessageChunk)`로 막는다. **안 막으면 채팅창에
`2026-08-27T11:46:37+09:00` 같은 원시 결과가 찍힌다 — 에러도 없고 200도 정상이다.**

**③ `content`는 도구를 쓰든 안 쓰든 **항상** 리스트다.**
```python
AIMessageChunk(content=[{'type':'text','text':'AAA'}, {'type':'tool_use', ...}])
  .content -> list   # bind_tools를 한 순간부터 늘 이렇다(실측)
  .text    -> 'AAA'  # 텍스트 블록만 이어붙여 항상 str
```

**④ `astream`의 `config`는 2번째 위치 인자다.** `astream(input, config=None, *, stream_mode=...)`

**⑤ 검색 결과를 `messages`에 넣으면 매 턴 쌓인다.**(3-2b) `{"messages":[SystemMessage(...)]}`를
반환하는 게 가장 쉬운 구현인데, 그러면 10턴 뒤 프롬프트에 청크 50개가 실려 나간다.
**에러도 경고도 없다.** 그래서 `retrieved_context`라는 별도 State 필드(리듀서 없음 = 덮어쓰기)를 쓴다.

**⑥ Qdrant는 자연 키를 못 쓴다.**(3-3b 실측) point id는 unsigned int 또는 UUID뿐이라
`"CLAUDE.md#0"`은 **400**이다. `uuid5`(결정론적)를 써야 재인입이 덮어쓰기가 되고,
`uuid4`(랜덤)를 쓰면 **에러 없이 중복이 쌓인다.**

**⑦ Qdrant에는 트랜잭션이 없다.**(3-3c) `delete` → `upsert` 사이에 그 문서가 검색에서
통째로 사라지는 창이 실제로 존재한다. pgvector에는 없던 문제다. 무중단 재인입은
`update_collection_aliases`(새 컬렉션 + alias 교체)로 한다.

---

## 6. 조건분기는 우리가 하지 않는다 (2c의 핵심)

`tools_condition`의 실제 본문은 이것뿐이다:

```python
if hasattr(ai_message, "tool_calls") and len(ai_message.tool_calls) > 0:
    return "tools"
return "__end__"
```

**키워드 매칭도 정규식도 없다.** 판단은 Anthropic 서버에서 **모델이** 하고, 근거는 우리가
`bind_tools`로 보낸 `description`이다. 우리 코드는 이미 나온 결과를 읽을 뿐이다.

**그래서 세 가지가 따라온다.**

1. **도구를 안 부르면 로직이 아니라 `tools.py:14`의 docstring을 고친다.** 그 글이 판단 근거의 전부다.
2. **확률적이다.** 같은 질문에도 다르게 행동할 수 있다 → **도구 경로 테스트에 진짜 모델을 쓰면 안 된다.**
3. **강제할 수는 있다.** `bind_tools(tools, tool_choice="any")`. 다만 "안녕"에도 도구를 부르게 된다.

### 반대로, 검색은 우리가 정한다 (3-2b의 핵심)

`retrieve`는 조건부 엣지가 아니라 `START → retrieve` **고정 엣지**다. 검색을 `@tool`로 만들어
모델에게 맡기는 선택지(*agentic RAG*)가 있었지만 안 골랐다 — **M6 계측기가 없는 지금은
결정론이 압도적으로 중요하다.** 검색이 확률적으로 일어나면 "답이 나빴다"의 원인이 검색 품질인지
모델이 검색을 건너뛴 것인지 구분할 수 없다.

**즉 이 그래프에는 성격이 다른 두 종류의 엣지가 있다** — 우리가 정한 것(`START→retrieve`,
`retrieve→call_model`, `tools→call_model`)과 모델이 정하는 것(`call_model→?`).

---

## 7. 층이 나뉜 덕에 앞으로 안 바뀌는 것

| 단계 | 바뀌는 파일 | 안 바뀌는 파일 |
|---|---|---|
| **M4** 트레이싱 ✅ | `core/tracing.py` 신규 · `chat.py`의 `config`에 두 키 | `graph.py` · `ai_sdk.py` · `rag/*` · 프론트 |
| **M6** 평가 하네스 | `evals/*` 신규 (`app/` 밖) | `app/` 전부 |
| **M7** 청킹 | `rag/chunking.py` 신규 · `ingest.py` | **`base.py` 계약 · 두 store · `graph.py`** |
| **M8** 하이브리드 | `rag/hybrid.py`·`rerank.py` · **계약에 sparse가 들어올 수 있다** | `chat.py` · `ai_sdk.py` · 프론트 |
| **영속 체크포인터** | `deps.py` 한 줄(`AsyncPostgresSaver`) | `graph.py` · `chat.py` · 프론트 |
| **저장소 교체** | `deps.py`는 그대로, **`.env`의 `VECTOR_STORE` 한 줄** | 전부 |
| **저장소 추가** | `rag/새_store.py` 신규 + `factory.py:18`의 dict 한 줄 | 나머지 전부 |
| **도구 추가** | `tools.py`의 `TOOLS` 목록 한 줄 | 나머지 전부 |

`ai_sdk.py`가 어느 줄에도 없다. M1-1c에서 `ui_message_stream(deltas: AsyncIterable[str])`로
"누가 토큰을 만드는가"를 인자로 밀어낸 설계가 M2·M3 내내 값을 했다.

**M3에서 프론트가 한 줄도 안 바뀌었다.** 2b가 프론트까지 번진 유일한 단계였고, 그건 클라이언트와
서버의 역할 분담 자체를 바꿨기 때문이다. RAG는 서버 안쪽의 일이라 밖으로 새지 않는다.

### `config`가 확장 지점이다

`chat.py:64`의 dict는 LangGraph 전용이 아니라 LangChain 공통의 `RunnableConfig`다.
**M4가 예고대로 여기 두 키를 더한 것으로 끝났다** — `callbacks`(Langfuse 핸들러)와
`metadata`(`langfuse_session_id`). `tags`·`recursion_limit`도 같은 dict에 들어간다.

```python
config = {
    "configurable": {"thread_id": payload.id},  # 2b — 어느 대화인가
    "callbacks": get_callbacks(),  # M4 — 키가 없으면 [] (no-op)
    "metadata": trace_metadata(payload.id),  # M4 — {"langfuse_session_id": ...}
}
```

**그래프 안의 모든 노드·모델·도구 호출이 이 콜백을 자동으로 상속한다.** 노드마다 계측 코드를
심을 일이 없다는 뜻이고, 그게 `RunnableConfig`에 배선한 값이다.

### `build_graph`의 시그니처가 확장 지점이다

```python
build_graph(model, retrieve_fn, checkpointer=None, tools=None)
```
네 개가 전부 **인자**다. 테스트가 넷을 다 갈아끼울 수 있고(→ 8절), 운영 코드가 넷을 다
갈아끼울 수 있다(→ `deps.py`). **`retrieve_fn`만 기본값이 없는 것**도 의도다 — 기본값이
조용히 진짜 DB를 부르면 이 인자를 깜빡한 새 테스트가 CI에서 실제 Postgres를 두드린다.

---

## 8. 테스트가 어디를 끊어서 보는가

| 테스트 | 교체하는 것 | 검증 범위 | 개수 |
|---|---|---|---|
| [tests/test_chat.py](../backend/tests/test_chat.py) | `get_graph` → 가짜 모델 + 새 `InMemorySaver` + 가짜 `retrieve_fn` | 3~34번 전 구간 (Anthropic·저장소만 제외) | 22 |
| [tests/test_rag_store.py](../backend/tests/test_rag_store.py) | 없음 (모양·규칙만) | 계약 준수 · 팩토리 · CLI 플래그 | 9 |
| [tests/test_tracing.py](../backend/tests/test_tracing.py) | `settings`의 키를 monkeypatch | 켜짐/꺼짐 분기 · 싱글턴 · 메타데이터 키 | 6 |
| [tests/test_ingest.py](../backend/tests/test_ingest.py) | 없음 (순수 함수) | `chunk_text` 경계 | 4 |
| [tests/test_items.py](../backend/tests/test_items.py) · [test_health.py](../backend/tests/test_health.py) | SQLite 인메모리 | 기존 CRUD | 5 |
| [transport.test.ts](../frontend/src/components/chat/transport.test.ts) | 없음 (순수 함수) | 2번 — 본문 조립 | 3 |
| [App.test.tsx](../frontend/src/App.test.tsx) | 없음 (스모크) | 화면이 그려지는지만 | 1 |
| [capture-wire.mjs](../frontend/scripts/capture-wire.mjs) | 가짜 LLM | AI SDK의 **정답 바이트** 캡처 | — |
| [probe_tools.py](../backend/scripts/probe_tools.py) · [probe_embedding.py](../backend/scripts/probe_embedding.py) · [probe_qdrant.py](../backend/scripts/probe_qdrant.py) · [probe_langfuse.py](../backend/scripts/probe_langfuse.py) | 없음 (실측용) | 라이브러리 실제 동작 | — |
| [compare_stores.py](../backend/scripts/compare_stores.py) | 없음 (관찰용) | 두 저장소가 같은 답을 주는가 | — |

**백엔드 합계 46.** 같은 것을 두 곳에서 검증하지 않는다 — 와이어 포맷은 백엔드 테스트가
바이트로, 요청 본문은 `transport.test.ts`가 순수 함수로, 화면은 `App.test.tsx`가 본다.

### ★ pytest는 실제 DB·임베딩·LLM·Qdrant를 절대 부르지 않는다 ★

`ci.yml`이 이 테스트들을 그대로 돌리기 때문이다(비용·플래키·시크릿). 그래서:

- 챗봇 경로는 `get_graph`를 통째로 교체한다
- 검색은 `retrieve_fn`을 람다로 주입한다
- 저장소는 **인스턴스를 만들되 호출하지 않는다** — `QdrantClient`의 생성자가 연결하지 않는다는
  것을 3-3b에서 **실측**했기에 가능한 설계다(연결했다면 `get_store("qdrant")`가 CI에서 죽는다)
- 검색 **품질**은 pytest의 대상이 아니다 — 그건 M6 평가 하네스의 몫이다

### 가짜 모델·가짜 검색이 여럿인 이유

| 대역 | 무엇을 하나 | 지키는 것 |
|---|---|---|
| `FakeChatModel` | 도구를 **절대 안 부른다** | 기존 테스트가 2b와 **같은 경로**를 지난다 |
| `ToolCallingFakeModel` | **반드시 한 번 부른다** | 2c에서 생긴 **사이클 경로** |
| `retrieve_fn=lambda _: []` | 검색 결과 **없음** | 기존 테스트가 **"검색 없던 시절"과 동일**하게 동작 |
| `retrieve_fn=lambda _: FAKE_CHUNKS` | 검색 결과 **있음** | 컨텍스트가 모델까지 가는가 |
| `failing_retrieve` | 항상 **예외** | 검색 장애가 챗봇 장애로 안 번지는가 |
| `ConfigCapturingGraph` | 진짜 그래프에 **위임하며 config를 기록** | `RunnableConfig`에 무엇이 실렸는가(M4) |

가짜 모델 둘 다 `bind_tools`를 구현해야 한다 — `BaseChatModel.bind_tools`의 기본 구현이
`raise NotImplementedError`라서, 없으면 **전부 ERROR로 죽는다**(실측).

### 짝으로 둔 테스트들

| 짝 | 하나만 있으면 |
|---|---|
| `test_tool_call_round_trip` ↔ `test_tool_result_does_not_leak_into_the_stream` | 전자만: 결과가 새도 통과 / 후자만: 도구가 안 돌아도 통과 |
| `..._reaches_the_model_as_a_system_message` ↔ `..._does_not_leak_into_checkpointed_history` | 전자만: 매 턴 누적돼도 통과 / 후자만: 검색이 안 돌아도 통과 |
| `test_pop_store_arg`의 "이름" ↔ "남은 인자" | 이름만 보면 `--store`가 파일 경로로 남는 버그를 못 잡는다 |
| `test_enabled_with_keys` ↔ `test_half_configured_counts_as_disabled` | 전자만: public만 넣은 반쪽 설정이 "켜짐"으로 통과 |

---

## 9. 문제가 생겼을 때 어디를 보나

| 증상 | 먼저 볼 곳 |
|---|---|
| `Failed to fetch` | 서버가 떠 있는가 → `curl localhost:8000/api/v1/chat/health` |
| 422 | `transport.ts:18` — `id`·`trigger`·`messageId`를 빠뜨렸는가 (body는 **대체**다) |
| 400 `expected a non-empty user message` | 마지막 메시지가 user가 아니거나 텍스트 파트가 없다 |
| **이전 턴을 기억 못 함** | ① Payload의 `id`가 매 요청 같은가 ② `deps.py:58`에 체크포인터가 있는가 |
| **갑자기 기억을 잃음** | `--reload`가 재시작했다. `InMemorySaver`는 프로세스 메모리다 — 코드 문제가 아니다 |
| **새 대화인데 옛날 얘기를 함** | `Chat.tsx:127`이 `setMessages([])`로 되돌아갔는가 |
| **화면에 원시 타임스탬프가 찍힘** | `chat.py:96`의 `isinstance(chunk, AIMessageChunk)` 필터가 빠졌다 |
| **도구를 안 부름 / 너무 자주 부름** | `tools.py:14`의 **docstring**을 고친다. 코드가 아니다 |
| `GraphRecursionError` | 사이클이 25바퀴를 넘었다 |
| 글자가 흐르지 않고 **툭** 나타남 | `deps.py:33` — `ChatAnthropic(streaming=True)` 확인 |
| **문서 얘기를 전혀 안 함 / "모른다"만 함** | ① 인입을 했는가 ② `retrieve` 로그에 예외가 찍혔는가(`graph.py:148`) ③ 아래 검색 CLI로 끊어서 확인 |
| **엉뚱한 문서를 근거로 답함** | 검색 문제다 → `uv run python -m app.rag.retriever "질문"`으로 **챗봇 없이** 확인 |
| **답이 근거를 무시함** | 로직이 아니라 `graph.py:40`의 `SYSTEM_PROMPT_TEMPLATE`부터 고친다 |
| **컨텍스트가 턴마다 불어남** | `retrieve`가 `{"messages": ...}`를 반환하고 있다 → `retrieved_context`여야 한다 |
| `ConnectionTimeout` (pgvector) | `docker compose up -d db` |
| `UnexpectedResponse: 404` (Qdrant) | 컬렉션이 없다 → `--store qdrant`로 인입부터. `_collection_ready` 플래그 때문에 **프로세스 재시작**이 필요할 수 있다 |
| **Qdrant로 바꿨는데 결과가 그대로** | `VECTOR_STORE` 오타는 `ValueError`로 죽는다. 안 죽었다면 인입을 pgvector에만 했을 것이다 |
| **검색 결과에 같은 내용이 여러 번** | Qdrant point id에 `uuid4`를 쓰고 있다 → `uuid5`(결정론적)여야 한다 |
| **순위가 거꾸로** | `qdrant_store.py:150`의 `1.0 - point.score` 변환이 빠졌다 |
| `NotImplementedError` (테스트) | 가짜 모델에 `bind_tools`가 없다 |
| **Langfuse에 트레이스가 안 쌓임** | ① `.env`에 키 둘 다 있는가(하나만이면 꺼진다) ② `uv run python scripts/probe_langfuse.py`로 `auth_check()` 확인 ③ `LANGFUSE_HOST`가 맞는가 |
| **Sessions 뷰에서 대화가 안 묶임** | `metadata` 키가 `langfuse_session_id`인가. 오타는 에러가 아니라 평범한 메타데이터로 저장된다 |
| `ImportError: langfuse.callback` | v2 예제를 베꼈다. v3/v4는 `langfuse.langchain` |
| "Please install langchain to ..." | `langchain-core`만으로는 안 된다. `uv add langchain` |
| 스크립트에서만 트레이스가 안 감 | `client.flush()`를 안 했다. 전송이 배치라 프로세스가 먼저 죽는다 |
| `UnicodeEncodeError: 'cp949'` | Windows 콘솔. 스크립트에 `sys.stdout.reconfigure(encoding="utf-8")` |
| curl이 한글 본문에 **400** | Git Bash 코드페이지. UTF-8 파일에 담아 `-d @req.json` |

### 층별로 끊어서 보는 법 (아래로 갈수록 좁다)

```bash
# ① 저장소만 — 챗봇도 그래프도 없이
cd backend && uv run python -m app.rag.retriever "파이썬 버전은 어떻게 관리해?"
uv run python -m app.rag.retriever --store qdrant "같은 질문"     # 저장소만 바꿔서

# ② 두 저장소를 나란히 (같은 벡터로 — 저장소 차이만 남는다)
uv run python scripts/compare_stores.py

# ③ 백엔드만 — 브라우저 없이 2턴
curl -s -N -X POST http://localhost:8000/api/v1/chat -H "Content-Type: application/json" \
  -d @req.json          # 한글은 반드시 UTF-8 파일로

# ④ 그래프 배선을 눈으로
uv run python -c "from app.api.deps import _graph; print(_graph.get_graph().draw_mermaid())"
```

④의 기대 출력 — 이 5줄이 다 있으면 배선은 맞다:
```
__start__  -->  retrieve       실선 = 무조건
retrieve   -->  call_model     실선 = 무조건
call_model -.-> __end__        점선 = 조건부
call_model -.-> tools          점선 = 조건부
tools      -->  call_model     실선 = 사이클
```

### 체크포인터를 직접 열어보는 법

```python
graph.get_state({"configurable": {"thread_id": "t-demo"}}).values["messages"]
```

손댄 적 없는 스레드는 `values == {}`다(실측).
**여기에 `SystemMessage`가 보이면 3-2b의 설계가 깨진 것이다** — 검색 결과가 누적되고 있다.

### 저장소 안을 직접 들여다보는 법

```bash
# pgvector — "행이 있는가"가 아니라 "값이 맞는가"를 본다 (3-1의 chunk_index=1 사고)
docker compose exec db psql -U postgres -d app -c \
  "select source, count(*), min(chunk_index), max(chunk_index), count(distinct chunk_index)
   from document_chunks group by source order by source;"

# Qdrant — 웹 대시보드가 있다
#   http://localhost:6333/dashboard
curl -s -X POST http://localhost:6333/collections/document_chunks/points/count \
  -H 'Content-Type: application/json' -d '{"exact":true}'
```

**두 저장소의 총 개수가 같아야 `compare_stores.py`의 결과가 의미를 갖는다.**

---

## 갱신 규칙

이 문서는 **줄 번호를 포함**하므로 코드가 움직이면 어긋난다. 마일스톤이 끝날 때
(= [README.md](./README.md)의 체크박스를 채울 때) 함께 갱신한다.

줄 번호를 다시 뽑는 명령:

```bash
cd backend
grep -n "def \|async for\|yield\|isinstance(chunk\|return StreamingResponse\|raise HTTP\|config = " app/api/routes/chat.py
grep -n "^def \|^async def \|^UI_MESSAGE\|^DONE\|yield sse" app/core/ai_sdk.py
grep -n "class \|def \|bind_tools\|add_node\|add_edge\|add_conditional\|compile\|SYSTEM_PROMPT\|retrieved_context\|to_thread" app/graph.py
grep -n "@tool\|^def \|^TOOLS" app/tools.py
grep -n "^_model\|^_graph\|^_checkpointer\|^_store\|^def \|^Graph" app/api/deps.py
grep -n "^_client\|^def " app/core/tracing.py
grep -n "^TOP_K\|^EMBEDDING_DIM\|^class \|    def \|^def \|^_BUILDERS\|^TIMEOUT" app/rag/*.py

cd ../frontend
grep -n "chatTransport\|useChat(\|function submit\|sendMessage(\|setChatId" src/components/chat/Chat.tsx
grep -n "export \|api:\|messages:" src/components/chat/transport.ts
```
