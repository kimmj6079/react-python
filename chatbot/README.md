# 챗봇 기능 학습 로드맵 (FastAPI + LangGraph + Vercel AI SDK + Qdrant + Langfuse)

> 이 폴더에는 코드가 없다. 이 문서는 **순수 로드맵/진행 기록**이고, 실제 코드는 저장소 루트의
> `backend/`, `frontend/`(기존 items CRUD 앱)에 새 기능으로 직접 추가된다.

## Context

처음에는 완전히 격리된 `chatbot/backend`(FastAPI), `chatbot/frontend`(Next.js) 하위 프로젝트로 계획했으나,
**기존 `backend/`, `frontend/`에 새 기능으로 같이 개발하는 쪽으로 방향을 바꿨다.** 확정된 통합 수준:

- **프론트엔드**: Next.js는 포기하고 기존 Vite+React 그대로 사용. Vercel AI SDK의 `useChat`(`ai`, `@ai-sdk/react`)은
  Next.js 전용이 아니라 어떤 React 환경에서도 동일하게 동작하므로 기능상 문제 없음.
- **백엔드**: 완전히 별도 앱이 아니라 **같은 FastAPI 앱에 새 라우터로 추가**(`app/api/routes/chat.py`).
  같은 포트(8000)·같은 CORS 설정·같은 배포 파이프라인을 공유.

FastAPI에는 익숙하지만 LangGraph·Vercel AI SDK·Qdrant·Langfuse는 전부 처음이다. **코드를 대신 작성받는 게 아니라
직접 타이핑하며 배우는 것이 목적**이므로, 이 문서는 순서와 이유를 안내하는 커리큘럼이고 Claude는 방향 제시·질문 답변·
코드 리뷰 역할만 한다.

Qdrant는 Cloud 무료 티어, Langfuse도 동일한 이유(학습 마찰 최소화)로 Cloud 무료 티어를 기본값으로 한다
(나중에 `LANGFUSE_HOST`만 바꾸면 self-host 전환 가능).

## 통합 후 실제로 손대는 파일

```
backend/
├── pyproject.toml            # langgraph, langchain-openai(또는 anthropic), qdrant-client,
│                              # langchain-qdrant, langfuse 등 의존성 추가
├── .env.example               # 새 시크릿 키 이름 추가 (OPENAI_API_KEY, QDRANT_URL, QDRANT_API_KEY,
│                              # LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST)
└── app/
    ├── main.py                 # app.include_router(chat.router, prefix=settings.api_v1_prefix) 추가
    ├── core/config.py          # 위 새 시크릿들을 Settings 필드로 추가
    ├── core/tracing.py         # 신규: Langfuse CallbackHandler 팩토리 (M4)
    ├── api/routes/chat.py      # 신규: POST /api/v1/chat 엔드포인트 (SSE 스트리밍)
    ├── graph.py                 # 신규: LangGraph StateGraph 정의 (M2)
    └── rag/{ingest.py,retriever.py}  # 신규: Qdrant 인입/검색 (M3)

frontend/
├── package.json               # ai, @ai-sdk/react 추가
└── src/
    ├── App.tsx                 # 신규: "Items" / "Chat" 전환용 간단한 탭 상태 추가
    └── components/Chat.tsx     # 신규: useChat 기반 채팅 UI
```

- 기존 `items` 관련 라우터/컴포넌트는 전혀 건드리지 않는다 — 새 파일 추가 + `main.py`/`App.tsx`에 최소한의 배선만.
- 프론트에 아직 라우팅 라이브러리가 없으므로(현재 `package.json`에 `react-router` 없음), 처음엔 `react-router-dom`을
  새로 들이지 않고 `App.tsx`에 `view: 'items' | 'chat'` 같은 로컬 상태로 탭 전환만 구현한다. 나중에 화면이 늘어나면
  그때 라우터 도입을 고려.
