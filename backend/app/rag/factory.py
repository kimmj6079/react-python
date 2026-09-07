# "어느 저장소를 쓸 것인가"를 정하는 단 한 곳. (M3-4)
#
# 3-3a에서는 이 파일을 일부러 안 만들었다 — 구현이 pgvector 하나뿐인데 팩토리를 두면
# 분기가 항상 같은 쪽으로만 가는 코드가 되고, 6개월 뒤 아무도 왜 있는지 모른다.
# 구현이 둘이 된 지금에야 만든다. **아직 없는 문제를 막는 코드는 만들지 않는다**는
# 이 저장소의 원칙(2c에서 노드 이름 필터를 미뤘던 것)이 여기서 한 바퀴 돈 셈이다.
#
# 이 파일이 생기면서 저장소를 아는 곳이 정확히 세 군데가 됐다:
#   pgvector_store.py (Postgres를 안다) / qdrant_store.py (Qdrant를 안다) / 여기 (둘을 안다)
# 나머지 전부 — graph.py, chat.py, ingest.py, retriever.py, deps.py — 는 계약만 본다.
from app.core.config import settings
from app.rag.base import VectorStore
from app.rag.pgvector_store import PgVectorStore
from app.rag.qdrant_store import QdrantStore

# 이름 -> 만드는 법. dict로 둔 이유는 if/elif 사슬보다 "지원 목록"이 한눈에 보이고,
# 아래 에러 메시지가 목록을 자동으로 따라오기 때문이다.
_BUILDERS = {
    "pgvector": PgVectorStore,
    "qdrant": QdrantStore,
}


def get_store(name: str | None = None) -> VectorStore:
    # name을 인자로도 받는 이유: 설정(환경변수)은 프로세스 하나에 하나뿐이라
    # "둘을 동시에 열어 비교하는" 3-4의 비교 스크립트를 쓸 수 없다.
    # 기본값은 설정에서, 필요하면 호출자가 명시 — CLI의 --store 플래그가 이 길로 온다.
    key = (name or settings.vector_store).strip().lower()
    builder = _BUILDERS.get(key)
    if builder is None:
        # ★ 조용히 pgvector로 폴백하지 않는다 ★ 오타("qdrnat")를 폴백으로 삼키면
        # "Qdrant로 바꿨는데 왜 결과가 그대로지?"를 몇 시간 헤매게 된다.
        # 설정 오타는 시끄럽게 죽는 편이 항상 싸다.
        raise ValueError(f"알 수 없는 vector_store: {key!r} - 가능한 값: {sorted(_BUILDERS)}")
    return builder()


def pop_store_arg(args: list[str]) -> str | None:
    """`--store <이름>` / `--store=<이름>`을 인자 목록에서 빼내어 돌려준다(없으면 None).

    ★ args를 제자리에서 수정한다 ★ 호출자가 남은 인자를 파일 경로로만 다루면 되게
    하기 위해서다. 부수효과가 있는 함수라 이름을 pop_으로 시작했다.

    argparse를 안 쓰는 이유: 이 저장소의 CLI들은 sys.argv를 손으로 읽는 스타일이고,
    플래그 하나 때문에 파서를 들이면 나머지(가변 개수 파일 경로) 처리까지 전부 다시
    써야 한다. 플래그가 셋쯤으로 늘면 그때 argparse로 바꾸는 게 맞다.
    """
    for i, arg in enumerate(args):
        if arg == "--store":
            args.pop(i)
            # 값이 빠진 채 끝나면 빈 문자열을 돌려준다 — get_store가 "가능한 값" 목록을
            # 담아 죽으므로, 여기서 별도 에러 메시지를 만들 필요가 없다.
            return args.pop(i) if i < len(args) else ""
        if arg.startswith("--store="):
            args.pop(i)
            return arg.split("=", 1)[1]
    return None
