// 인용 카드. 답변 아래에 "무엇을 근거로 답했는지"를 보여준다. (M10)
//
// ★ RAG의 실제 사고는 "검색이 실패해서"보다 "검색은 됐는데 LLM이 문맥 밖 얘기를
// 섞어서" 난다 ★ 사용자는 어느 문장이 문서 근거이고 어느 문장이 모델의 사전지식인지
// 구분할 방법이 없다. 사내 챗봇을 실제로 쓰게 하려면 여기가 사실상 필수다.
//
// ★ 이 카드의 출처는 모델이 만든 것이 아니다 ★ 백엔드가 "실제로 프롬프트에 넣은
// 청크"를 그대로 내보낸다(ai_sdk.py의 source_part). 프롬프트에 [1][2] 번호를 쓰게
// 하는 방식과 결정적으로 다른 점이다 — 모델은 없는 번호를 지어낼 수 있지만
// 이건 지어낼 수가 없다.
import type { UIMessage } from 'ai'

// useChat이 파싱해준 파트 중 출처만 고른다. 커스텀 파트가 아니라 SDK가 이미 아는
// 'source-document' 타입이라(M10 실측) 우리가 파싱 규칙을 만들 필요가 없었다.
type SourcePart = Extract<UIMessage['parts'][number], { type: 'source-document' }>

export function Citations({ parts }: { parts: UIMessage['parts'] }) {
  const sources = parts.filter((p): p is SourcePart => p.type === 'source-document')

  // ★ 없는 것과 비어 있는 것은 다르다 ★ 출처가 없을 때 빈 상자를 그리면
  // 사용자는 "출처가 있는데 안 보이나?"로 읽는다. 아예 아무것도 안 그린다.
  if (sources.length === 0) return null

  return (
    <div className="cites">
      <span className="cites__label">근거 문서</span>
      <ul className="cites__list">
        {sources.map((s) => (
          <li key={s.sourceId} className="cites__item">
            <span className="cites__file">{s.filename}</span>
            {/* title은 heading_path다(M7에서 붙인 것). "CLAUDE.md"만으로는 850줄
                문서의 어디인지 알 수 없고, 경로가 있어야 검증하러 갈 위치가 생긴다. */}
            {s.title && s.title !== s.filename && (
              <span className="cites__where">{s.title}</span>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}
