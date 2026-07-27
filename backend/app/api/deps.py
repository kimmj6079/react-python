# FastAPI 라우터에서 공통으로 쓰는 의존성(dependency)을 모아두는 파일.
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.db.session import get_db

# DbSession이라는 타입 별칭을 만들어두면, 라우터 함수 파라미터에서
# `db: DbSession`이라고만 써도 FastAPI가 자동으로 get_db()를 호출해 세션을 주입해준다.
# (매번 `db: Session = Depends(get_db)`라고 반복해서 쓸 필요가 없어짐)
DbSession = Annotated[Session, Depends(get_db)]
