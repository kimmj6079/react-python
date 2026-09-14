// 대화 세션 id를 새로고침 너머로 유지하는 로직. (M5-3)
//
// ★ 왜 이 조각을 따로 뺐나 ★ Chat.tsx 안에 두면 이 규칙을 검증하려고 React 렌더와
// useChat 목킹이 통째로 딸려온다(transport.ts를 분리한 것과 같은 이유).
// 그리고 여기서 잡고 싶은 것은 렌더가 아니라 **localStorage가 없거나 던질 때의 동작**이라,
// 오히려 순수 함수 쪽에서 더 정확히 볼 수 있다.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { clearChatId, loadChatId, newChatId, STORAGE_KEY } from './session'

afterEach(() => {
  localStorage.clear()
  vi.restoreAllMocks()
})

describe('loadChatId', () => {
  it('저장된 id가 있으면 그대로 이어 쓴다', () => {
    localStorage.setItem(STORAGE_KEY, 'thread-abc')

    expect(loadChatId()).toBe('thread-abc')
  })

  it('저장된 것이 없으면 새로 만들어 저장한다', () => {
    const id = loadChatId()

    expect(id).toBeTruthy()
    // ★ 만들기만 하고 저장을 안 하면 새로고침마다 새 대화가 된다 ★
    // 화면은 멀쩡히 동작하므로 "왜 기억을 못 하지"로만 드러나는 종류의 버그다.
    expect(localStorage.getItem(STORAGE_KEY)).toBe(id)
  })

  it('두 번 불러도 같은 id다', () => {
    expect(loadChatId()).toBe(loadChatId())
  })

  it('localStorage가 던져도 앱이 죽지 않는다', () => {
    // ★ 실제로 던지는 환경이 있다 ★ Safari 프라이빗 모드, 사이트 데이터 차단,
    // 일부 임베드(iframe with 3rd-party cookie 차단)에서 setItem이 예외를 던진다.
    // 여기서 안 막으면 **채팅 화면 전체가 흰 화면이 된다** — 기억을 못 하는 것보다
    // 훨씬 나쁜 실패다. 기억을 포기하되 동작은 유지한다.
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('QuotaExceededError')
    })

    const id = loadChatId()

    expect(id).toBeTruthy()
  })
})

describe('newChatId', () => {
  it('새 id를 만들고 저장한다 — "새 대화"가 새로고침을 넘어 유지된다', () => {
    const first = loadChatId()

    const second = newChatId()

    expect(second).not.toBe(first)
    expect(localStorage.getItem(STORAGE_KEY)).toBe(second)
  })
})

describe('clearChatId', () => {
  it('저장된 id를 지운다', () => {
    loadChatId()

    clearChatId()

    expect(localStorage.getItem(STORAGE_KEY)).toBeNull()
  })
})
