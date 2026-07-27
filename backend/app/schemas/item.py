# Pydantic 스키마: API로 주고받는 데이터의 형태(요청/응답 바디)를 정의한다.
# models/item.py의 SQLAlchemy 모델(DB 테이블)과는 별개 개념이다.
# 요청용(Create)과 응답용(Read)을 분리해두면, 예를 들어 id나 created_at처럼
# "클라이언트가 보낼 필요 없고 서버가 채워주는 값"을 요청 스키마에서 자연스럽게 뺄 수 있다.
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ItemCreate(BaseModel):
    # 클라이언트가 아이템 생성 요청 시 보내는 형태 (id, created_at은 서버가 채운다).
    name: str
    description: str | None = None


class ItemRead(BaseModel):
    # from_attributes=True: dict가 아니라 SQLAlchemy 모델 객체(Item 인스턴스)를 넣어도
    # 속성(attribute)을 읽어서 그대로 이 스키마로 변환할 수 있게 해준다.
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    created_at: datetime
