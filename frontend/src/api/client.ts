// 백엔드 API를 호출하는 함수들을 모아둔 파일. 컴포넌트는 fetch를 직접 쓰지 않고 이 함수들을 사용한다.
import type { Item, ItemCreate } from '../types/item'

// VITE_API_URL은 빌드 타임에 정적으로 번들에 박히는 값(CLAUDE.md 참고).
// 값이 없으면(k8s 프로덕션 등) 상대경로가 되도록 빈 문자열 등을 기대하지만,
// 로컬 개발 기본값으로는 localhost:8000을 사용한다.
const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

// POST /api/v1/chat 의 전체 주소.
// useChat은 내부에서 자기 fetch를 돌리므로 아래 request() 헬퍼를 통과하지 않는다.
// 그래도 "주소를 만드는 규칙"은 이 파일 하나에만 둔다 — 안 그러면 VITE_API_URL 처리가 두 갈래로 갈라진다.
export const CHAT_API_URL = `${API_URL}/api/v1/chat`

// fetch를 감싼 공통 헬퍼. 에러 처리와 JSON 파싱을 한 곳에서 처리해서 중복을 줄인다.
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!response.ok) {
    // fetch는 4xx/5xx 응답이어도 예외를 던지지 않으므로, 여기서 직접 체크해서 던져줘야 한다.
    throw new Error(`${init?.method ?? 'GET'} ${path} failed: ${response.status}`)
  }
  return response.json() as Promise<T>
}

// GET /api/v1/items : 아이템 전체 목록 조회
export function listItems(): Promise<Item[]> {
  return request<Item[]>('/api/v1/items')
}

// POST /api/v1/items : 아이템 생성
export function createItem(item: ItemCreate): Promise<Item> {
  return request<Item>('/api/v1/items', {
    method: 'POST',
    body: JSON.stringify(item),
  })
}

// GET /api/v1/chat/health : 채팅 서버 상태 확인
export function getChatHealth(): Promise<{ status: string }> {
  return request<{ status: string }>('/api/v1/chat/health')
}

// ─── M11: 문서 업로드 · 인입 상태 ───

export type DocumentStatus = 'pending' | 'processing' | 'done' | 'failed'

export interface DocumentOut {
  id: number
  source: string
  filename: string
  status: DocumentStatus
  // 실패 이유. 조용히 삼키면 "업로드는 됐는데 검색은 안 되는" 최악의 상태가 되므로
  // 백엔드가 여기 담아 보내고 화면이 그대로 보여준다.
  error: string | null
  chunk_count: number
  updated_at: string
}

export interface UploadResult {
  document: DocumentOut
  message: string
}

// POST /api/v1/documents (multipart)
// ★ request() 헬퍼를 안 쓴다 ★ 그 헬퍼는 Content-Type을 application/json으로 고정하는데,
// multipart는 브라우저가 boundary를 포함한 헤더를 직접 만들어야 한다. 우리가 지정하면
// boundary가 빠져서 서버가 파싱하지 못한다 — 그래서 헤더를 아예 주지 않는다.
export async function uploadDocument(file: File): Promise<UploadResult> {
  const form = new FormData()
  form.append('file', file)
  const response = await fetch(`${API_URL}/api/v1/documents`, { method: 'POST', body: form })
  if (!response.ok) {
    // 백엔드가 detail에 사람이 읽을 이유를 담아 보낸다(형식 미지원, 용량 초과 등).
    // status만 던지면 사용자는 무엇을 고쳐야 할지 알 수 없다.
    const detail = await response.json().catch(() => null)
    throw new Error(detail?.detail ?? `업로드 실패 (${response.status})`)
  }
  return response.json() as Promise<UploadResult>
}

// GET /api/v1/documents : 인입된 문서 목록 + 상태
export function listDocuments(): Promise<DocumentOut[]> {
  return request<DocumentOut[]>('/api/v1/documents')
}

// GET /api/v1/documents/meta/limits : 업로드 제한
// 같은 숫자를 프론트에 하드코딩하면 서버가 제한을 바꿀 때 두 곳이 어긋난다.
export function getUploadLimits(): Promise<{ max_bytes: number; allowed_suffixes: string[] }> {
  return request('/api/v1/documents/meta/limits')
}
