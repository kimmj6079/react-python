# CRUD 계층: 실제 DB 쿼리(Create/Read/Update/Delete)를 모아두는 곳.
# 라우터(app/api/routes)는 HTTP 요청/응답만 다루고, DB 관련 로직은 여기에 위임한다.
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.item import Item
from app.schemas.item import ItemCreate


def get_items(db: Session) -> list[Item]:
    # SELECT * FROM items ORDER BY id 와 동일한 의미.
    return list(db.scalars(select(Item).order_by(Item.id)))


def get_item(db: Session, item_id: int) -> Item | None:
    # 기본키(primary key)로 단건 조회. 없으면 None을 반환한다.
    return db.get(Item, item_id)


def create_item(db: Session, item_in: ItemCreate) -> Item:
    item = Item(name=item_in.name, description=item_in.description)
    db.add(item)  # 세션에 추가(아직 DB에는 반영 안 됨)
    db.commit()  # 실제 INSERT 실행 및 트랜잭션 커밋
    db.refresh(item)  # DB가 채운 값(id, created_at 등)을 다시 읽어와 item 객체에 채워넣음
    return item
