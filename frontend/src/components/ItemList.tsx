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
        <li key={item.id}>
          <strong>{item.name}</strong>
          {item.description ? ` — ${item.description}` : null}
        </li>
      ))}
    </ul>
  )
}
