// 문서 업로드 + 인입 상태 표시. (M11, 퍼블 정리 2026-09-17)
//
// ★ 이 화면이 있어야 하는 이유 ★ 인입은 수십 초 걸리고 백그라운드에서 돈다.
// 업로드 직후 "됐다"고만 하면 사용자는 곧바로 질문을 던졌다가 "문서에 없다"는 답을
// 받는다. 그래서 상태(pending/processing/done/failed)를 폴링해서 보여준다.
//
// 스타일은 옆의 DocumentUpload.css에 있다(Chat.css와 같은 배치). 이 파일은
// "무엇을 보여줄지"만 정하고, "어떻게 보일지"는 CSS가 맡는다.
import { useCallback, useEffect, useRef, useState, type DragEvent } from 'react'

import { getUploadLimits, listDocuments, uploadDocument, type DocumentOut } from '../api/client'
import './DocumentUpload.css'

// 폴링 주기. 짧으면 서버를 두드리고 길면 "끝났는데 화면이 안 바뀐다"가 된다.
// 인입이 문서당 30초 남짓이라 2초면 충분히 촘촘하다.
const POLL_MS = 2000

const STATUS_LABEL: Record<DocumentOut['status'], string> = {
  pending: '대기 중',
  processing: '인입 중',
  done: '완료',
  failed: '실패',
}

type UploadLimits = { max_bytes: number; allowed_suffixes: string[] }

// 서버가 준 제한을 사람이 읽는 한 줄로. 숫자를 여기 박지 않는 이유는 handleFile의
// 크기 검사와 같다 — 서버가 제한을 바꾸면 화면 문구도 저절로 따라가야 한다.
function describeLimits(limits: UploadLimits): string {
  const mb = Math.floor(limits.max_bytes / 1024 / 1024)
  return `${limits.allowed_suffixes.join(', ')} · 최대 ${mb}MB`
}

// 'CLAUDE.md' → 'MD'. 목록에서 파일 종류를 한눈에 구분하는 배지용.
function fileBadge(filename: string): string {
  const dot = filename.lastIndexOf('.')
  return dot > 0 ? filename.slice(dot + 1).toUpperCase() : 'FILE'
}

