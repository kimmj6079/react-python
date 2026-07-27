# 모든 SQLAlchemy 모델(테이블)이 상속받는 공통 베이스 클래스.
# 이 Base를 상속한 모델들의 메타데이터(테이블 정보)가 Base.metadata에 모이고,
# Alembic이 마이그레이션을 자동 생성할 때 이 metadata를 기준으로 DB와 모델의 차이를 비교한다.
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
