# 저장소 구현과 팩토리가 계약을 지키는지 확인한다.
#
# ★ 진짜 DB도 Qdrant도 두드리지 않는다 ★ 여기서 재는 것은 "모양"과 "고르는 규칙"뿐이고,
# 검색 품질은 M6 평가 하네스의 몫이다. 이 저장소의 규칙(chatbot/README.md의 CI 경고)대로
# pytest는 실제 DB·임베딩·LLM·벡터DB를 부르지 않는다.
#
# 실측(3-3b): QdrantClient의 "생성자는 연결하지 않는다" — 서버를 내린 채로 만들어도
# 0.08초에 성공한다. 그래서 아래 테스트들이 Qdrant 없이도 돈다. 만약 생성자가 연결했다면
# get_store("qdrant")를 부르는 순간 CI가 죽었을 것이다.
import pytest

from app.rag.base import VectorStore
from app.rag.factory import get_store, pop_store_arg
from app.rag.pgvector_store import PgVectorStore
from app.rag.qdrant_store import QdrantStore


@pytest.mark.parametrize("store_class", [PgVectorStore, QdrantStore])
def test_stores_satisfy_the_protocol(store_class):
    # @runtime_checkable Protocol의 issubclass는 "메서드 이름이 다 있는가"만 본다.
    # 인자 이름·타입·개수는 안 본다 — 그건 정적 타입 체커의 몫인데 이 저장소엔
    # mypy가 없다(pyproject의 dev 그룹은 pytest·httpx·ruff뿐).
    #
    # 그래도 값이 있다: QdrantStore를 쓰면서 search를 serach로 오타 내거나
    # upsert_document를 upsert로 줄여 지으면 여기서 걸린다. 그런 실수는 실행해봐야
    # AttributeError로 터지는데, 하필 실행 경로가 "인입 CLI"라 API 테스트로는 안 잡힌다.
    #
    # parametrize로 둔 이유: 구현이 셋이 되면 목록에 한 줄만 추가하면 된다.
    assert issubclass(store_class, VectorStore)


def test_get_store_returns_the_named_implementation():
    assert isinstance(get_store("pgvector"), PgVectorStore)
    assert isinstance(get_store("qdrant"), QdrantStore)
    # 대소문자·공백에 관대하게 — 환경변수는 사람이 손으로 넣는 값이다.
    assert isinstance(get_store(" PgVector "), PgVectorStore)


def test_get_store_rejects_unknown_names_loudly():
    # ★ 이 테스트가 지키는 것은 "폴백하지 않는다"이다 ★
    # 오타("qdrnat")를 조용히 pgvector로 폴백하면 "Qdrant로 바꿨는데 왜 결과가
    # 그대로지?"를 몇 시간 헤매게 된다. 설정 오타는 시끄럽게 죽는 편이 항상 싸다.
    with pytest.raises(ValueError, match="qdrnat"):
        get_store("qdrnat")


@pytest.mark.parametrize(
    ("argv", "expected_name", "expected_rest"),
    [
        (["--store", "qdrant", "a.md"], "qdrant", ["a.md"]),
        (["--store=qdrant", "a.md"], "qdrant", ["a.md"]),
        (["a.md", "--store", "pgvector", "b.md"], "pgvector", ["a.md", "b.md"]),
        (["a.md", "b.md"], None, ["a.md", "b.md"]),
        # 값 없이 끝나면 빈 문자열 — get_store가 "가능한 값" 목록을 담아 죽는다.
        (["--store"], "", []),
    ],
)
def test_pop_store_arg(argv, expected_name, expected_rest):
    # 순수 함수라 pytest에 딱 맞는 대상이다(M6의 metrics.py와 같은 성질).
    # ★ 남은 인자까지 확인하는 게 핵심이다 ★ 이름만 검사하면 "--store"가 args에
    # 그대로 남아 파일 경로로 취급되는 버그("파일이 없다: --store")를 못 잡는다.
    assert pop_store_arg(argv) == expected_name
    assert argv == expected_rest
