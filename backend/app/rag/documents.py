# 업로드된 문서의 파싱 + 인입 오케스트레이션. (M11)
#
# M3의 인입은 "샘플 문서를 한 번 넣는 CLI"였다. 문서가 바뀌는 순간, 그리고 사용자가
# 직접 올리기 시작하는 순간 무너진다. 이 파일이 그 간극을 메운다:
#   파싱(형식마다 다름) → 해시로 스킵 판단 → 청킹/임베딩/업서트(ingest.py 재사용)
#   → 상태를 DB에 기록
import hashlib
import io
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.document import Document
from app.rag.factory import get_store
from app.rag.ingest import ingest_text, normalize_source

logger = logging.getLogger(__name__)

# ★ 임의 파일을 받는 엔드포인트다 — 제한을 처음부터 건다 ★
# 나중에 붙이면 그 사이에 올라온 것들이 이미 문제가 된다.
MAX_BYTES = 10 * 1024 * 1024
ALLOWED_SUFFIXES = {".md", ".txt", ".pdf"}


def parse(filename: str, data: bytes) -> str:
    """업로드된 바이트에서 텍스트를 뽑는다.

    ★ 실무 시간의 대부분이 여기 들어간다 ★ 파싱·인코딩·표 깨짐. 지금은 md/txt/pdf
    셋뿐이고 pdf도 pypdf의 기본 추출이라, **표와 다단 레이아웃은 깨진다.**
    그게 M7 청킹 품질에 그대로 들어온다는 것을 알고 감수한다 — 문서 형식이 늘면
    이 함수가 이 저장소에서 가장 지저분한 곳이 될 것이다.
    """
    suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix not in ALLOWED_SUFFIXES:
        raise ValueError(
            f"지원하지 않는 형식: {suffix or filename} (가능: {sorted(ALLOWED_SUFFIXES)})"
        )

    if suffix == ".pdf":
        from pypdf import PdfReader

        try:
            reader = PdfReader(io.BytesIO(data))
            # 페이지 사이를 빈 줄로 잇는다. 그래야 M7의 마크다운 분할기가 최소한
            # 페이지 경계를 문단 경계로 인식한다 — PDF에는 헤더 구조가 없으므로
            # 구조 인식 청킹의 이점이 크게 줄어든다는 것도 알고 간다.
            return "\n\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as exc:
            # ★ 테스트가 잡아낸 실제 버그 ★ pypdf는 PdfStreamError처럼 **ValueError가
            # 아닌** 자기 예외를 던진다(MRO: PdfStreamError -> PdfReadError ->
            # PyPdfError -> Exception). 그게 그대로 올라가면 라우터의
            # `except ValueError`를 지나쳐 **500 Internal Server Error**가 된다.
            # 사용자에게는 "서버가 터졌다"로 보이지만 실제로는 "파일이 깨졌다"이고,
            # 고칠 사람은 사용자다.
            #
            # 라이브러리 예외를 도메인 예외로 번역하는 것이 파싱 계층의 일이다 —
            # 안 하면 예외 타입이 상위로 새어나가 라우터가 pypdf를 알게 된다.
            # README가 "일부러 깨진 PDF를 업로드해 failed가 뜨는지 확인하라,
            # 성공 경로만 보고 넘어가면 이 항목의 절반을 놓친다"고 한 그 지점이다.
            raise ValueError(f"PDF를 읽을 수 없다 (파일이 손상됐을 수 있다): {exc}") from exc

    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        # ★ 한국어 문서에서 가장 흔한 실패 ★ Windows에서 만든 텍스트 파일은 cp949인
        # 경우가 많다. 조용히 replace로 뭉개면 깨진 글자가 그대로 임베딩되어
        # "검색은 되는데 답이 이상한" 상태가 된다 — 차라리 시끄럽게 실패한다.
        raise ValueError(
            "UTF-8로 읽을 수 없다 (cp949 파일이면 UTF-8로 저장해 다시 올린다)"
        ) from exc


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def run_ingest(db: Session, document_id: int, text: str) -> None:
    """실제 인입. FastAPI BackgroundTasks가 이 함수를 부른다.

    ★ BackgroundTasks의 한계를 알고 쓴다 ★ 프로세스가 죽으면 **잡이 그냥 사라진다.**
    문서는 `processing`에 남고 아무도 되살리지 않는다. 학습 범위에선 괜찮지만,
    이것이 실무가 Celery/ARQ/RQ 같은 외부 큐를 쓰는 이유다 —
    큐는 잡을 영속화하고, 죽으면 다른 워커가 집어간다.

    k8s에서 레플리카가 2개면 같은 문서를 둘이 동시에 처리할 수도 있다. 그래도
    **데이터가 망가지지는 않는다** — 업서트가 결정론적 id(uuid5)라 멱등이기 때문이다
    (M3-3c에서 넣은 성질이 여기서 값을 한다).
    """
    doc = db.get(Document, document_id)
    if doc is None:
        logger.warning("인입 대상 문서가 없다: id=%s", document_id)
        return

    doc.status = "processing"
    doc.error = None
    db.commit()

    try:
        store = get_store()
        inserted, deleted, _ = ingest_text(text, doc.source, store)
        doc.status = "done"
        doc.chunk_count = inserted
        doc.error = None
        logger.info("인입 완료: %s 청크 %d개 (기존 %d개 삭제)", doc.source, inserted, deleted)
    except Exception as exc:
        logger.exception("인입 실패: %s", doc.source)
        doc.status = "failed"
        doc.error = f"{type(exc).__name__}: {exc}"[:2000]
    db.commit()


