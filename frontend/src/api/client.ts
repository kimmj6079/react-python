import type { Item, ItemCreate } from '../types/item'

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!response.ok) {
    throw new Error(`${init?.method ?? 'GET'} ${path} failed: ${response.status}`)
  }
  return response.json() as Promise<T>
}

export function listItems(): Promise<Item[]> {
  return request<Item[]>('/api/v1/items')
}

export function createItem(item: ItemCreate): Promise<Item> {
  return request<Item>('/api/v1/items', {
    method: 'POST',
    body: JSON.stringify(item),
  })
}
