# 챗봇 UI 셸 설계 (M0.5)

- 작성일: 2026-08-10
- 대상: `frontend/src/components/chat/`, `frontend/src/App.tsx`, `frontend/src/App.css`
- 관련 로드맵: [chatbot/README.md](../../../chatbot/README.md)

## 배경

M0에서 `Chat.tsx`가 백엔드 `GET /api/v1/chat/health`를 호출해 상태 문자열 한 줄을 렌더링하는 것까지 끝났다.
현재 화면은 "배선이 살아있다"는 것만 보여줄 뿐 챗봇 UI가 아니다.

M1(Anthropic 스트리밍 + Vercel AI SDK `useChat`)은 SSE 프로토콜 모사라는 까다로운 작업이라,
UI 시행착오와 스트리밍 디버깅이 섞이면 문제 원인을 분리하기 어렵다.
그래서 **목(mock) 데이터만으로 챗봇 UI 셸을 먼저 완성**하고, M1에서는 데이터 소스만 갈아끼운다.

## 목표

1. 백엔드·API 키 없이 동작하는 전체화면 1컬럼 챗봇 UI를 완성한다.
2. M1에서 `useChat`으로 교체할 때 **하위 컴포넌트를 재작성하지 않아도 되는** 경계로 쪼갠다.
3. 이 작업을 `chatbot/README.md` 로드맵에 `M0.5` 마일스톤으로 편입한다.

## 확정된 결정 사항

| 항목 | 결정 | 이유 |
|---|---|---|
| 작업 순서 | M1 앞에 M0.5 신설 | SSE 디버깅과 UI 시행착오를 분리 |
| 레이아웃 | 전체화면 1컬럼 (헤더 + 스크롤 영역 + 하단 고정 입력창) | 사이드바는 M2에서 `thread_id`가 생기기 전까지 빈 껍데기 |
| 스타일링 | 순수 CSS 파일 + `index.css` 기존 토큰 재사용 | 의존성 0, 다크모드 자동, CI/빌드 영향 없음 |
| 앱 셸 침습 | 뷰별 레이아웃 클래스 (`.app` / `.app--chat`) | 기존 Items 화면 시각적 변화 0 |
| 코드 작성 주체 | 사용자가 직접 타이핑, Claude는 체크리스트·함정 힌트·리뷰 | 기존 로드맵 학습 원칙 유지 |

## 로드맵 편입

`chatbot/README.md`의 M0과 M1 사이에 `M0.5 — 챗봇 UI 셸 (목 데이터)`를 삽입한다.
M1 체크리스트가 이미 일부 진행돼 있으므로 번호를 밀지 않고 소수점으로 끼워넣어 기존 진행 기록을 보존한다.

M1 체크리스트의 마지막 항목 문구도 함께 수정한다.

- 기존: `frontend에 ai, @ai-sdk/react 추가, Chat.tsx를 useChat 기반으로 교체`
- 변경: `frontend에 ai, @ai-sdk/react 추가 — M0.5에서 만든 UI의 데이터 소스만 목 배열 → useChat으로 교체 (MessageList/MessageBubble/Composer는 그대로)`

`## 진행 현황` 목록에도 `M0.5` 항목을 추가한다.

## 컴포넌트 구조

```
frontend/src/
├── types/chat.ts                      # 신규
└── components/chat/
    ├── Chat.tsx                        # 기존 파일을 전면 교체
    ├── MessageList.tsx                 # 신규
    ├── MessageBubble.tsx               # 신규
    ├── Composer.tsx                    # 신규
    ├── chat.css                        # 신규
    └── Chat.test.tsx                   # 신규
```

### 책임 경계

| 파일 | 무엇을 하는가 | 소유 상태 | 의존 |
|---|---|---|---|
| `types/chat.ts` | `ChatMessage` 타입 정의 | — | 없음 |
| `Chat.tsx` | 메시지 배열 소유, 전송 처리, 3단 조립, health 점 표시 | `messages`, `isResponding`, `healthStatus` | 하위 3개 + `api/client` |
| `MessageList.tsx` | 배열 → 버블 렌더, 새 메시지 시 바닥으로 스크롤 | 스크롤 컨테이너 `ref` | `MessageBubble` |
| `MessageBubble.tsx` | 메시지 하나를 role에 맞는 버블로 렌더 | 없음 (순수 표현) | 없음 |
| `Composer.tsx` | 입력값 관리, Enter 전송 / Shift+Enter 줄바꿈, textarea 높이 자동 조절 | `value`, textarea `ref` | 없음 |

