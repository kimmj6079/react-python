# items 리소스에 대한 HTTP 라우터. 실제 DB 작업은 app/crud/item.py에 위임하고
# 여기서는 요청을 받아 CRUD 함수를 호출한 뒤 응답 스키마(ItemRead)로 변환하는 역할만 한다.
from fastapi import APIRouter, HTTPException

from app.api.deps import DbSession
from app.crud import item as crud_item
from app.schemas.item import ItemCreate, ItemRead

# prefix="/items" + main.py에서 붙이는 "/api/v1" = 최종 경로는 "/api/v1/items"
router = APIRouter(prefix="/items", tags=["items"])


@router.get("", response_model=list[ItemRead])
def list_items(db: DbSession):
    # GET /api/v1/items : 전체 아이템 목록 조회
    return crud_item.get_items(db)


@router.post("", response_model=ItemRead, status_code=201)
def create_item(item_in: ItemCreate, db: DbSession):
    # POST /api/v1/items : item_in은 요청 바디를 ItemCreate 스키마로 자동 검증/파싱한 결과
    return crud_item.create_item(db, item_in)


@router.get("/{item_id}", response_model=ItemRead)
def get_item(item_id: int, db: DbSession):
    # GET /api/v1/items/{item_id} : 단건 조회. 없으면 404 반환
    item = crud_item.get_item(db, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="item not found")
    return item
