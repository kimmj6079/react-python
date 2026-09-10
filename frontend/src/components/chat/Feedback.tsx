// 응답 피드백 버튼 (👍/👎). (M13)
//
// ★ 이 컴포넌트가 로드맵을 원형으로 닫는다 ★
// M6에서 손으로 만든 골든셋 24건은 **내가 상상한 질문**이다. 👎가 붙은 대화는
// 상상하지 못한 질문이고, 그것을 골든셋에 편입하면 회귀 테스트가 실사용에서 자란다.
// 즉 이 버튼 두 개는 UI 장식이 아니라 **평가 데이터의 입구**다.
//
// ★ 저장소를 새로 만들지 않는다 ★ 눌린 값은 Langfuse의 score로 간다(M4의 회수).
// 피드백 테이블 + 모델 + 마이그레이션을 새로 만들면 "피드백만 있고 그때 무슨 문맥을
// 썼는지는 모르는" 표가 생긴다. 트레이스에 붙어야 그 답이 무엇을 근거로 나왔는지까지
// 한 화면에서 보인다.
import { useState } from 'react'
import { sendChatFeedback } from '../../api/client'

type Value = 'up' | 'down'

/** 백엔드가 finish 프레임에 실어 보낸 traceId를 꺼낸다. 없으면 undefined.
 *
 * ★ metadata의 타입이 unknown인 것은 SDK의 의도다 ★ UIMessage<METADATA = unknown>
 * 이라(실측: ai/dist/index.d.ts:1830) 무엇이 들어 있는지는 앱이 정한다. 그래서
 * "우리 서버가 무엇을 넣는가"를 아는 이 한 곳에서만 좁히고, 나머지 화면 코드는
 * string | undefined만 본다. 타입 단언(as)을 여기저기 뿌리면 서버가 필드 이름을
 * 바꾼 날 **컴파일은 통과하고 런타임에 조용히 undefined**가 된다.
 *
 * export하지 않는다: 컴포넌트 파일이 컴포넌트 아닌 것을 함께 내보내면 Vite의
 * fast refresh가 깨진다(oxlint의 react(only-export-components) 경고). 다른 곳에서
 * 필요해지면 그때 별도 모듈로 옮긴다.
 */
function traceIdOf(metadata: unknown): string | undefined {
  if (!metadata || typeof metadata !== 'object') return undefined
  const value = (metadata as Record<string, unknown>).traceId
  return typeof value === 'string' && value ? value : undefined
}

export function Feedback({ metadata }: { metadata: unknown }) {
  // 이미 보낸 값. null이면 아직 안 눌렀다.
  const [sent, setSent] = useState<Value | null>(null)
  // 전송 중인 값. 연타로 두 번 나가는 것을 막고, 버튼에 '보내는 중' 표시를 준다.
  const [pending, setPending] = useState<Value | null>(null)
  const [failed, setFailed] = useState(false)

  // ★ 훅을 먼저 부르고 나서 early return 한다 ★ 조건부로 훅을 부르면 React가
  // 렌더마다 훅 순서를 맞추지 못해 터진다. Citations가 "출처가 없으면 null"인 것과
  // 같은 규칙인데, 저쪽은 훅이 없어서 순서를 신경 쓸 일이 없었다.
  //
  // ★ traceId가 없으면 아무것도 안 그린다 = 세 계층이 자동으로 맞물린다 ★
  //   Langfuse 키 없음 → 백엔드가 messageMetadata를 안 붙임 → 여기서 버튼이 안 그려짐.
  // "저장할 곳이 없으면 버튼도 없다"를 프론트에서 따로 판단하지 않는다.
  //
  // 덤: 메타데이터는 finish 프레임에만 실린다(실측). 그래서 **스트리밍 중에는
  // 자동으로 안 보이고** 답변이 끝나는 순간 나타난다 — status를 볼 필요가 없다.
  const traceId = traceIdOf(metadata)
  if (!traceId) return null

  // ★ function 선언이 아니라 const 화살표 함수다 ★ 위의 early return으로 traceId가
  // string으로 좁혀졌는데, function 선언은 호이스팅되어 "좁혀지기 전에도 호출될 수
  // 있는 것"으로 취급되기 때문에 그 안에서는 다시 string | undefined가 된다
  // (실제로 tsc가 TS2322로 잡아줬다). const 화살표는 선언 위치가 곧 정의 위치라
  // 좁힌 타입이 그대로 살아 있다.
  const submit = async (value: Value) => {
    // ★ 낙관적 업데이트를 일부러 안 한다 ★ 먼저 눌린 모양으로 바꿔놓고 실패 시
    // 되돌리는 방식이 반응은 빠르지만, 여기서는 "보냈다"는 표시가 곧 사용자에게
    // 하는 약속이다. 실제로 안 갔는데 갔다고 보여주면, 사용자는 자기 의견이
    // 반영됐다고 믿고 우리는 데이터가 없다 — 조용한 실패가 두 겹이 된다.
    // 요청 한 번은 수십 ms라 굳이 앞당길 이유도 없다.
    if (pending) return
    setPending(value)
    setFailed(false)
    try {
      await sendChatFeedback({ traceId, value })
      setSent(value)
    } catch {
      // 실패를 삼키지 않는다. 백엔드가 트레이싱 없이 503을 주는 경우가 대표적이다
      // (LANGFUSE_* 키가 없는 환경). 그때 아무 표시도 없으면 "눌러도 아무 일이
      // 없는 버튼"이 되고, 사용자는 우리 앱이 고장 났다고 판단한다.
      setFailed(true)
    } finally {
      setPending(null)
    }
  }

  return (
    <div className="fb">
      <button
        type="button"
        className={`fb__btn ${sent === 'up' ? 'fb__btn--on' : ''}`}
        // 이미 보낸 뒤에는 잠근다. 백엔드가 score_id를 trace_id로 고정해 멱등이긴
        // 하지만(같은 트레이스에 점수가 쌓이지 않는다), 그건 서버의 안전망이지
        // 사용자에게 보여줄 동작이 아니다. 화면에서도 "한 번"이 분명해야 한다.
        disabled={sent !== null || pending !== null}
        onClick={() => submit('up')}
        // 아이콘만 있는 버튼은 스크린리더에서 정체불명이 된다.
        aria-label="도움이 됐어요"
        title="도움이 됐어요"
      >
        👍
      </button>
      <button
        type="button"
        className={`fb__btn ${sent === 'down' ? 'fb__btn--on' : ''}`}
        disabled={sent !== null || pending !== null}
        onClick={() => submit('down')}
        aria-label="도움이 안 됐어요"
        title="도움이 안 됐어요"
      >
        👎
      </button>

      {/* role="status"는 스크린리더가 "화면이 조용히 바뀐 것"을 읽어주게 한다.
          시각 사용자에게는 색으로 보이는 변화가 그렇지 않은 사용자에게는 없다. */}
      {sent && (
        <span className="fb__note" role="status">
          피드백 고마워요
        </span>
      )}
      {failed && (
        <span className="fb__note fb__note--error" role="status">
          피드백을 보내지 못했어요
        </span>
      )}
    </div>
  )
}
