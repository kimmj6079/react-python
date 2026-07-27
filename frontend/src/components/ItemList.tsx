// items 배열을 받아 목록(<ul>)으로 렌더링만 하는 "표시 전용(presentational)" 컴포넌트.
// 데이터를 직접 가져오지 않고 props로 받기만 해서 재사용/테스트가 쉽다.
import type { Item } from '../types/item'

interface ItemListProps {
  items: Item[]
}

export function ItemList({ items }: ItemListProps) {
  if (items.length === 0) {
    return <p>No items yet.</p>
  }

  return (
    <ul>
      {items.map((item) => (
        // key: React가 리스트의 각 항목을 구분하기 위해 필요. 반드시 고유한 값(여기선 id)을 써야 한다.
        <li key={item.id}>
          <strong>{item.name}</strong>
          {item.description ? ` — ${item.description}` : null}
        </li>
      ))}
    </ul>
  )
}
