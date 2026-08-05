// 백엔드 API를 호출하는 함수들을 모아둔 파일. 컴포넌트는 fetch를 직접 쓰지 않고 이 함수들을 사용한다.
import type { Item, ItemCreate } from '../types/item'

// VITE_API_URL은 빌드 타임에 정적으로 번들에 박히는 값(CLAUDE.md 참고).
// 값이 없으면(k8s 프로덕션 등) 상대경로가 되도록 빈 문자열 등을 기대하지만,
// 로컬 개발 기본값으로는 localhost:8000을 사용한다.
const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

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