# 챗봇 프로젝트 (FastAPI + LangGraph + Next.js/Vercel AI SDK + Qdrant + Langfuse) 학습 로드맵

## Context

이 프로젝트는 저장소 루트의 `backend/`, `frontend/`(FastAPI+React/Vite+PostgreSQL 스터디 프로젝트)와는 별개로, **처음부터 직접 타이핑하며** 만드는 챗봇 학습 서브프로젝트다. 목표 스택은 FastAPI(백엔드) + LangGraph(에이전트 오케스트레이션) + Next.js/Vercel AI SDK(프론트) + Qdrant(벡터 검색, Cloud 무료 티어) + Langfuse(LLM 트레이싱).

FastAPI에는 익숙하지만 LangGraph·Next.js·Qdrant·Langfuse는 전부 처음이다. **코드를 대신 작성받는 게 목적이 아니라 직접 타이핑하며 배우는 것이 목적**이므로 이 문서는 "무엇을, 왜, 어떤 순서로 만들지"를 안내하는 커리큘럼이며, 실제 구현은 직접 타이핑하고 Claude는 각 단계에서 질문에 답하거나 작성한 코드를 리뷰하는 방식으로 진행한다.

확정한 방향:
- 배치: 저장소 내부 `chatbot/` 하위 (기존 `backend/`, `frontend/`는 건드리지 않음)
- 시나리오: 단계적으로 — 먼저 단순 대화형을 완성한 뒤 RAG를 얹는다
- Qdrant: 로컬 Docker 대신 **Qdrant Cloud 무료 티어**
- Langfuse: Qdrant와 동일한 이유(학습 마찰 최소화)로 **Langfuse Cloud 무료 티어**를 기본값으로 — 나중에 `LANGFUSE_HOST`만 바꾸면 self-host로 전환 가능

## 폴더 구조

```
d:\react-python\
├── backend/, frontend/        # 기존 프로젝트 — 그대로 유지, 건드리지 않음
├── chatbot/                    # 이 학습 프로젝트 전용 네임스페이스
│   ├── README.md               # 이 문서 (로드맵 + 실행법)
│   ├── backend/                # FastAPI + LangGraph, 독립 pyproject.toml/uv.lock
│   │   └── app/
│   │       ├── main.py
│   │       ├── api/chat.py
│   │       ├── core/{config.py, tracing.py}
│   │       ├── graph.py
│   │       └── rag/{ingest.py, retriever.py}
│   └── frontend/               # Next.js, 독립 package.json
│       └── src/app/{page.tsx, layout.tsx}
```

- 최상위에 이름만 다른 폴더(`chatbot-backend`/`chatbot-frontend`)를 늘어놓는 대신 `chatbot/` 네임스페이스 하나로 묶어, 두 개의 독립 스터디 프로젝트가 있다는 게 트리 구조만 봐도 드러나게 한다.
- 포트 충돌 없음: 기존 스택이 5432/8000/5173을 쓰므로 챗봇 백엔드는 **8001**, 프론트는 Next.js 기본값 **3000** 사용.
- Python 패키지 관리는 기존과 동일하게 `uv` 재사용(독립 `pyproject.toml`/`uv.lock`). 프론트는 Vite가 아니라 Next.js(`next dev`, App Router)로 완전히 다른 도구.
- CI(`ci.yml`/`cd.yml`)·k8s·`docker-compose.yml`과는 무관 — 순수 로컬 학습 샌드박스로 유지.
- 저장소 루트 `.gitignore`에 추가 필요: `.env` 패턴은 이미 일반 규칙이라 `chatbot/backend/.env`도 커버되지만, **`.env.local`**과 **`.next/`**는 새 패턴이라 추가해야 함:
  ```
  chatbot/frontend/.env.local
  chatbot/frontend/.next/
  ```

## 마일스톤 (직접 타이핑, 각 단계 끝에 직접 검증)

### M0 — 스캐폴딩 (FastAPI ↔ Next.js "hello" 왕복)
LLM/스트리밍 없이 두 서버가 서로 통신하는 것만 확인. `chatbot/backend`는 `uv init` + fastapi/uvicorn/pydantic-settings, CORS 미들웨어(`allow_origins=["http://localhost:3000"]`), `GET /api/hello`. `chatbot/frontend`는 `create-next-app`으로 생성, 클라이언트 컴포넌트에서 `fetch`로 `/api/hello` 호출해 렌더링.
**검증**: `curl localhost:8001/api/hello`, 브라우저에서 렌더링 확인, DevTools에서 CORS 에러 없음 확인.

### M1 — 단순 LLM 대화 (LangGraph 없이, Vercel AI SDK 스트리밍)
FastAPI가 LLM을 직접 호출해 SSE로 스트리밍, Next.js는 `ai`/`@ai-sdk/react`의 `useChat`으로 수신. **핵심 함정**: Vercel AI SDK의 스트림 프로토콜(헤더 이름, 청크 타입)은 SDK 메이저 버전마다 바뀌어왔다 — 문서를 암기해서 타이핑하지 말고, Next.js Route Handler로 `streamText().toUIMessageStreamResponse()`를 먼저 만들어 `curl -N -i`로 **실제 응답 헤더/바이트를 눈으로 캡처**한 뒤 FastAPI 쪽에서 그대로 모사한다. AI SDK v5의 메시지는 `content: string`이 아니라 `parts: [{type:"text", text:...}]` 배열이므로, 이를 순수 텍스트로 변환하는 함수(`ui_messages_to_llm_messages`)를 직접 작성.
**검증**: `curl -N`으로 원시 SSE 라인 확인, 브라우저에서 실시간 토큰 렌더링, DevTools "EventStream" 탭에서 청크 순서(start→text-start→text-delta*→text-end→finish) 확인.

