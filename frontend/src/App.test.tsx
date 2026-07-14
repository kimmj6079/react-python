import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import App from './App'
import * as client from './api/client'

vi.mock('./api/client')
const mockedClient = vi.mocked(client)

describe('App', () => {
  it('lists items loaded from the API', async () => {
    mockedClient.listItems.mockResolvedValue([
      { id: 1, name: 'keyboard', description: 'mechanical', created_at: '2026-01-01T00:00:00Z' },
    ])

    render(<App />)

    expect(await screen.findByText('keyboard')).toBeInTheDocument()
  })

  it('submits the form and appends the created item', async () => {
    mockedClient.listItems.mockResolvedValue([])
    mockedClient.createItem.mockResolvedValue({
      id: 2,
      name: 'mouse',
      description: null,
      created_at: '2026-01-01T00:00:00Z',
    })

    render(<App />)
    const user = userEvent.setup()

    await user.type(screen.getByLabelText('name'), 'mouse')
    await user.click(screen.getByRole('button', { name: /add item/i }))

    expect(await screen.findByText('mouse')).toBeInTheDocument()
    expect(mockedClient.createItem).toHaveBeenCalledWith({ name: 'mouse', description: undefined })
  })
})
