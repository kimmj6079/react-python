# 문서 업로드 · 인입 상태 조회 라우터. (M11)
#
# M3의 인입은 CLI였다 — 개발자가 터미널에서 돌린다. 사용자가 직접 문서를 올리게
# 하려면 (a) 업로드 엔드포인트 (b) 오래 걸리는 작업의 비동기 처리 (c) 상태 조회가
# 전부 필요하고, 셋 다 이 파일에 있다.
import logging

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from sqlalchemy import select

from app.api.deps import DbSession
from app.db.session import SessionLocal
from app.models.document import Document
from app.rag.documents import (
    ALLOWED_SUFFIXES,
    MAX_BYTES,
    parse,
    run_ingest,
    upsert_record,
)
from app.schemas.document import DocumentOut, UploadResult

logger = logging.getLogger(__name__)
router = APIRouter(tags=["documents"])


def _ingest_job(document_id: int, text: str) -> None:
    """백그라운드에서 도는 잡.

    ★ 요청의 DB 세션을 쓰면 안 된다 ★ FastAPI는 응답을 보낸 뒤 BackgroundTasks를
    실행하는데, 그 시점에 `get_db`의 의존성 세션은 이미 닫혀 있다. 닫힌 세션을 쓰면
    "요청 하나만 보내면 되는데 두 번째부터 죽는다" 같은 재현하기 어려운 실패가 난다.
    그래서 잡이 **자기 세션을 새로 연다.**
    """
    with SessionLocal() as db:
        run_ingest(db, document_id, text)


@router.post("/documents", status_code=202, response_model=UploadResult)
async def upload_document(
    db: DbSession,
    background: BackgroundTasks,
    file: UploadFile = File(...),
) -> UploadResult:
    """문서를 올리고 백그라운드 인입을 예약한다.

    ★ 202 Accepted를 돌려준다 ★ 200이 아니다. 인입은 아직 안 끝났고 수십 초 걸린다.
    200을 주면 클라이언트가 "끝났다"고 오해하고 곧바로 질문을 던졌다가
    "문서에 없다"는 답을 받는다 — 상태 폴링이 필요하다는 신호를 HTTP로 준다.
    """
    data = await file.read()

    # ★ 제한을 처음부터 건다 ★ 임의 파일을 받는 엔드포인트이고, 나중에 붙이면
    # 그 사이에 올라온 것들이 이미 문제가 된다.
    if len(data) > MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"파일이 너무 크다: {len(data)}바이트 (최대 {MAX_BYTES})",
        )
    if not data:
        raise HTTPException(status_code=400, detail="빈 파일이다")

    filename = file.filename or "unnamed"
    try:
        # ★ 파싱을 요청 안에서 한다 ★ 백그라운드로 미루지 않는 이유: 형식 오류나
        # 인코딩 실패는 **지금 당장 사용자에게 알려줄 수 있는** 실패다. 백그라운드로
        # 미루면 "업로드는 됐는데 나중에 failed"가 되어 피드백이 한 박자 늦는다.
        # 임베딩(수십 초)만 백그라운드로 보낸다.
        text = parse(filename, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not text.strip():
        # PDF에서 자주 난다 — 스캔 이미지 PDF는 추출되는 텍스트가 없다.
        # 여기서 안 막으면 청크 0개짜리 문서가 done이 되어 "올렸는데 검색이 안 된다"가 된다.
        raise HTTPException(
            status_code=400,
            detail="텍스트를 추출하지 못했다 (스캔 이미지 PDF면 OCR이 필요하다)",
        )

    doc, needs_ingest = upsert_record(db, filename, text)

    if needs_ingest:
        background.add_task(_ingest_job, doc.id, text)
        message = "인입을 시작했다. 상태는 GET /documents로 확인한다"
    else:
        # doc_hash가 같고 이미 done이면 임베딩을 통째로 건너뛴다.
        message = "같은 내용이 이미 인입돼 있어 건너뛴다"

    return UploadResult(document=DocumentOut.model_validate(doc), message=message)


@router.get("/documents", response_model=list[DocumentOut])
def list_documents(db: DbSession) -> list[Document]:
    return list(db.execute(select(Document).order_by(Document.id.desc())).scalars())


@router.get("/documents/{document_id}", response_model=DocumentOut)
def get_document(document_id: int, db: DbSession) -> Document:
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="없는 문서다")
    return doc


@router.get("/documents/meta/limits")
def limits() -> dict:
    """프론트가 업로드 전에 미리 걸러낼 수 있도록 제한을 알려준다.

    같은 숫자를 프론트에 하드코딩하면 서버가 제한을 바꿀 때 두 곳이 어긋난다 —
    VITE_API_URL을 client.ts 한 곳에만 둔 것과 같은 이유다.
    """
    return {"max_bytes": MAX_BYTES, "allowed_suffixes": sorted(ALLOWED_SUFFIXES)}
