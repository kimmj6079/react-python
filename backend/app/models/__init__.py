# Import every model module here so Base.metadata is fully populated
# whenever `app.models` is imported (used by Alembic autogenerate).
from app.models.chunk import DocumentChunk  # noqa: F401

# ★ M11에서 추가 ★ CLAUDE.md의 "새 모델 추가 시 app/models/__init__.py에도 등록"이
# 바로 이 줄이다. 빼먹으면 Base.metadata에 안 잡혀서 alembic autogenerate가 테이블을
# 못 보고, "마이그레이션을 만들었는데 아무것도 안 생기는" 상태가 된다.
from app.models.document import Document  # noqa: F401
from app.models.item import Item  # noqa: F401
