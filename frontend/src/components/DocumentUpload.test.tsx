import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as client from '../api/client'
import { DocumentUpload } from './DocumentUpload'

// API 모듈을 통째로 가짜로 바꾼다. 와이어 포맷(multipart, 응답 스키마)은 백엔드
// 테스트가 검증하므로, 여기서는 "화면이 API 결과를 어떻게 보여주는가"만 본다.
// App.test.tsx가 fetch를 안 가로채는 것과 같은 이유 — 같은 것을 두 곳에서 검증하지 않는다.
vi.mock('../api/client', () => ({
  getUploadLimits: vi.fn(),
  listDocuments: vi.fn(),
  uploadDocument: vi.fn(),
}))
const mocked = vi.mocked(client)

const LIMITS = { max_bytes: 10 * 1024 * 1024, allowed_suffixes: ['.md', '.pdf', '.txt'] }
const LIMITS_TEXT = '.md, .pdf, .txt · 최대 10MB'

function makeDoc(overrides: Partial<client.DocumentOut> = {}): client.DocumentOut {
  return {
    id: 1,
    source: 'upload/notes.md',
    filename: 'notes.md',
    status: 'done',
    error: null,
    chunk_count: 12,
    updated_at: '2026-09-17T00:00:00Z',
    ...overrides,
  }
}

describe('DocumentUpload', () => {
  beforeEach(() => {
    // 호출 기록을 비운다 — 세 번째 테스트의 not.toHaveBeenCalled가 두 번째 테스트의
    // 호출을 보고 실패하지 않게. 구현(mockResolvedValue)은 아래에서 다시 준다.
    vi.clearAllMocks()
    mocked.getUploadLimits.mockResolvedValue(LIMITS)
    mocked.listDocuments.mockResolvedValue([])
  })

  it('renders the drop zone with server-provided limits and an empty state', async () => {
    render(<DocumentUpload />)

    expect(screen.getByText('클릭해서 선택')).toBeInTheDocument()
    expect(screen.getByText(/아직 올린 문서가 없습니다/)).toBeInTheDocument()
    // 제한 문구는 서버 응답이 도착한 뒤에 나타나므로 findBy(비동기)로 기다린다.
    expect(await screen.findByText(LIMITS_TEXT)).toBeInTheDocument()
  })

  it('uploads a dropped file and shows it in the list', async () => {
    const doc = makeDoc({ status: 'processing', chunk_count: 0 })
    mocked.uploadDocument.mockResolvedValue({ document: doc, message: '인입을 시작했습니다' })
    render(<DocumentUpload />)
    await screen.findByText(LIMITS_TEXT)

    // drop은 input에서 시작해도 label까지 버블링되므로 label의 onDrop이 받는다.
    const file = new File(['# hi'], 'notes.md', { type: 'text/markdown' })
    fireEvent.drop(screen.getByLabelText(/파일을 끌어다 놓거나/), {
      dataTransfer: { files: [file] },
    })

    await waitFor(() => expect(mocked.uploadDocument).toHaveBeenCalledWith(file))
    expect(await screen.findByText('notes.md')).toBeInTheDocument()
    expect(screen.getByText('인입 중')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('인입을 시작했습니다')
  })

  it('rejects a file over the server limit without calling the API', async () => {
    render(<DocumentUpload />)
    await screen.findByText(LIMITS_TEXT)

    // 10MB 버퍼를 실제로 만들지 않고 size만 덮어쓴다. 검사하는 것은 숫자 비교다.
    const big = new File(['x'], 'big.pdf')
    Object.defineProperty(big, 'size', { value: LIMITS.max_bytes + 1 })
    fireEvent.drop(screen.getByLabelText(/파일을 끌어다 놓거나/), {
      dataTransfer: { files: [big] },
    })

    expect(await screen.findByRole('alert')).toHaveTextContent('파일이 너무 큽니다')
    expect(mocked.uploadDocument).not.toHaveBeenCalled()
  })
})
