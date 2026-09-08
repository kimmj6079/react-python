// M10 실측: AI SDK가 "출처(source)" 파트를 와이어에 어떻게 싣는가.
//
// M1-1b와 완전히 같은 논리다 — 문서를 암기해 타이핑하지 말고 설치된 패키지에게
// 직접 물어본다. 1b에서 만들어둔 가짜 모델 방식을 그대로 재사용하므로 API 키도
// 네트워크도 필요 없고, 매번 같은 바이트가 나와 diff 비교가 된다.
//
// 실행: cd frontend && node scripts/capture-source-wire.mjs
import { streamText } from "ai";
import { MockLanguageModelV4, simulateReadableStream } from "ai/test";

// ★ 커스텀 data 파트를 새로 만들지 않고 SDK가 이미 아는 source를 쓴다 ★
// UIMessage의 파트 종류에 'source-document'가 이미 있다(실측: ai/dist/index.d.ts).
// 커스텀 파트를 만들면 프론트에서 타입을 우리가 정의해야 하고, useChat이 모르는
// 파트라 파싱 규칙도 우리 몫이 된다. 이미 있는 것을 쓰면 둘 다 공짜다.
const chunks = [
  { type: "stream-start", warnings: [] },
  { type: "text-start", id: "0" },
  { type: "text-delta", id: "0", delta: "빌드 타임에 정해집니다." },
  { type: "text-end", id: "0" },
  {
    type: "source",
    sourceType: "document",
    id: "CLAUDE.md#17",
    mediaType: "text/markdown",
    title: "CLAUDE.md > 아키텍처",
    filename: "CLAUDE.md",
  },
  {
    type: "finish",
    finishReason: { unified: "stop", raw: undefined },
    usage: {
      inputTokens: { total: 0, noCache: 0, cacheRead: 0, cacheWrite: 0 },
      outputTokens: { total: 0, text: 0, reasoning: 0 },
    },
  },
];

const model = new MockLanguageModelV4({
  doStream: { stream: simulateReadableStream({ chunks, chunkDelayInMs: 5 }) },
});

const res = streamText({ model, prompt: "hi" }).toUIMessageStreamResponse({
  // ★ 기본값으로는 source가 안 나갈 수 있다 ★ 1b에서 usage가 기본으로 안 실렸던
  // 것과 같은 성질 — "안쪽 포맷 ≠ 출력 포맷"이라 옵션을 확인해야 한다.
  sendSources: true,
});

console.log("--- body ---");
const decoder = new TextDecoder();
for await (const chunk of res.body) {
  console.log(JSON.stringify(decoder.decode(chunk)));
}