def upsert_record(db: Session, filename: str, text: str) -> tuple[Document, bool]:
    """documents 행을 만들거나 갱신하고, "인입이 필요한가"를 함께 돌려준다.

    ★ doc_hash가 같으면 건너뛴다 ★ 문서 100개 중 하나만 바뀌었을 때 99개를 다시
    임베딩할 이유가 없다. 로컬 임베딩이라 돈은 안 들지만 문서당 30초씩 든다.
    (실무에서 임베딩 API를 쓰면 이건 곧바로 비용이다.)

    반환의 두 번째 값이 False면 호출자가 백그라운드 작업을 아예 띄우지 않는다.
    """
    source = normalize_source_for_upload(filename)
    digest = content_hash(text)

    doc = db.execute(select(Document).where(Document.source == source)).scalar_one_or_none()
    if doc is None:
        doc = Document(source=source, filename=filename, doc_hash=digest, status="pending")
        db.add(doc)
        db.commit()
        db.refresh(doc)
        return doc, True

    # ★ done이면서 해시가 같을 때만 건너뛴다 ★ 지난번이 failed였다면 같은 내용이라도
    # 다시 시도해야 한다 — "고쳤는데 왜 안 되지"의 흔한 원인이 이 조건 실수다.
    if doc.doc_hash == digest and doc.status == "done":
        return doc, False

    doc.filename = filename
    doc.doc_hash = digest
    doc.status = "pending"
    doc.error = None
    db.commit()
    db.refresh(doc)
    return doc, True


def normalize_source_for_upload(filename: str) -> str:
    """업로드 파일의 source 키.

    CLI의 normalize_source()는 저장소 루트 기준 상대경로를 만든다(파일이 디스크에
    있으므로). 업로드는 디스크 경로가 없으므로 `uploads/<파일명>`으로 고정한다.
    **두 경로가 겹치지 않게 접두어를 두는 것이 핵심이다** — 같은 이름의
    `CLAUDE.md`를 올렸을 때 저장소의 진짜 CLAUDE.md 청크를 지워버리면 안 된다.
    """
    safe = filename.replace("\\", "/").rsplit("/", 1)[-1]
    return f"uploads/{safe}"


__all__ = [
    "ALLOWED_SUFFIXES",
    "MAX_BYTES",
    "content_hash",
    "normalize_source",
    "normalize_source_for_upload",
    "parse",
    "run_ingest",
    "upsert_record",
]
