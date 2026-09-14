// 대화 세션 id를 새로고침 너머로 유지한다. (M5-3)
//
// ★ 이 파일이 왜 M5-3에서야 생겼나 ★
// 2b-2에서 `chatId`를 컴포넌트가 소유하게 만들면서 "새로고침하면 새 id가 생긴다 =
// 서버에도 새 스레드다. 화면도 비어 있으니 앞뒤가 맞는다"고 적어뒀었다.
// **그때는 정말로 앞뒤가 맞았다** — 체크포인터가 InMemorySaver라 서버 쪽 대화도
// 프로세스와 함께 사라지는 것이 기본이었으니까.
//
// M5-2에서 대화가 Postgres로 옮겨가면서 그 전제가 깨졌다. 이제 서버는 대화를 계속
// 갖고 있는데 브라우저만 그 주소(thread_id)를 잊어버린다 — **데이터는 남았는데
// 가리킬 손잡이를 잃는** 상태다. 그래서 id를 유지한다.
//
// ★ 이게 곧 "누구인가"의 대용품이라는 점을 알고 쓴다 ★ 인증이 없으니 이 id 하나가
// 사용자를 식별하는 유일한 값이다. 그래서:
//   - 브라우저를 바꾸면 남의 대화가 아니라 **내 대화도** 못 찾는다(동기화 없음)
//   - 같은 브라우저를 쓰는 다른 사람이 내 대화를 그대로 본다
// 실무에서는 로그인 뒤 서버가 스레드 목록을 주고, localStorage는 "마지막으로 보던
// 대화" 정도만 기억한다. 지금 구조는 그 방향으로 갈 때 이 파일만 바뀐다.

import { generateId } from 'ai'

// 키에 접두어를 붙인다. localStorage는 오리진 전체가 공유하는 공간이라
// 'chatId' 같은 흔한 이름은 같은 도메인에 올라간 다른 앱과 충돌한다
// (docker-compose 운영 배포에서 한 VM에 여러 앱을 올리는 구조라 실제로 가능한 일이다).
export const STORAGE_KEY = 'react-python:chat-id'

/**
 * localStorage 접근을 감싸는 이유 = **던지는 환경이 실제로 있다.**
 *
 * Safari 프라이빗 모드, 브라우저의 사이트 데이터 차단, 서드파티 쿠키가 막힌 iframe에서
 * `localStorage`는 접근만 해도 SecurityError를, `setItem`은 QuotaExceededError를 던진다.
 * 이걸 안 막으면 예외가 렌더 중에 터져 **채팅 화면 전체가 흰 화면이 된다** —
 * "대화를 기억하지 못한다"보다 훨씬 나쁜 실패다.
 *
 * 그래서 규칙을 하나로 정한다: **기억은 포기하되 동작은 유지한다.**
 * (백엔드에서 "Langfuse 키가 없으면 트레이싱만 꺼지고 앱은 돈다"로 정한 것과 같은 판단이다.)
 */
function read(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY)
  } catch {
    return null
  }
}

function write(id: string): void {
  try {
    localStorage.setItem(STORAGE_KEY, id)
  } catch {
    // 저장에 실패해도 이번 세션은 정상 동작한다. 새로고침하면 새 대화가 될 뿐이다.
  }
}

/** 이어서 쓸 대화 id. 없으면 만들어 저장한다. */
export function loadChatId(): string {
  const saved = read()
  if (saved) return saved
  const id = generateId()
  // ★ 만들기만 하고 저장을 빼먹으면 새로고침마다 새 대화가 된다 ★
  // 화면은 멀쩡히 동작해서 "왜 기억을 못 하지"로만 드러난다. 테스트로 못 박아뒀다.
  write(id)
  return id
}

/** "새 대화" 버튼용. 새 id를 만들고 그것을 앞으로의 대화로 저장한다. */
export function newChatId(): string {
  const id = generateId()
  write(id)
  return id
}

/** 저장된 id를 지운다. 지금은 테스트가 쓰고, 나중에 "로그아웃"이 생기면 거기서 쓴다. */
export function clearChatId(): void {
  try {
    localStorage.removeItem(STORAGE_KEY)
  } catch {
    // 지우지 못해도 할 수 있는 일이 없다.
  }
}
