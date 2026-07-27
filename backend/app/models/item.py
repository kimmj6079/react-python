# SQLAlchemy ORM 모델. 이 클래스 하나가 DB의 "items" 테이블 하나와 매핑된다.
# 필드 하나 = 컬럼 하나. 실제 테이블 생성/변경은 이 모델이 아니라 Alembic 마이그레이션이 담당한다.
from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Item(Base):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # server_default=func.now(): 값을 안 주면 DB(Postgres)가 현재 시각을 자동으로 채운다.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
