from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.item import Item
from app.schemas.item import ItemCreate


def get_items(db: Session) -> list[Item]:
    return list(db.scalars(select(Item).order_by(Item.id)))


def get_item(db: Session, item_id: int) -> Item | None:
    return db.get(Item, item_id)


def create_item(db: Session, item_in: ItemCreate) -> Item:
    item = Item(name=item_in.name, description=item_in.description)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item
