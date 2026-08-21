import { streamText } from "ai";
//import { MockEmbeddingModelV4, MockLanguageModelV4, simulateReadableStream } from "ai/test";
import { MockLanguageModelV4, simulateReadableStream } from "ai/test";

console.log(typeof streamText, typeof MockLanguageModelV4, typeof simulateReadableStream);

const chunks = [
    {type : "stream-start", warnings: [] },
    {type : "text-start", id : "0"},
    {type : "text-delta", id : "0", delta : "안녕"},
    {type : "text-delta", id : "0", delta : "하세"},
    {type : "text-delta", id : "0", delta : "요"},
    {type : "text-end", id : "0"},
    {
        type: "finish",
        finishReason: { unified: "stop", raw: undefined },
            usage: {
            inputTokens: { total: 0, noCache: 0, cacheRead: 0, cacheWrite: 0 },
            outputTokens: { total: 0, text: 0, reasoning: 0 },
        }
    }
];

console.log(chunks.length);

const model = new MockLanguageModelV4({
    doStream : {
        stream : simulateReadableStream({chunks, chunkDelayInMs: 50}),
    }
})


console.log(model.modelId, model.specificationVersion);

const result = streamText({model,prompt:"hi"});
const res = result.toUIMessageStreamResponse();

console.log("status", res.status);

console.log("--- headers ---");
for (const[key, value] of res.headers){
    console.log(`${key}: ${value}`);
}

console.log("--- body ---");
const decoder = new TextDecoder();
for await (const chunk of res.body) {
  console.log(JSON.stringify(decoder.decode(chunk)));
}