**M1에서 바뀌는 것은 `Chat.tsx` 하나뿐이다.** `messages`/`isResponding`을 `useState`+`setTimeout`에서
`useChat()`의 반환값으로 교체하면 나머지는 그대로 동작한다. 이 재사용 가능성이 이 분할의 유일한 목적이다.

### 타입

```ts
// frontend/src/types/chat.ts
export type ChatRole = 'user' | 'assistant'

export interface ChatMessage {
  id: string
  role: ChatRole
  text: string
}
```

`text: string` 단일 필드로 둔다. AI SDK v5의 메시지는 `parts: [{type:'text', text}]` 배열 구조지만,
M1에서 그 변환은 `Chat.tsx` 안에서 흡수하고 하위 컴포넌트에는 계속 평평한 `text`를 내려준다.

## 데이터 흐름 (M0.5)

1. `Chat.tsx`가 하드코딩된 초기 메시지 3~4개를 `useState` 초기값으로 보유한다.
2. `Composer`가 `onSend(text)`를 호출한다.
3. `Chat.tsx`가 user 메시지를 배열에 추가하고 `isResponding`을 `true`로 만든다.
4. `setTimeout` 500ms 후 고정된 assistant 응답을 추가하고 `isResponding`을 `false`로 되돌린다.
5. `isResponding`이 `true`인 동안 `MessageList` 하단에 "응답 중..." 표시, `Composer`의 전송 버튼은 비활성.

M0에서 만든 `getChatHealth()` 호출은 **제거하지 않고** 헤더 우측의 작은 상태 점으로 유지한다.
UI를 다듬는 내내 백엔드 배선이 살아있는지 눈으로 확인할 수 있고, M1에서 실제 엔드포인트를 붙일 때
"프론트가 백엔드에 닿긴 하는가"를 먼저 배제할 수 있다.

health 호출이 실패해도 챗 UI 자체는 정상 동작해야 한다 — 점 색만 바뀐다.
성공은 `var(--accent)`, 실패는 `var(--text)`(흐린 회색), 응답 대기 중에는 `var(--border)`.
실패를 빨강으로 칠하지 않는 이유는, 백엔드를 끄고 UI만 다듬는 상황이 M0.5에서는 정상 작업 상태이기 때문이다.

## 레이아웃

### 앱 셸

```tsx
// App.tsx
<main className={view === 'chat' ? 'app app--chat' : 'app'}>
```

```css
/* App.css — 기존 main 규칙을 .app으로 옮기고, 챗일 때만 덮어쓴다 */
.app {
  max-width: 480px;
  margin: 2rem auto;
  padding: 0 1rem;
  font-family: system-ui, sans-serif;
}

.app--chat {
  max-width: none;
  margin: 0;
  padding: 0;
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  text-align: left;
}
```

`index.css`의 `#root`가 이미 `display:flex; flex-direction:column; min-height:100svh`이므로
`.app--chat`에 `flex:1`을 주면 남은 세로 공간을 그대로 받는다.
`#root`에 걸린 `text-align:center`는 `.app--chat`에서 `left`로 되돌린다.

기존 `main` 태그 선택자는 `.app` 클래스 선택자로 이름만 바꾸고 속성값은 그대로 옮긴다.
`form`, `ul`, `li` 태그 선택자는 손대지 않는다. Items 화면은 시각적으로 전혀 바뀌지 않는다.

### 챗 내부

```css
.chat           { display: flex; flex-direction: column; height: 100%; }
.chat__header   { flex-shrink: 0; }
.chat__list     { flex: 1; min-height: 0; overflow-y: auto; }
.chat__composer { flex-shrink: 0; }
```

### 걸리는 지점 4개

