from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

engine = create_engine(
    settings.database_url,
    # 1. 풀에서 사용 가능한 커넥션을 기다리는 시간(초) (기본값: 30)
    pool_timeout=30,
    
    # 2. 풀의 커넥션을 재사용하기 전에 연결 상태를 자동으로 확인
    pool_pre_ping=True,
    
    # 3. 일정 시간(초) 동안 idle 상태였던 커넥션을 자동으로 재연결 (DB 서버의 timeout 방지)
    pool_recycle=1800,
    
    # 4. DB 드라이버 레벨 타임아웃 (connect_args)
    connect_args={
        # PostgreSQL (psycopg2) 예시:
        "connect_timeout": 10,       # DB 연결 시도 타임아웃 (초)
        "options": "-c statement_timeout=5000"  # 쿼리 실행 타임아웃 (밀리초 단위, 5000ms = 5s)
        
        # MySQL (pymysql) 사용 시 예시:
        # "connect_timeout": 10,
        # "read_timeout": 10,
        # "write_timeout": 10,
    }
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
