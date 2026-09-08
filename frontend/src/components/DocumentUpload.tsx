// 문서 업로드 + 인입 상태 표시. (M11)
//
// ★ 이 화면이 있어야 하는 이유 ★ 인입은 수십 초 걸리고 백그라운드에서 돈다.
// 업로드 직후 "됐다"고만 하면 사용자는 곧바로 질문을 던졌다가 "문서에 없다"는 답을
// 받는다. 그래서 상태(pending/processing/done/failed)를 폴링해서 보여준다.
import { useCallback, useEffect, useRef, useState } from 'react'

import {
  getUploadLimits,
  listDocuments,
  uploadDocument,
  type DocumentOut,
} from '../api/client'

// 폴링 주기. 짧으면 서버를 두드리고 길면 "끝났는데 화면이 안 바뀐다"가 된다.
// 인입이 문서당 30초 남짓이라 2초면 충분히 촘촘하다.
const POLL_MS = 2000

const STATUS_LABEL: Record<DocumentOut['status'], string> = {
  pending: '대기 중',
  processing: '인입 중…',
  done: '완료',
  failed: '실패',
}

export function DocumentUpload() {
  const [documents, setDocuments] = useState<DocumentOut[]>([])
  const [limits, setLimits] = useState<{ max_bytes: number; allowed_suffixes: string[] } | null>(
    null,
  )
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const refresh = useCallback(async () => {
    try {
      setDocuments(await listDocuments())
    } catch {
      // 목록 갱신 실패는 조용히 넘긴다 — 폴링이라 다음 주기에 다시 시도한다.
      // 여기서 에러를 띄우면 잠깐의 네트워크 끊김에 화면이 빨개진다.
    }
  }, [])

  useEffect(() => {
    getUploadLimits().then(setLimits).catch(() => {})
    refresh()
  }, [refresh])

  // ★ 진행 중인 문서가 있을 때만 폴링한다 ★ 항상 돌리면 아무 일도 없는 화면이
  // 2초마다 서버를 두드린다. 끝나면 스스로 멈추는 것이 폴링의 최소 예의다.
  useEffect(() => {
    const pending = documents.some((d) => d.status === 'pending' || d.status === 'processing')
    if (!pending) return
    const timer = setInterval(refresh, POLL_MS)
    return () => clearInterval(timer)
  }, [documents, refresh])

  async function handleFile(file: File) {
    setError(null)
    setNotice(null)

    // ★ 서버가 알려준 제한으로 먼저 거른다 ★ 10MB를 올려놓고 413을 받는 것보다
    // 고르는 순간 막는 편이 낫다. 숫자를 하드코딩하지 않고 서버에서 받아오므로
    // 서버가 제한을 바꾸면 프론트도 자동으로 따라간다.
    if (limits && file.size > limits.max_bytes) {
      setError(`파일이 너무 큽니다 (최대 ${Math.floor(limits.max_bytes / 1024 / 1024)}MB)`)
      return
    }

    setBusy(true)
    try {
      const result = await uploadDocument(file)
      setNotice(result.message)
      setDocuments((prev) => [
        result.document,
        ...prev.filter((d) => d.id !== result.document.id),
      ])
    } catch (e) {
      setError(e instanceof Error ? e.message : '업로드에 실패했습니다')
    } finally {
      setBusy(false)
      // 같은 파일을 다시 고를 수 있게 값을 비운다 — 안 비우면 onChange가 안 뜬다.
      if (inputRef.current) inputRef.current.value = ''
    }
  }

  return (
    <section className="docs">
      <h2 className="docs__title">문서</h2>
      <p className="docs__hint">
        올린 문서는 청킹·임베딩을 거쳐 챗봇의 검색 대상이 됩니다.
        {limits && ` (${limits.allowed_suffixes.join(', ')} · 최대 ${Math.floor(limits.max_bytes / 1024 / 1024)}MB)`}
      </p>

      <input
        ref={inputRef}
        type="file"
        accept={limits?.allowed_suffixes.join(',')}
        disabled={busy}
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) void handleFile(file)
        }}
      />
      {busy && <span className="docs__busy"> 업로드 중…</span>}

      {error && <p className="docs__error">{error}</p>}
      {notice && <p className="docs__notice">{notice}</p>}

      <ul className="docs__list">
        {documents.map((doc) => (
          <li key={doc.id} className={`docs__item docs__item--${doc.status}`}>
            <span className="docs__name">{doc.filename}</span>
            <span className="docs__status">{STATUS_LABEL[doc.status]}</span>
            {doc.status === 'done' && <span className="docs__meta">청크 {doc.chunk_count}개</span>}
            {/* ★ 실패 이유를 반드시 화면에 띄운다 ★ 여기서 삼키면 사용자는
                "올렸는데 왜 답을 못 하지"만 보게 되고, 고칠 방법을 알 수 없다. */}
            {doc.error && <span className="docs__errmsg">{doc.error}</span>}
          </li>
        ))}
        {documents.length === 0 && <li className="docs__empty">아직 올린 문서가 없습니다.</li>}
      </ul>
    </section>
  )
}
