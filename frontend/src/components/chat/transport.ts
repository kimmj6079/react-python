// useChat이 "어디로 · 어떤 본문으로" 보낼지를 정하는 계층.
//
// 왜 Chat.tsx에서 분리했나: 이건 UI가 아니라 와이어 계약이다. 백엔드에서
// core/ai_sdk.py(와이어 포맷)와 api/routes/chat.py(HTTP)를 나눈 것과 같은 선을
// 프론트에도 긋는다. 덤으로 아래 prepareChatRequest가 순수 함수가 되어
// React 없이 테스트할 수 있다.
//
// 여기 쓰인 API는 실측이다 (ai@7.0.79, index.js:17833). 버전을 올리면 다시 본다.
import { DefaultChatTransport, type PrepareSendMessagesRequest, type UIMessage } from "ai"
import { CHAT_API_URL } from "../../api/client"

// SDK가 콜백에 넘겨주는 인자 묶음의 타입을 그대로 빌려온다.
// Parameters<T>[0]은 "함수 타입 T의 첫 번째 파라미터 타입"을 뽑는 유틸리티 타입이다.
// 이렇게 하면 SDK가 인자를 하나 추가해도 우리가 손으로 따라 적을 필요가 없고,
// 반대로 우리가 잘못된 이름을 구조분해하면 컴파일 에러로 잡힌다.
type PrepareArgs = Parameters<PrepareSendMessagesRequest<UIMessage>>[0]

export function prepareChatRequest({id, messages, trigger, messageId} : PrepareArgs) {
  // ★ 2b-3의 전부 ★
  // 2b-2까지는 이 콜백이 없어서 SDK 기본 본문이 나갔다 — 히스토리 전체다.
  // 서버는 2b-1부터 마지막 하나만 쓰고 나머지를 버리고 있었으므로,
  // 여기서 줄이는 것은 "동작 변경"이 아니라 "이미 안 쓰는 데이터를 안 보내는 것"이다.
  // 그래서 백엔드도 테스트도 한 줄 안 바뀐다.
  //
  // ★ 반환한 body가 기본 본문을 통째로 "대체"한다 (병합 아님, 실측) ★
  // 그래서 id · trigger · messageId를 여기서 직접 넣어야 한다. 빼먹으면
  // schemas/chat.py의 ChatRequest 검증에 걸려 422가 난다.    
  return{
    body : {
      id,
      // slice(-1)이지 messages[messages.length - 1]이 아니다.
      //   - slice는 "배열"을 준다. 스키마가 messages: list[UIMessage]라 배열이어야 한다.
      //   - 빈 배열이어도 안전하게 []를 준다. 인덱스 접근은 [undefined]가 되어
      //     JSON에 [null]로 실려 나가고, 서버에서 422가 난다.
      messages: messages.slice(-1),
      trigger,
      messageId,        
    }
  }
}

// transport는 "어디로 어떻게 보낼까"만 들고 있는 객체라 렌더마다 새로 만들 이유가 없다.
// import 출처에 주의: 훅은 '@ai-sdk/react'인데 DefaultChatTransport는 코어인 'ai'에 있다.
export const chatTransport = new DefaultChatTransport({
  api: CHAT_API_URL,
  prepareSendMessagesRequest: prepareChatRequest,
})