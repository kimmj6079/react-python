from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from app.api.deps import DbSession

router = APIRouter(tags=["health"])


@router.get("/health")
def liveness() -> dict[str, str]:
    """Liveness probe: the process is up and able to respond."""
    return {"status": "ok"}


@router.get("/health/ready")
def readiness(db: DbSession) -> dict[str, str]:
    """Readiness probe: the process can actually reach the database."""
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    return {"status": "ok"}
