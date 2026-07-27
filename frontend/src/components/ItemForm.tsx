// 새 아이템을 입력받는 폼. 실제 저장(API 호출)은 하지 않고, 완성된 데이터를
// 부모가 넘겨준 onSubmit 콜백으로 전달하기만 한다 (실제 호출은 App.tsx에서 담당).
import { useState } from 'react'
import type { FormEvent } from 'react'
import type { ItemCreate } from '../types/item'

interface ItemFormProps {
  onSubmit: (item: ItemCreate) => void | Promise<void>
}

export function ItemForm({ onSubmit }: ItemFormProps) {
  // input 값들을 컴포넌트 state로 관리 (이른바 "controlled input" 패턴)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')

  async function handleSubmit(event: FormEvent) {
    event.preventDefault() // 기본 동작(페이지 새로고침)을 막는다
    if (!name.trim()) return // name이 비어있으면 제출하지 않음
    await onSubmit({ name, description: description || undefined })
    // 제출 성공 후 입력값 초기화
    setName('')
    setDescription('')
  }

  return (
    <form onSubmit={handleSubmit}>
      <input
        aria-label="name"
        placeholder="Item name"
        value={name}
        onChange={(e) => setName(e.target.value)}
      />
      <input
        aria-label="description"
        placeholder="Description (optional)"
        value={description}
        onChange={(e) => setDescription(e.target.value)}
      />
      <button type="submit">Add item</button>
    </form>
  )
}
