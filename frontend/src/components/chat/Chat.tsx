// 새 아이템을 입력받는 폼. 실제 저장(API 호출)은 하지 않고, 완성된 데이터를
// 부모가 넘겨준 onSubmit 콜백으로 전달하기만 한다 (실제 호출은 App.tsx에서 담당).
import { useEffect, useState } from 'react'
import { getChatHealth } from '../../api/client'

export function Chat() {
  const [status, setStatus] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  
  useEffect(() => {
    getChatHealth()
      .then((data) => {
        setStatus(data.status)
        setError(null)
      })
      .catch(() => {
        setStatus(null)
        setError('Failed to load chat health')
      })
    }, [])

    return (
        <section>
            <h1>Chat</h1>
            {error ? <p role="alert">{error}</p> : null}
            {status ? <p>backend status: {status}</p> : null}   
        </section>

    )
}