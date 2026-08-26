import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import App from './App'

describe('App', () => {
  // 스모크 테스트: 챗 화면이 그려지는지만 본다.
  // useChat의 실제 통신은 여기서 검증하지 않는다 - fetch를 가로채야 하는데,
  // 와이어 포맷은 백엔드 tests/test_chat.py가 바이트 단위로 이미 검증하고 있다.
  // 같은 것을 두 곳에서 검증하면 포맷이 바뀔 때 고칠 곳만 두 배가 된다.
  it('renders the chat view', () => {
    render(<App />)

    expect(screen.getByRole('heading', { name: 'Chat' })).toBeInTheDocument()
    expect(screen.getByPlaceholderText('메시지를 입력하세요')).toBeInTheDocument()
  })
})