- API prefix는 기존 `items`와 동일하게 `settings.api_v1_prefix`(`/api/v1`)를 재사용 → 엔드포인트는
  `/api/v1/chat`.

## ⚠ 기존 CI/CD·배포 파이프라인에 자동으로 편입된다는 점 유의

`chatbot/backend`처럼 격리된 샌드박스가 아니라 `backend/`, `frontend/`에 직접 추가하므로, 이 코드는
자동으로 다음 파이프라인의 대상이 된다:

- **`ci.yml`**: `ruff check`, `pytest`(실제 Postgres 마이그레이션 포함), `vitest`, docker build, k8s manifest
  check가 이 새 코드에도 그대로 적용된다. **특히 pytest에서 실제 LLM/Qdrant/Langfuse API를 호출하면 안 됨** —
  비용·플래키함·CI에 시크릿 노출 문제가 생기므로, chat 엔드포인트 테스트는 LLM 호출 부분을 목(mock)으로 대체하는
  방식을 M1에서 같이 설계해야 한다.
- **CD/배포**: `docker-compose.yml`, `k8s/`, `docker-compose.prod.yml` 이미지에도 이 코드가 그대로 포함된다.
  다만 실제 배포(k8s Job, docker-compose 서비스, `k8s/base/secret.yaml`, `.env.prod`)에 새 시크릿 값을
  채우는 건 로컬 학습이 어느 정도 끝난 뒤(M5 근처)로 미뤄도 된다 — 로컬 `.env`만 채워도 `docker compose up`
  까지는 문제없이 동작.

즉 M0~M4는 **로컬 dev 서버(uvicorn --reload / npm run dev)** 기준으로 진행하고, CI/배포 반영은 나중에
별도로 다룬다.

## 마일스톤

### M0 — 배선 확인 (가볍게)
기존 FastAPI↔React 통신은 이미 `items` 기능으로 증명되어 있으므로, 여기선 새 라우터/새 탭이 제대로 연결되는지만
가볍게 확인한다. `app/api/routes/chat.py`에 `GET /api/v1/chat/health -> {"status": "ok"}` 정도의 placeholder
추가 → `main.py`에 등록. 프론트는 `App.tsx`에 "Items"/"Chat" 탭 상태 추가 → `Chat.tsx`에서 그 placeholder를
`fetch`로 호출해 렌더링.
**검증**: `curl localhost:8000/api/v1/chat/health`, 브라우저에서 탭 전환 후 렌더링 확인.

**체크리스트 (완료)**:
- [x] `backend/app/api/routes/chat.py`에 `GET /chat/health -> {"status": "ok"}` placeholder 라우터 작성
  (health.py의 liveness/readiness probe를 그대로 복붙하지 않도록 주의 — DB 체크 불필요)
- [x] `backend/app/main.py`에 `chat.router` 등록 (`items`와 동일하게 `settings.api_v1_prefix` 사용)
- [x] `frontend/src/App.tsx`에 `view: 'items' | 'chat'` 상태 + 탭 버튼 2개 추가, 조건부 렌더링으로 전환
  (JSX 안 주석은 `//`가 아니라 `{/* ... */}`로 써야 함 — 안 그러면 화면에 그대로 텍스트로 렌더링됨)
- [x] `frontend/src/components/chat/Chat.tsx` 작성 (`useEffect`로 placeholder fetch, `export function Chat()`
  named export — `App.tsx`가 named import로 가져다 씀)
- [x] `frontend/src/api/client.ts`에 `getChatHealth()` 추가 (`request()` 헬퍼 재사용)
- [x] 검증: `http://localhost:8000/api/v1/chat/health` 200 확인 + 브라우저에서 탭 전환/렌더링 확인

