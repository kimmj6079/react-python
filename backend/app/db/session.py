# DB 연결(엔진)과, 요청마다 하나씩 만들어 쓰는 세션(Session)을 정의하는 파일.
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

# engine: DB와의 실제 커넥션 풀을 관리하는 객체. 앱 실행 중 한 번만 생성한다.
engine = create_engine(settings.database_url)
# SessionLocal: 이 팩토리를 호출할 때마다(SessionLocal()) 새 세션(작업 단위)이 만들어진다.
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    # FastAPI의 Depends(get_db)로 쓰이는 "의존성 함수".
    # yield 이전은 요청 시작 시, yield 이후(finally)는 요청이 끝난 뒤 실행된다.
    # 즉 요청마다 세션을 새로 열고, 응답 후 반드시 닫아 커넥션이 새지 않게 한다.
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