// ISO 문자열 → '9. 17. 09:10'. 서버는 UTC로 주고 브라우저가 로컬 시간으로 바꾼다.
// 파싱에 실패하면 빈 문자열 — 날짜 하나 때문에 목록 전체가 깨지면 안 된다.
function formatUpdatedAt(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleString('ko-KR', {
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function DocumentUpload() {
  const [documents, setDocuments] = useState<DocumentOut[]>([])
  const [limits, setLimits] = useState<UploadLimits | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  // 파일을 드롭존 위로 끌고 있는 동안만 true. 시각 피드백(테두리·배경색) 전용이다.
  const [dragging, setDragging] = useState(false)
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
    getUploadLimits()
      .then(setLimits)
      .catch(() => {})
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
      setDocuments((prev) => [result.document, ...prev.filter((d) => d.id !== result.document.id)])
    } catch (e) {
      setError(e instanceof Error ? e.message : '업로드에 실패했습니다')
    } finally {
      setBusy(false)
      // 같은 파일을 다시 고를 수 있게 값을 비운다 — 안 비우면 onChange가 안 뜬다.
      if (inputRef.current) inputRef.current.value = ''
    }
  }

  // ── 드래그앤드롭 ──
  // ★ preventDefault가 핵심이다 ★ 브라우저의 기본 동작은 "드롭된 파일을 열기"라서,
  // dragover와 drop 둘 다에서 막지 않으면 페이지가 그 파일로 바뀌어 버린다.
  function handleDragOver(e: DragEvent<HTMLElement>) {
    e.preventDefault()
    if (!busy) setDragging(true)
  }
  function handleDragLeave() {
    setDragging(false)
  }
  function handleDrop(e: DragEvent<HTMLElement>) {
    e.preventDefault()
    setDragging(false)
    if (busy) return
    // 여러 개를 떨어뜨려도 첫 파일만 받는다. 업로드 API가 한 번에 한 파일이라
    // 화면도 그 계약을 그대로 따른다 — 다중 업로드는 API가 바뀔 때 같이 바꾼다.
    const file = e.dataTransfer.files?.[0]
    if (file) void handleFile(file)
  }

  const inProgress = documents.filter(
    (d) => d.status === 'pending' || d.status === 'processing',
  ).length

  // 조건부 클래스. 라이브러리(clsx) 없이 이 정도는 배열+filter로 충분하다.
  const dropClass = ['docs__drop', dragging && 'docs__drop--over', busy && 'docs__drop--busy']
    .filter(Boolean)
    .join(' ')

  return (
    <section className="docs">
      <div className="docs__inner">
        <header className="docs__head">
          <h2 className="docs__title">문서</h2>
          <p className="docs__hint">올린 문서는 청킹·임베딩을 거쳐 챗봇의 검색 대상이 됩니다.</p>
        </header>

        {/* label이 드롭존이다. 안의 input과 묶여 있어서 어디를 클릭해도 파일 창이
            열린다 — onClick으로 input.click()을 부르는 JS가 필요 없다. */}
        <label
          className={dropClass}
          aria-busy={busy}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
        >
          {/* 시각적으로만 숨긴다(CSS .docs__input). display:none이면 Tab 키로 도달할
              수 없어서 키보드 사용자는 파일을 올릴 방법이 없어진다. */}
          <input
            ref={inputRef}
            className="docs__input"
            type="file"
            accept={limits?.allowed_suffixes.join(',')}
            disabled={busy}
            onChange={(e) => {
              const file = e.target.files?.[0]
              if (file) void handleFile(file)
            }}
          />
          <svg
            className="docs__drop-icon"
            viewBox="0 0 24 24"
            width="28"
            height="28"
            aria-hidden="true"
          >
            <path
              d="M12 16V4m0 0-4 4m4-4 4 4"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
            <path
              d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
            />
          </svg>
          <span className="docs__drop-title">
            {busy ? (
              '업로드 중…'
            ) : (
              <>
                파일을 끌어다 놓거나 <em>클릭해서 선택</em>
              </>
            )}
          </span>
          {/* 제한 문구는 서버 응답이 있을 때만. "확인하는 중…" 같은 임시 문구를 두면
              백엔드가 죽어 있을 때 영원히 그 상태로 남아 사용자를 속인다. */}
          {limits && <span className="docs__drop-meta">{describeLimits(limits)}</span>}
        </label>

        {/* role: 에러는 alert(즉시 읽어줌), 안내는 status(차례가 오면 읽어줌).
            스크린리더 사용자에게도 "올렸다/실패했다"가 눈으로 보는 것과 같은 타이밍에 닿는다. */}
        {error && (
          <p className="docs__alert docs__alert--error" role="alert">
            {error}
          </p>
        )}
        {notice && (
          <p className="docs__alert docs__alert--ok" role="status">
            {notice}
          </p>
        )}

        <div className="docs__list-head">
          <h3 className="docs__list-title">올린 문서</h3>
          <span className="docs__count">
            {documents.length}개{inProgress > 0 && ` · ${inProgress}개 진행 중`}
          </span>
        </div>

        <ul className="docs__list">
          {documents.map((doc) => (
            <li key={doc.id} className={`docs__item docs__item--${doc.status}`}>
              <span className="docs__badge" aria-hidden="true">
                {fileBadge(doc.filename)}
              </span>
              <div className="docs__body">
                {/* title: 말줄임된 긴 파일명을 hover로 전체 확인할 수 있게. */}
                <span className="docs__name" title={doc.filename}>
                  {doc.filename}
                </span>
                <span className="docs__meta">
                  {doc.status === 'done' && `청크 ${doc.chunk_count}개 · `}
                  {formatUpdatedAt(doc.updated_at)}
                </span>
                {/* ★ 실패 이유를 반드시 화면에 띄운다 ★ 여기서 삼키면 사용자는
                    "올렸는데 왜 답을 못 하지"만 보게 되고, 고칠 방법을 알 수 없다. */}
                {doc.error && <span className="docs__errmsg">{doc.error}</span>}
              </div>
              <span className={`docs__status docs__status--${doc.status}`}>
                <i className="docs__dot" aria-hidden="true" />
                {STATUS_LABEL[doc.status]}
              </span>
            </li>
          ))}
          {documents.length === 0 && (
            <li className="docs__empty">
              아직 올린 문서가 없습니다. 위에 파일을 올리면 여기에 진행 상태가 표시됩니다.
            </li>
          )}
        </ul>
      </div>
    </section>
  )
}
