// 최상위 컴포넌트. 상태(items, error)를 관리하고, 실제 API 호출은 여기서 담당한 뒤
// 하위 컴포넌트(ItemForm, ItemList)에는 필요한 데이터/콜백만 props로 내려준다.
import { useEffect, useState } from 'react'
import { createItem, listItems } from './api/client'
import { ItemForm } from './components/ItemForm'
import { ItemList } from './components/ItemList'
import type { Item, ItemCreate } from './types/item'
import { Chat } from './components/chat/Chat'
import './App.css'

function App() {
  const [view, setView] = useState<'items' | 'chat'>('items')
  const [items, setItems] = useState<Item[]>([])
  const [error, setError] = useState<string | null>(null)

  // useEffect(..., []) : 의존성 배열이 비어있으므로 컴포넌트가 처음 화면에 나타날 때 딱 한 번만 실행된다.
  // 여기서는 최초 렌더링 시 서버에서 아이템 목록을 불러온다.
  useEffect(() => {
    listItems()
      .then(setItems)
      .catch(() => setError('Failed to load items'))
  }, [])

  // ItemForm이 제출될 때 호출되는 콜백. 실제 생성 API를 호출하고 성공하면
  // 서버에 다시 요청하지 않고 방금 생성된 아이템을 로컬 상태에 바로 추가한다(낙관적 업데이트에 가까움).
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
      <nav>
        <button onClick={() => setView('items')}>Items</button>
        <button onClick={() => setView('chat')}>Chat</button>
      </nav>

      {/* view 상태에 따라 다른 화면을 보여준다. (SPA)*/ }
      {view === 'items' && (
        <>
          <h1>Items</h1>
          {error ? <p role="alert">{error}</p> : null}
          <ItemForm onSubmit={handleCreate} />
          <ItemList items={items} />
        </>
      )}

      {view === 'chat' && <Chat />}
      
    </main>
  )
}

export default App
