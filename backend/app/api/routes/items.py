from fastapi import APIRouter, HTTPException

from app.api.deps import DbSession
from app.crud import item as crud_item
from app.schemas.item import ItemCreate, ItemRead

router = APIRouter(prefix="/items", tags=["items"])


@router.get("", response_model=list[ItemRead])
def list_items(db: DbSession):
    return crud_item.get_items(db)


@router.post("", response_model=ItemRead, status_code=201)
def create_item(item_in: ItemCreate, db: DbSession):
    return crud_item.create_item(db, item_in)


@router.get("/{item_id}", response_model=ItemRead)
def get_item(item_id: int, db: DbSession):
    item = crud_item.get_item(db, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="item not found")
    return item
