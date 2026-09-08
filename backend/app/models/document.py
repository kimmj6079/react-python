# 인입된 문서 하나의 "상태" 행. (M11)
#
# ★ document_chunks와 역할이 다르다 ★
#   document_chunks : 검색용 색인. 원본에서 파생됐고 언제든 지우고 다시 만들 수 있다
#   documents(여기) : 인입 작업의 **상태 기록**. "이 문서가 지금 어디까지 처리됐나"
#
# ★ 왜 상태를 메모리가 아니라 DB에 두는가 ★
# 인입은 수 분 걸릴 수 있어 요청-응답 안에서 처리하면 타임아웃이 난다. 그래서
# 백그라운드로 돌리는데, 그러면 "지금 어떻게 됐나"를 물어볼 곳이 필요하다.
# 메모리에 두면 (a) 프로세스가 죽으면 사라지고 (b) k8s에서 레플리카가 2개면 **어느
# 파드가 처리 중인지 아무도 모른다.** DB에 두면 어느 파드가 물어도 같은 답이 나온다.
# 이게 결국 실무가 Celery/ARQ 같은 외부 큐로 가는 이유의 첫 단계다.
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# 상태 전이: pending -> processing -> done | failed
# 문자열 Enum을 DB 타입으로 안 쓴 이유: Postgres ENUM은 값을 추가할 때 마이그레이션이
# 필요하다. 상태가 하나 늘 때마다 스키마 변경을 하느니 문자열 + 앱 검증이 낫다
# (values를 여기 상수로 모아두면 오타는 잡힌다).
STATUSES = ("pending", "processing", "done", "failed")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)

    # ★ document_chunks.source와 같은 값이다 ★ 이 두 테이블을 잇는 유일한 키이고,
    # 그래서 재인입할 때 "이 문서의 청크"를 정확히 지울 수 있다.
    # unique=True: 같은 문서가 두 행이 되면 상태가 어느 쪽인지 알 수 없다.
    source: Mapped[str] = mapped_column(String(500), unique=True, nullable=False)

    # 사용자가 올린 원래 파일명. source는 정규화되므로 표시용으로 따로 둔다.
    filename: Mapped[str] = mapped_column(String(500), nullable=False)

    # ★ 내용의 해시 ★ 같은 내용을 다시 올리면 임베딩을 통째로 건너뛴다.
    # 문서 100개짜리 저장소에서 하나만 바뀌었을 때 99개를 다시 임베딩할 이유가 없다 —
    # 로컬 임베딩이라 돈은 안 들지만 시간은 든다(문서당 30초).
    doc_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")

    # ★ 실패 이유를 반드시 남긴다 ★ 인입 실패를 조용히 삼키면 "업로드는 됐는데 검색은
    # 안 되는" 최악의 상태가 된다. 사용자는 올렸다고 믿고, 답이 안 나오면 챗봇을 탓한다.
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
