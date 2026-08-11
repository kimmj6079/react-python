# 챗봇 API가 주고받는 데이터 형태. schemas/item.py와 같은 역할이다.
from pydantic import BaseModel


class ChatRequest(BaseModel):
    # 사용자가 보낸 한 마디. M2에서 thread_id가 추가되면서 형태가 바뀐다.
    message: str
