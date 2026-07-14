import { useEffect, useState } from 'react'
import { createItem, listItems } from './api/client'
import { ItemForm } from './components/ItemForm'
import { ItemList } from './components/ItemList'
import type { Item, ItemCreate } from './types/item'
import './App.css'

function App() {
  const [items, setItems] = useState<Item[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    listItems()
      .then(setItems)
      .catch(() => setError('Failed to load items'))
  }, [])

  async function handleCreate(itemIn: ItemCreate) {
    try {
      const created = await createItem(itemIn)
      setItems((prev) => [...prev, created])
      setError(null)
    } catch {
      setError('Failed to create item')
    }
  }

  return (
    <main>
      <h1>Items</h1>
      {error ? <p role="alert">{error}</p> : null}
      <ItemForm onSubmit={handleCreate} />
      <ItemList items={items} />
    </main>
  )
}

export default App
