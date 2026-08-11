# FastAPI 라우터에서 공통으로 쓰는 의존성(dependency)을 모아두는 파일.
from typing import Annotated

from anthropic import AsyncAnthropic
from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db

# DbSession이라는 타입 별칭을 만들어두면, 라우터 함수 파라미터에서
# `db: DbSession`이라고만 써도 FastAPI가 자동으로 get_db()를 호출해 세션을 주입해준다.
# (매번 `db: Session = Depends(get_db)`라고 반복해서 쓸 필요가 없어짐)
DbSession = Annotated[Session, Depends(get_db)]

# Anthropic 클라이언트는 내부에 HTTP 커넥션 풀을 들고 있어서, 요청마다 새로 만들면
# 매번 연결을 새로 여는 낭비가 생긴다. 모듈 레벨에 하나만 만들어 재사용한다.
# (config.py의 settings 싱글턴과 같은 발상)
_anthropic_client = AsyncAnthropic(api_key=settings.anthropic_api_key)


def get_anthropic_client() -> AsyncAnthropic:
    # 함수로 한 겹 감싸는 이유: pytest에서 app.dependency_overrides로
    # 이 함수를 가짜 클라이언트 반환 함수로 교체할 수 있게 하기 위함이다.
    # 라우터가 _anthropic_client를 직접 import하면 그 교체가 불가능해진다.
    return _anthropic_client


AnthropicClient = Annotated[AsyncAnthropic, Depends(get_anthropic_client)]
