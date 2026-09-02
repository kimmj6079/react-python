# Import every model module here so Base.metadata is fully populated
# whenever `app.models` is imported (used by Alembic autogenerate).
from app.models.chunk import DocumentChunk  # noqa: F401
from app.models.item import Item  # noqa: F401
