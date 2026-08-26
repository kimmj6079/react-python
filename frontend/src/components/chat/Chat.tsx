// 챗봇 UI. AI SDK의 useChat 훅이 요청 전송 · SSE 파싱 · 메시지 상태 관리를 전부 담당하고,
// 이 컴포넌트가 하는 일은 "입력값 관리"와 "그리기"다.
//
// 여기 쓰인 API 모양은 추측이 아니라 실측이다 (chatbot/README.md의 M1-1d).
// ai@7.0.79 / @ai-sdk/react@4.0.82 기준이고, 버전을 올리면 .d.ts를 다시 봐야 한다.
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { useChat } from '@ai-sdk/react'
import { DefaultChatTransport } from 'ai'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { CHAT_API_URL } from '../../api/client'
import './Chat.css'

// transport는 "어디로 어떻게 보낼까"만 들고 있는 객체라 렌더마다 새로 만들 이유가 없다.
// import 출처에 주의: 훅은 '@ai-sdk/react'인데 DefaultChatTransport는 코어인 'ai'에 있다.
const transport = new DefaultChatTransport({ api: CHAT_API_URL })

// 빈 화면에 띄울 예시 질문. 컴포넌트 밖 상수라 렌더마다 새로 만들어지지 않는다.
const SUGGESTIONS = [
  'FastAPI의 SSE 스트리밍을 예제로 설명해줘',
  '파이썬 리스트 컴프리헨션을 표로 정리해줘',
  'LangGraph의 StateGraph가 뭐야?',
]

export function Chat() {
  // 입력창 값은 우리가 직접 관리한다. useChat은 input/handleInputChange를 주지 않는다.
  const [input, setInput] = useState('')

  const { messages, sendMessage, setMessages, status, error, clearError, stop } = useChat({
    transport,
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
        <h1 className="chat__title">Chat</h1>
        <button
          type="button"
          className="chat__new"
          onClick={() => setMessages([])}
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