1. **`min-height: 0`** — flex 자식의 기본값은 `min-height: auto`라서 내용 크기만큼 무한정 늘어난다.
   이게 없으면 `.chat__list`에 `overflow-y:auto`를 줘도 스크롤바가 생기지 않고 페이지 전체가 늘어난다.
   `.app--chat`과 `.chat__list` **양쪽 모두**에 필요하다.

2. **`flex-shrink: 0`** — 헤더와 입력창에 없으면 메시지가 쌓일 때 눌려서 찌그러진다.

3. **자동 스크롤 `behavior`** — `'smooth'`는 M1 스트리밍에서 토큰마다 애니메이션이 겹쳐 오히려 끊긴다.
   `'auto'`를 쓴다.

4. **버블 줄바꿈** — `max-width: 70%`만으로는 공백 없는 긴 문자열(URL 등)이 버블을 뚫고 나간다.
   `overflow-wrap: anywhere`가 필요하다.

### 버블 스타일

`index.css`의 기존 CSS 변수만 사용해 다크모드가 자동으로 따라오게 한다.

| | 정렬 | 배경 | 테두리 |
|---|---|---|---|
| user | `align-self: flex-end` | `var(--accent-bg)` | `var(--accent-border)` |
| assistant | `align-self: flex-start` | `var(--code-bg)` | `var(--border)` |

새 색상값을 하드코딩하지 않는다.

## 테스트

`frontend/src/components/chat/Chat.test.tsx`를 신설하고, 기존 [App.test.tsx](../../../frontend/src/App.test.tsx)와
같은 방식(`vi.mock('../../api/client')` + role/text 쿼리)을 따른다.

케이스 3개:

1. 초기 목 메시지가 화면에 렌더된다.
2. 입력 후 전송하면 그 텍스트가 목록에 user 메시지로 추가된다.
3. Enter는 전송하고, Shift+Enter는 전송하지 않는다.

**jsdom 주의**: `Element.prototype.scrollTo`가 jsdom에 구현되어 있지 않아 자동 스크롤 코드가 그대로 예외를 던진다.
`ref.current?.scrollTo?.(...)` 옵셔널 호출로 방어하거나 `setupTests.ts`에서 stub한다.
어느 쪽을 택하든 자동 스크롤의 실제 동작은 테스트 대상이 아니다 — jsdom은 레이아웃을 계산하지 않으므로
`scrollHeight`가 항상 0이라 검증에 의미가 없다. 브라우저에서 수동 확인한다.

`setTimeout` 기반 목 응답은 `vi.useFakeTimers()`로 제어하거나, 케이스 2를 user 메시지 추가까지만
검증하는 것으로 회피한다.

목 데이터만 쓰므로 외부 API 호출이 없어 `ci.yml`의 vitest에 그대로 편입돼도 안전하다.

## 검증

`npm run dev` 실행 후 브라우저에서:

- 메시지를 20개 이상 쌓아 `.chat__list`에만 스크롤바가 생기고 페이지 자체는 스크롤되지 않는지
- 창 높이를 줄여도 입력창이 하단에 고정되고 찌그러지지 않는지
- 공백 없는 긴 URL을 보내 버블 안에서 줄바꿈되는지
- OS 다크모드를 전환해 색이 따라오는지
- DevTools 반응형 375px 폭에서 깨지지 않는지
- 백엔드를 끈 상태에서도 챗 UI가 동작하고 상태 점만 실패 표시되는지

명령어: `npm run test -- --run`, `npm run lint`, `npm run build`.

## 범위 밖

의도적으로 제외한다.

- 마크다운 렌더링 / 코드 하이라이팅 — M1에서 실제 LLM 응답을 본 뒤 필요성을 판단한다.
- 대화 목록 사이드바 / 새 대화 버튼 — M2에서 `thread_id`가 생기기 전까지는 실체가 없다.
- 메시지 복사 / 재생성 / 편집 버튼
- 아바타 이미지
- `react-router` 도입 — 화면이 더 늘어날 때 다시 검토한다.
- 백엔드 변경 — M0.5는 프론트엔드 전용이다.
