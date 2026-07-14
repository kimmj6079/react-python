from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ItemCreate(BaseModel):
    name: str
    description: str | None = None


class ItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    created_at: datetime
