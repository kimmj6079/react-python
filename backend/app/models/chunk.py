# 문서 조각(청크) 하나 = 이 테이블의 한 행. RAG의 저장소다.
#
# items 테이블과 목적이 다르다: items는 사용자가 만드는 업무 데이터고,
# 여기는 문서에서 파생된 "검색용 색인"이다. 원본이 따로 있으므로
# 언제든 지우고 다시 만들 수 있다 — 그 성질이 M11(재인입)에서 중요해진다.
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# ★ 임베딩 차원. 모델이 정하는 값이라 여기 상수로 못 박는다 ★
# intfloat/multilingual-e5-large = 1024차원(실측).
# 모델을 바꾸면 이 숫자가 바뀌고, 그러면 컬럼 타입이 바뀌므로
# 마이그레이션 + 전체 재인입이 필요하다. "설정 한 줄"이 아니다.
EMBEDDING_DIM = 1024


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(primary_key=True)

    # 어느 문서에서 왔나. 두 가지 역할을 한다:
    #   1) 답변에 출처를 표시할 때 (M10)
    #   2) 재인입할 때 "이 문서의 청크만 지우고 다시 넣기"의 키 (M11)
    source: Mapped[str] = mapped_column(String(500), nullable=False)

    # 문서 안에서 몇 번째 조각인가. 없어도 검색은 되지만 디버깅이 지옥이 된다 —
    # "3번째 조각이 이상하다"를 말할 수 없으면 청킹 전략을 고칠 수가 없다(M7).
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)

    # ★ 원문을 반드시 같이 저장한다 ★
    # 벡터는 비가역이다 — 1024개 숫자에서 원래 문장을 복원할 수 없다.
    # 원문이 없으면 검색에 성공해도 모델에게 붙여줄 게 없다.
    # "벡터 DB에 문서를 넣는다"는 표현 때문에 벡터만 저장하면 될 것 같지만 아니다.
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # 임베딩 벡터. Postgres에는 vector(1024) 타입으로 저장된다.
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
