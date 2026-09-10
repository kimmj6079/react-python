// M13 실측: AI SDK가 "메시지 메타데이터"를 와이어에 어떻게 싣는가.
//
// M1-1b(기본 봉투) · M10(source-document)와 완전히 같은 방법이다 — 문서를 암기해
// 타이핑하지 말고 설치된 패키지에게 직접 물어본다. 가짜 모델을 쓰므로 API 키도
// 네트워크도 필요 없고, 매번 같은 바이트가 나와 diff 비교가 된다.
//
// 알고 싶은 것 두 가지:
//   1) message-metadata 파트의 정확한 JSON 모양
//   2) 그 파트가 스트림의 **어디에** 오는가 (start 직후? finish 직전?)
//      -> 백엔드가 trace_id를 아는 시점은 "그래프가 다 돈 뒤"라서, 스트림 앞쪽에만
//         실을 수 있는 구조라면 설계를 바꿔야 한다. 그걸 확인하는 것이 이 스크립트의 목적.
//
// 실행: cd frontend && node scripts/capture-metadata-wire.mjs
import { streamText } from 'ai'
import { MockLanguageModelV4, simulateReadableStream } from 'ai/test'

const chunks = [
  { type: 'stream-start', warnings: [] },
  { type: 'text-start', id: '0' },
  { type: 'text-delta', id: '0', delta: '빌드 타임에 정해집니다.' },
  { type: 'text-end', id: '0' },
  {
    type: 'finish',
    finishReason: { unified: 'stop', raw: undefined },
    usage: {
      inputTokens: { total: 0, noCache: 0, cacheRead: 0, cacheWrite: 0 },
      outputTokens: { total: 0, text: 0, reasoning: 0 },
    },
  },
]

const model = new MockLanguageModelV4({
  doStream: { stream: simulateReadableStream({ chunks, chunkDelayInMs: 5 }) },
})

const res = streamText({ model, prompt: 'hi' }).toUIMessageStreamResponse({
  // messageMetadata는 값이 아니라 **콜백**이다(실측: index.d.ts:2525
  // "Called on start and finish events"). 즉 SDK도 "메타데이터는 나중에야
  // 알 수 있는 값"이라는 전제로 설계돼 있다 — 우리 sources_fn과 같은 사고방식.
  messageMetadata: ({ part }) => {
    if (part.type === 'start') return { traceId: 'start-시점에는-아직-모른다' }
    if (part.type === 'finish') return { traceId: '0123456789abcdef0123456789abcdef' }
    return undefined
  },
})

console.log('--- body ---')
const decoder = new TextDecoder()
for await (const chunk of res.body) {
  console.log(JSON.stringify(decoder.decode(chunk)))
}

// --- ② 프론트가 그걸 어떻게 읽는가 --------------------------------------
// 와이어에 실리는 것만 확인하고 끝내면 절반이다. useChat이 그 값을 어디에 두는지
// (message.metadata인지, parts 안 어딘가인지)를 봐야 Feedback.tsx를 쓸 수 있다.
// readUIMessageStream이 useChat 내부와 같은 어셈블러라 브라우저 없이 확인된다.
import { readUIMessageStream } from 'ai'

const model2 = new MockLanguageModelV4({
  doStream: { stream: simulateReadableStream({ chunks, chunkDelayInMs: 5 }) },
})
const uiStream = streamText({ model: model2, prompt: 'hi' }).toUIMessageStream({
  messageMetadata: ({ part }) =>
    part.type === 'finish' ? { traceId: '0123456789abcdef0123456789abcdef' } : undefined,
})

console.log('--- parsed (useChat이 보는 모양) ---')
for await (const message of readUIMessageStream({ stream: uiStream })) {
  console.log(
    JSON.stringify({ metadata: message.metadata, parts: message.parts.map((p) => p.type) }),
  )
}
