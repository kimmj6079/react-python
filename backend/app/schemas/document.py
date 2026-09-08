# 문서 인입 API의 응답 모양. (M11)
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DocumentOut(BaseModel):
    # from_attributes: SQLAlchemy ORM 객체를 그대로 검증/직렬화할 수 있게 한다.
    # 이게 없으면 라우터마다 dict로 손수 옮겨 담아야 하고, 필드가 늘 때마다 빠뜨린다.
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    filename: str
    status: str
    # ★ 에러를 응답에 포함한다 ★ 실패를 조용히 삼키면 "업로드는 됐는데 검색은 안 되는"
    # 최악의 상태가 된다. 사용자가 화면에서 이유를 볼 수 있어야 고칠 수 있다.
    error: str | None
    chunk_count: int
    updated_at: datetime


class UploadResult(BaseModel):
    document: DocumentOut
    # "인입을 시작했다" vs "같은 내용이라 건너뛴다"를 구분해 알려준다.
    # 둘 다 202지만 사용자가 기다려야 하는지가 다르다.
    message: str
