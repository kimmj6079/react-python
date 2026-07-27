// 백엔드 스키마(backend/app/schemas/item.py)와 대응되는 TypeScript 타입 정의.
// 백엔드 필드가 바뀌면 이 파일도 함께 맞춰줘야 타입 에러 없이 안전하게 쓸 수 있다.

// 서버에서 응답으로 받는 아이템의 형태 (ItemRead와 대응)
export interface Item {
  id: number
  name: string
  description: string | null
  created_at: string
}

// 서버로 생성 요청을 보낼 때의 형태 (ItemCreate와 대응, id/created_at은 서버가 채우므로 없음)
export interface ItemCreate {
  name: string
  description?: string
}
