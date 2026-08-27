// prepareChatRequest는 순수 함수라 React도 jsdom도 필요 없다.
// 그래서 여기서 테스트한다 — Chat.tsx를 통해 테스트하면 렌더링·훅·SSE 목킹까지
// 딸려와서, 정작 검증하려는 "본문을 어떻게 만드는가"가 노이즈에 묻힌다.
//
// 이게 App.test.tsx(화면이 그려지는가)와 역할이 갈리는 지점이다.
// 같은 것을 두 곳에서 검증하지 않는다.
import { describe, expect, it } from 'vitest'
import type { UIMessage } from 'ai'
import { prepareChatRequest } from './transport'

function msg(id: string, role: 'user' | 'assistant', text: string): UIMessage {
  return { id, role, parts: [{ type: 'text', text }] }
}

// SDK가 넘겨주는 인자는 9개인데 우리가 쓰는 건 4개뿐이다.
// 나머지를 테스트마다 적으면 정작 중요한 messages가 안 보이므로 헬퍼로 묻어둔다.
function call(messages: UIMessage[]) {
  return prepareChatRequest({
    api: '/api/v1/chat',
    id: 'thread-1',
    messages,
    body: undefined,
    headers: undefined,
    credentials: undefined,
    requestMetadata: undefined,
    trigger: 'submit-message',
    messageId: messages.at(-1)?.id,
  })
}

describe('prepareChatRequest', () => {
  it('히스토리가 쌓여도 마지막 메시지 하나만 보낸다', () => {
    // 이 테스트가 지키는 것: slice(-1)을 slice(1)이나 slice(0, 1)로 잘못 쓰는 실수.
    // 그런 오타는 화면에서 안 보인다 — 서버가 엉뚱한 메시지에 답하거나
    // 400을 낼 뿐이라 원인을 프론트에서 찾기 어렵다.
    const { body } = call([
      msg('m1', 'user', '첫 질문'),
      msg('m2', 'assistant', '첫 답'),
      msg('m3', 'user', '두 번째 질문'),
    ])

    expect(body.messages).toEqual([msg('m3', 'user', '두 번째 질문')])
  })

  it('id · trigger · messageId를 함께 실어 보낸다', () => {
    // 반환한 body가 SDK 기본 본문을 "대체"하므로(실측), 이 셋을 빼먹으면
    // 서버가 422를 낸다. 조용히 사라지는 종류라 테스트로 못 박는다.
    const { body } = call([msg('m1', 'user', '안녕')])

    expect(body.id).toBe('thread-1')
    expect(body.trigger).toBe('submit-message')
    expect(body.messageId).toBe('m1')
  })

  it('메시지가 없으면 빈 배열을 준다', () => {
    // messages[messages.length - 1]로 짰다면 여기서 [undefined]가 나온다.
    // 실제로 일어나는 경로는 아니지만, 이 테스트가 있으면 나중에 누가
    // slice를 인덱스 접근으로 "간단하게" 바꿀 때 즉시 걸린다.
    const { body } = call([])

    expect(body.messages).toEqual([])
  })
})