### M2 — LangGraph 도입 (단일 노드 → 멀티턴 메모리 → 도구/조건부 엣지)
`StateGraph`를 직접 조립(prebuilt 에이전트 대신 저수준 API로 시작 — 단일 노드→확장 순서와 정확히 맞음). `State(TypedDict)`에 `messages: Annotated[list, add_messages]`, 단일 노드 `call_model` → `InMemorySaver`로 컴파일. **아키텍처 전환점**: 이제부터 프론트가 매번 전체 히스토리를 보내는 게 아니라, 백엔드(체크포인터)가 대화 상태의 단일 소스가 되고 프론트는 `thread_id` + 새 메시지만 보낸다. 이후 간단한 도구 1개를 `bind_tools` + `ToolNode` + `add_conditional_edges(tools_condition)`로 추가.
**검증**: 같은 `thread_id`로 2회 연속 요청해 이전 턴을 기억하는지 확인, `graph.get_state(config)`로 체크포인트 내용 직접 출력.

### M3 — Qdrant 연동 (RAG 완성)
Qdrant Cloud 가입 → 무료 클러스터 생성 → API Key/URL 확보(무료 티어는 1주 미사용 시 suspend, 4주 시 삭제 — 학습을 오래 쉬면 재활성화 필요할 수 있음 유의). `qdrant-client` + `langchain-qdrant`, 임베딩은 OpenAI `text-embedding-3-small`(이미 M1에서 쓰는 키 재사용 가능, 다국어 문서에도 무난). 일회성 인입 스크립트(`rag/ingest.py`)로 샘플 문서 청킹 후 `QdrantVectorStore.from_documents`로 업서트. 그래프에 `retrieve` 노드를 맨 앞에 추가(`START→retrieve→generate→END`), `State`에 `context: list[str]` 필드 추가.
**검증**: Qdrant 콘솔에서 컬렉션/포인트 수 확인, 직접 만든 샘플 문서에만 있는 내용을 질문해 정답이 나오는지 확인 → 문서를 수정하고 재인입해 답이 바뀌는지 확인(파라메트릭 지식이 아니라 실제 검색 결과를 쓴다는 증거).

### M4 — Langfuse 연동 (트레이싱)
Langfuse Cloud 가입 → 프로젝트 생성 → Public/Secret Key 발급. `langfuse` SDK(v3+는 `langfuse.langchain.CallbackHandler` 자체 제공 — 설치 시점에 정확한 임포트 경로 재확인). 그래프 호출 시 `config`에 `callbacks=[handler]` 전달, 가능하면 `thread_id`를 Langfuse `session_id`로도 연결.
**검증**: Langfuse 대시보드 Traces에서 retrieve/generation이 중첩된 트리로 보이는지, 실제 프롬프트(주입된 컨텍스트 포함)와 토큰/비용/지연시간이 보이는지, Sessions 뷰에서 세션 그룹핑 확인.

### M5 (선택, 이후 확장)
대화 영속화 강화(`InMemorySaver`→`PostgresSaver`), 인증(Auth.js), 배포(프론트 Vercel/백엔드 Railway·Render·Fly.io 또는 기존 VM 패턴을 별도 서브도메인으로), resumable stream, Langfuse 기반 비용/가드레일. 핵심 커리큘럼(M0~M4) 완료 후 관심사에 따라 선택.

## 기존 CLAUDE.md 워크플로우와 달라지는 지점
- Python은 여전히 `uv` (일관됨). 프론트는 Vite→Next.js로 빌드 도구 자체가 다름.
- 로컬 Docker 통합 없음 — Qdrant/Langfuse 모두 Cloud라 M0~M4엔 컨테이너 불필요.
- Alembic 없음 — Qdrant는 컬렉션 API, LangGraph 체크포인터는 자체 `setup()`으로 테이블 생성.
- 기존 CI/CD·k8s 매니페스트와 완전히 무관.
- 새 시크릿 종류 추가: LLM 프로바이더 키, `QDRANT_URL`/`QDRANT_API_KEY`, `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY`/`LANGFUSE_HOST` — `.env.example` 커밋 + 실값 gitignore 패턴은 기존과 동일하게 재사용.

## 진행 방식
각 마일스톤을 직접 타이핑하고, Claude는 (a) 다음에 뭘 만들지 방향 제시, (b) 막히는 지점 질문에 답변, (c) 작성된 코드 리뷰/디버깅 보조 역할을 한다. 코드 전문을 먼저 제공하지 않는다.

## 진행 현황
- [ ] M0 — 스캐폴딩
- [ ] M1 — 단순 LLM 대화 + 스트리밍
- [ ] M2 — LangGraph 도입
- [ ] M3 — Qdrant RAG
- [ ] M4 — Langfuse 트레이싱
- [ ] M5 — 선택 확장
