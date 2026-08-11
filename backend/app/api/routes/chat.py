# Kubernetes가 컨테이너 상태를 확인할 때 호출하는 헬스체크 엔드포인트들.
import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.api.deps import AnthropicClient
from app.core.config import settings
from app.schemas.chat import ChatRequest

router = APIRouter(tags=["chat"])


@router.get("/chat/health")
def chat_health() -> dict[str, str]:
    """
    채팅 서버 상태 확인
    """
    return {"status": "ok"}


@router.post("/chat")
async def chat(payload: ChatRequest, client: AnthropicClient) -> StreamingResponse:
    async def event_stream():
        # async with: 스트림이 끝나거나 예외가 나도 연결을 확실히 정리해준다.
        async with client.messages.stream(
            model=settings.anthropic_model,
            max_tokens=1024,
            messages=[{"role": "user", "content": payload.message}],
        ) as stream:
            # text_stream은 텍스트 델타만 골라서 문자열로 주는 편의 iterator.
            async for text in stream.text_stream:
                # 그냥 f"data: {text}" 로 쓰면 안 된다. text에 개행이 들어오는 순간
                # SSE의 줄 구조가 깨진다. JSON으로 감싸면 개행이 "\n" 두 글자로
                # 이스케이프되어 안전하다. ensure_ascii=False는 한글이 \uXXXX로
                # 깨져 보이지 않게 하려는 것(동작엔 영향 없고 디버깅 편의).
                chunk = json.dumps({"text": text}, ensure_ascii=False)
                yield f"data: {chunk}\n\n"
        # 스트림 종료 신호. 없으면 클라이언트가 끝난 줄 모르고 계속 기다린다.
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",  # 중간 캐시가 스트림을 통째로 잡아두지 않게
            "X-Accel-Buffering": "no",  # nginx 버퍼링 방지 (배포 시 필요)
        },
    )