### M1 — 단순 LLM 대화 (LangGraph 없이, Vercel AI SDK 스트리밍)
FastAPI가 LLM을 직접 호출해 SSE로 스트리밍, 프론트는 `ai`/`@ai-sdk/react`의 `useChat`으로 수신.
**핵심 함정**: Vercel AI SDK의 스트림 프로토콜(헤더 이름, 청크 타입)은 SDK 메이저 버전마다 바뀌어왔다 — 문서를
암기해서 타이핑하지 말고, 먼저 아주 간단한 순수 JS/TS 스크립트나 Route Handler 등으로 `streamText().toUIMessageStreamResponse()`
결과를 `curl -N -i`로 **실제 헤더/바이트를 캡처**한 뒤 FastAPI에서 그대로 모사한다. AI SDK v5 메시지는
`content: string`이 아니라 `parts: [{type:"text", text:...}]` 배열이므로, 순수 텍스트로 변환하는 함수를 직접 작성.
**여기서 같이 결정할 것**: pytest에서 이 엔드포인트를 어떻게 테스트할지(LLM 클라이언트를 fixture로 목킹).
**검증**: `curl -N`으로 원시 SSE 라인 확인, 브라우저에서 실시간 토큰 렌더링, DevTools "EventStream" 탭에서
청크 순서 확인.

**체크리스트 (진행 중)**:
- [x] LLM 프로바이더 결정: **Anthropic (Claude)**
- [x] console.anthropic.com에서 API 키 발급
- [x] `backend`에서 `uv add anthropic`
- [x] `backend/app/core/config.py`의 `Settings`에 `anthropic_api_key: str = ""` 필드 추가
  (+ `anthropic_model: str = "claude-haiku-4-5"` — 교체 후보를 주석으로 병기. 시크릿 기본값은
  반드시 `""` — config.py는 커밋되는 파일이라 실제 키를 적으면 GitHub에 그대로 올라간다)
- [x] `backend/.env`(실값)·`backend/.env.example`(더미값)에 `ANTHROPIC_API_KEY=...` 추가
  (`.env`는 gitignore 대상이라 git/탐색기에서 잘 안 보이고, `.env.example`은 커밋되는 파일이라
  절대 실값을 넣으면 안 된다. pydantic-settings는 `.env`만 읽고 `.env.example`은 읽지 않는다)
- [ ] **1a. 평범한 SSE로 Claude 스트리밍 흘려보내기** — `app/api/routes/chat.py`에 `POST /chat` 추가.
  `AsyncAnthropic`(동기 클라이언트는 이벤트 루프를 막는다) + `client.messages.stream()`의 `.text_stream`을
  `StreamingResponse(media_type="text/event-stream")`로 내보낸다. SSE 한 덩어리는 `data: ...\n\n`
  — 줄바꿈 **두 개**가 구분자라 하나만 쓰면 클라이언트가 이벤트 경계를 못 잡는다.
  검증: `curl -N -X POST localhost:8000/api/v1/chat -H 'Content-Type: application/json' -d '{"message":"..."}'`
- [ ] **1b. AI SDK의 실제 와이어 포맷 캡처** — 최소 JS/TS 스크립트로 `streamText().toUIMessageStreamResponse()`를
  띄우고 `curl -N -i`로 헤더+바이트를 그대로 기록해둔다 (문서 암기 금지 — 메이저 버전마다 바뀐다)
- [ ] **1c. 1a의 출력을 1b 포맷에 맞추기** — AI SDK v5 메시지는 `content: string`이 아니라
  `parts: [{type:"text", text:...}]` 배열이므로 순수 텍스트 변환 함수를 직접 작성
- [ ] pytest에서 LLM 호출 목킹 전략 설계 (1a에서 클라이언트를 모듈 레벨/lifespan 중 어디에 뒀는지가 여기서 갈린다)
- [ ] frontend에 `ai`, `@ai-sdk/react` 추가, `Chat.tsx`를 `useChat` 기반으로 교체
- [ ] 최종 검증: 브라우저 실시간 렌더링 + DevTools "EventStream" 탭에서 청크 순서 확인

