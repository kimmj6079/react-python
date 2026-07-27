# Kubernetes가 컨테이너 상태를 확인할 때 호출하는 헬스체크 엔드포인트들.
from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from app.api.deps import DbSession

router = APIRouter(tags=["health"])


@router.get("/health")
def liveness() -> dict[str, str]:
    """Liveness probe: the process is up and able to respond."""
    # DB 체크 없이 프로세스 응답 여부만 확인. 실패하면 k8s가 컨테이너를 재시작(restart)한다.
    return {"status": "ok"}


@router.get("/health/ready")
def readiness(db: DbSession) -> dict[str, str]:
    """Readiness probe: the process can actually reach the database."""
    # DB에 실제로 쿼리를 날려봐서 연결 가능한지 확인.
    # 실패하면 503을 반환하고, k8s는 이 파드로 트래픽을 보내지 않는다(재시작은 안 함).
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    return {"status": "ok"}
