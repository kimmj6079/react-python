// 챗봇 UI. AI SDK의 useChat 훅이 요청 전송 · SSE 파싱 · 메시지 상태 관리를 전부 담당하고,
// 이 컴포넌트가 하는 일은 "입력값 관리"와 "그리기"다.
//
// 여기 쓰인 API 모양은 추측이 아니라 실측이다 (chatbot/README.md의 M1-1d).
// ai@7.0.79 / @ai-sdk/react@4.0.82 기준이고, 버전을 올리면 .d.ts를 다시 봐야 한다.
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { useChat } from '@ai-sdk/react'
import { generateId } from 'ai'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { chatTransport } from './transport'
import { Citations } from './Citations'
import { Feedback } from './Feedback'
import './Chat.css'

// 빈 화면에 띄울 예시 질문. 컴포넌트 밖 상수라 렌더마다 새로 만들어지지 않는다.
const SUGGESTIONS = [
  'FastAPI의 SSE 스트리밍을 예제로 설명해줘',
  '파이썬 리스트 컴프리헨션을 표로 정리해줘',
  'LangGraph의 StateGraph가 뭐야?',
]

export function Chat() {
  // 입력창 값은 우리가 직접 관리한다. useChat은 input/handleInputChange를 주지 않는다.
  const [input, setInput] = useState('')

  // ★ 2b-2: 대화 세션 id를 컴포넌트가 소유한다 ★
  // 2b-1 전까지는 useChat이 내부에서 만든 id를 그냥 썼다. 그때는 이 값이
  // 아무 의미 없는 상관관계 id였지만, 2b-1부터는 이게 그대로 서버의
  // thread_id다 — 즉 "어느 대화 기록에 이어 쓸 것인가"를 정하는 값이 됐다.
  // 의미가 생긴 값은 남이 만들게 두지 않는다.
  //
  // useState(generateId())가 아니라 useState(() => generateId())인 것에 주의.
  // 전자는 렌더마다 generateId()를 호출한다(반환값은 첫 번째만 쓰이고 나머지는
  // 버려진다). lazy initializer를 쓰면 최초 1회만 실행된다.
  //
  // 새로고침하면 새 id가 생긴다 = 서버에도 새 스레드다. 화면도 비어 있으니
  // 앞뒤가 맞는다. localStorage에 넣어 유지하지 않는 이유는 아래 ③ 참고.
  const [chatId, setChatId] = useState(() => generateId())

  // id를 넘기면 useChat이 이 값으로 Chat 인스턴스를 만든다. 그리고 id가 바뀌면
  // 인스턴스를 통째로 새로 만든다(실측: shouldRecreateChat). 그래서 messages도
  // 같이 비워진다 — 우리가 setMessages([])를 부를 필요가 없어졌다.
  const { messages, sendMessage, status, error, clearError, stop } = useChat({
    id: chatId,
    transport: chatTransport,
  })

  // status는 4상태다: submitted | streaming | ready | error.
  const isBusy = status === 'submitted' || status === 'streaming'

  // --- 자동 스크롤 -------------------------------------------------------
  // 목록 맨 끝에 빈 div를 두고 거기로 스크롤한다. scrollTop을 직접 계산하는 것보다
  // 간단하고 부드러운 스크롤도 공짜다.
  const bottomRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
    // messages는 토큰이 도착할 때마다 새 배열이 되므로 스트리밍 내내 따라간다.
    // status도 넣은 이유: 타이핑 인디케이터가 나타나고 사라질 때도 높이가 변한다.
  }, [messages, status])

  // --- textarea 자동 높이 -----------------------------------------------
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    // 'auto'로 먼저 되돌리는 게 핵심이다. 이걸 빼면 scrollHeight가 현재 높이에
    // 갇혀서 한 번 커진 textarea가 절대 줄어들지 않는다.
    el.style.height = 'auto'
    el.style.height = `${el.scrollHeight}px`
  }, [input])

  // --- 전송 --------------------------------------------------------------
  // 폼 제출 · Enter 키 · 예시 질문 버튼 세 경로에서 같은 일을 하므로 함수로 뽑았다.
  function submit(text: string) {
    const trimmed = text.trim()
    // 빈 문자열을 보내면 백엔드가 400을 낸다(ai_sdk.text_from_parts가 빈 텍스트를 거른다).
    if (!trimmed || isBusy) return

    // 인자가 유니온이라 { text } / { files } / { parts } 중 하나만 쓸 수 있다.
    // 프로미스지만 await하지 않는다 — 진행 상태는 useChat이 갱신해준다.
    sendMessage({ text: trimmed })
    setInput('')
  }

  function handleSubmit(e: FormEvent) {
    // 폼 기본 동작(페이지 새로고침)을 막는다. 안 막으면 대화가 통째로 날아간다.
    e.preventDefault()
    submit(input)
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    // ★ 한글 입력의 필수 처리 ★
    // 한글은 조합(composition) 방식이라 "안녕"을 치는 동안 IME가 글자를 조립 중이다.
    // 이때의 Enter는 "조합 확정"이지 "전송"이 아니다. 이 가드가 없으면 마지막 글자에서
    // 의도치 않게 전송되거나 글자가 중복된다. 영어로 테스트하면 절대 안 나오는 버그다.
    if (e.nativeEvent.isComposing) return

    if (e.key === 'Enter' && !e.shiftKey) {
      // textarea의 기본 Enter는 줄바꿈이므로 막아야 한다.
      e.preventDefault()
      submit(input)
    }
    // Shift+Enter는 아무것도 안 한다 = 기본 동작인 줄바꿈이 그대로 일어난다.
  }

  return (
    <div className="chat">
      <header className="chat__header">
        {/* title 속성으로 thread_id를 노출한다. 학습 중 "지금 어느 스레드지?"를
            브라우저에서 바로 확인하기 위한 것이고, CSS를 건드리지 않는다.
            실무 서비스라면 이건 안 보여준다 — 사용자에게 의미 없는 값이고,
            thread_id는 지금 구조상 남이 알면 대화에 끼어들 수 있는 값이다. */}
        <h1 className="chat__title" title={`thread: ${chatId}`}>
          Chat
        </h1>
        <button
          type="button"
          className="chat__new"
          // ★ 2b-2의 한 줄 ★
          // 2b-1 전까지는 setMessages([])였다. 그건 브라우저 배열만 비우고
          // 서버 스레드는 그대로 둬서, 화면은 비었는데 모델은 이전 대화를
          // 기억하는 상태를 만들었다(2b-1 검증에서 눈으로 확인한 그것).
          //
          // 이제는 id를 새로 발급한다. useChat이 인스턴스를 재생성하면서
          // messages도 비우고, 다음 요청은 서버의 새 thread_id로 나간다.
          // "화면 비우기"와 "서버 스레드 바꾸기"가 한 동작이 된다.
          onClick={() => setChatId(generateId())}
          disabled={messages.length === 0 || isBusy}
        >
          새 대화
        </button>
      </header>

      <div className="chat__scroll">
        {messages.length === 0 ? (
          <div className="chat__empty">
            <h2 className="chat__empty-title">무엇을 도와드릴까요?</h2>
            <div className="chat__suggestions">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  type="button"
                  className="chat__suggestion"
                  onClick={() => submit(s)}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="chat__thread">
            {messages.map((message) => (
              <article key={message.id} className={`msg msg--${message.role}`}>
                {message.role === 'assistant' && (
                  // aria-hidden: 스크린리더가 "AI"를 읽을 필요는 없다. 장식이다.
                  <div className="msg__avatar" aria-hidden="true">
                    AI
                  </div>
                )}
                <div className="msg__body">
                  {/* 본문은 content가 아니라 parts 배열이다 (ai/dist/index.d.ts:1818).
                      파트 종류가 11종이라 text만 골라 그린다. */}
                  {message.parts.map((part, i) =>
                    part.type !== 'text' ? null : message.role === 'assistant' ? (
                      // 어시스턴트 응답만 마크다운으로 해석한다. 사용자가 친 "**굵게**"까지
                      // 해석하면 내가 뭘 보냈는지 화면에서 확인할 수 없게 된다.
                      <ReactMarkdown key={i} remarkPlugins={[remarkGfm]}>
                        {part.text}
                      </ReactMarkdown>
                    ) : (
                      // 사용자 메시지는 문자열 그대로. 줄바꿈은 CSS의 white-space가 살린다.
                      <span key={i}>{part.text}</span>
                    ),
                  )}
                  {/* ★ M10 ★ 같은 parts 배열에서 출처만 골라 카드로 그린다.
                      본문 아래에 두는 이유: 백엔드가 text-end 뒤에 출처를 보내므로
                      (실측 순서) 글이 다 그려진 뒤 카드가 붙는다 — 화면이 덜컹거리지 않는다. */}
                  {message.role === 'assistant' && <Citations parts={message.parts} />}
                  {/* ★ M13 ★ 인용 카드 아래에 👍/👎. 순서에 뜻이 있다 —
                      사용자가 "근거"를 보고 나서 판단하게 두는 것이다.
                      metadata를 통째로 넘긴다: 무엇이 들어 있는지(traceId)는
                      와이어를 아는 Feedback이 판단한다. traceId가 없으면 아무것도
                      안 그리므로, 스트리밍 중이거나 트레이싱이 꺼진 환경에서는
                      여기서 조건을 따로 걸지 않아도 버튼이 나타나지 않는다. */}
                  {message.role === 'assistant' && <Feedback metadata={message.metadata} />}
                </div>
              </article>
            ))}

            {/* 요청은 나갔는데 첫 토큰이 아직인 구간. streaming에 들어가면 글자가
                직접 흘러나오므로 이 표시는 필요 없다. */}
            {status === 'submitted' && (
              <article className="msg msg--assistant">
                <div className="msg__avatar" aria-hidden="true">
                  AI
                </div>
                <div className="msg__body">
                  <span className="typing">
                    <i />
                    <i />
                    <i />
                  </span>
                </div>
              </article>
            )}

            {/* 스크롤 목적지. 화면에 보이는 것은 없다. */}
            <div ref={bottomRef} />
          </div>
        )}
      </div>

      {error ? (
        <div className="chat__error" role="alert">
          <span>{error.message}</span>
          <button type="button" onClick={clearError}>
            닫기
          </button>
        </div>
      ) : null}

      <form className="composer" onSubmit={handleSubmit}>
        <div className="composer__box">
          <textarea
            ref={textareaRef}
            className="composer__input"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="메시지를 입력하세요"
            rows={1}
          />

          {/* 작업 중일 때는 전송 버튼을 중지 버튼으로 바꾼다. 두 개를 나란히 두면
              평소에 하나는 항상 죽어 있어 자리만 차지한다. */}
          {isBusy ? (
            <button
              type="button"
              className="composer__btn composer__btn--stop"
              onClick={stop}
              aria-label="응답 중지"
            >
              ■
            </button>
          ) : (
            <button
              type="submit"
              className="composer__btn"
              disabled={!input.trim()}
              aria-label="전송"
            >
              ↑
            </button>
          )}
        </div>
        <p className="composer__hint">Enter 전송 · Shift+Enter 줄바꿈</p>
      </form>
    </div>
  )
}
