import { useState } from 'react'
import type { FormEvent } from 'react'
import type { ItemCreate } from '../types/item'

interface ItemFormProps {
  onSubmit: (item: ItemCreate) => void | Promise<void>
}

export function ItemForm({ onSubmit }: ItemFormProps) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (!name.trim()) return
    await onSubmit({ name, description: description || undefined })
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
