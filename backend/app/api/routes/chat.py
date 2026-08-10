# Kubernetes가 컨테이너 상태를 확인할 때 호출하는 헬스체크 엔드포인트들.
from fastapi import APIRouter

router = APIRouter(tags=["chat"])

@router.get("/chat/health")
def chat_health() -> dict[str, str] :
    """
    채팅 서버 상태 확인
    """
    return {"status": "ok"}