> **1a~1c로 쪼갠 이유**: 미지수가 둘(Anthropic 스트리밍 API / AI SDK 프로토콜)이라 한 번에 하면
> 화면에 글자가 안 나올 때 원인을 구분할 수 없다. 1a에서 "토큰이 실제로 흘러나온다"를 curl로
> 확정해두면 이후 문제는 전부 포맷 문제로 좁혀진다.

### M2 — LangGraph 도입 (단일 노드 → 멀티턴 메모리 → 도구/조건부 엣지)
`StateGraph`를 직접 조립. `State(TypedDict)`에 `messages: Annotated[list, add_messages]`, 단일 노드
`call_model` → `InMemorySaver`로 컴파일. **아키텍처 전환점**: 프론트가 매번 전체 히스토리를 보내는 대신,
백엔드(체크포인터)가 대화 상태의 단일 소스가 되고 프론트는 `thread_id` + 새 메시지만 보낸다. 이후 간단한
도구 1개를 `bind_tools` + `ToolNode` + `add_conditional_edges(tools_condition)`로 추가.
**검증**: 같은 `thread_id`로 2회 연속 요청해 이전 턴을 기억하는지 확인, `graph.get_state(config)`로 체크포인트
내용 직접 출력.

### M3 — Qdrant 연동 (RAG 완성)
Qdrant Cloud 가입 → 무료 클러스터 생성 → API Key/URL 확보(무료 티어는 1주 미사용 시 suspend, 4주 시 삭제 유의).
`qdrant-client` + `langchain-qdrant`, 임베딩은 OpenAI `text-embedding-3-small`. 일회성 인입 스크립트
(`rag/ingest.py`)로 샘플 문서 청킹 후 업서트. 그래프에 `retrieve` 노드를 맨 앞에 추가
(`START→retrieve→generate→END`), `State`에 `context: list[str]` 필드 추가.
**검증**: Qdrant 콘솔에서 컬렉션/포인트 수 확인, 샘플 문서에만 있는 내용 질문 → 정답 확인 → 문서 수정/재인입 후
답이 바뀌는지 확인.

### M4 — Langfuse 연동 (트레이싱)
Langfuse Cloud 가입 → 프로젝트 생성 → Key 발급. `langfuse.langchain.CallbackHandler`를 그래프 호출 `config`의
`callbacks`에 전달, `thread_id`를 Langfuse `session_id`로도 연결.
**검증**: Langfuse 대시보드 Traces에서 retrieve/generation 중첩 트리 확인, 프롬프트/토큰/비용/지연시간 확인,
Sessions 뷰에서 세션 그룹핑 확인.

### M5 (선택) — CI/배포 반영 + 확장
- `ci.yml`의 pytest가 chat 엔드포인트를 목 기반으로 통과하는지 확인(M1에서 이미 설계했다면 여기선 점검만).
- `backend/.env.example`, `k8s/base/secret.yaml.example`, `.env.prod.example`에 새 시크릿 키 이름 추가.
- 대화 영속화 강화(`InMemorySaver`→`PostgresSaver`, 기존 Postgres 재사용), resumable stream, 비용/가드레일 등.

## 진행 방식
각 마일스톤을 직접 타이핑하고, Claude는 (a) 다음에 뭘 만들지 방향 제시, (b) 막히는 지점 질문에 답변,
(c) 작성된 코드 리뷰/디버깅 보조 역할을 한다. 코드 전문을 먼저 제공하지 않는다.

## 진행 현황
- [x] M0 — 배선 확인 (새 라우터 + 새 탭)
- [ ] M1 — 단순 LLM 대화 + 스트리밍 (+ 테스트 목킹 전략)
- [ ] M2 — LangGraph 도입
- [ ] M3 — Qdrant RAG
- [ ] M4 — Langfuse 트레이싱
- [ ] M5 — CI/배포 반영 + 선택 확장
