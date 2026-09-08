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

from app.rag.access import Principal
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


def test_empty_chunk_list_is_a_valid_delete(monkeypatch):
    """★ M11에서 발견한 엣지 케이스 ★

    "이 문서를 통째로 지운다"는 청크 0개로 업서트하는 것과 같다. 정당한 연산인데
    Qdrant는 points가 빈 upsert를 400 "Empty update request"로 거부한다.
    pgvector는 add_all([])이 그냥 통과해서 이 차이가 안 보였다 —
    **구현이 둘일 때만 드러나는 종류의 어긋남**이고, 계약을 지키려면 구현이 흡수해야 한다.

    실제 Qdrant를 안 띄우고 클라이언트만 대역으로 바꿔, "upsert를 아예 안 부르는지"를 본다.
    """
    calls = {"upsert": 0, "delete": 0}

    class FakeClient:
        def collection_exists(self, name):
            return True

        def count(self, name, count_filter=None):
            return type("R", (), {"count": 3})()

        def delete(self, **kwargs):
            calls["delete"] += 1

        def upsert(self, **kwargs):
            calls["upsert"] += 1

    store = QdrantStore.__new__(QdrantStore)
    store._client = FakeClient()
    store._collection = "test"
    store._collection_ready = True

    deleted = store.upsert_document("a.md", [], [], [])

    assert deleted == 3  # 지운 개수는 그대로 돌려준다
    assert calls["delete"] == 1  # 삭제는 한다
    assert calls["upsert"] == 0  # ★ 빈 upsert는 아예 안 부른다 ★


# ─────────────────── M12: 권한 필터 ───────────────────


def test_principal_always_includes_the_public_role():
    """공개 청크(allowed_roles=["*"])는 역할과 무관하게 보여야 한다.

    이 처리를 각 저장소가 따로 하게 두면 한쪽만 빠뜨린다 — 그래서 Principal이
    한 번에 책임진다. 빠뜨린 쪽은 "공개 문서가 안 보인다"로 드러나는데,
    권한 버그 중에서는 그나마 눈에 띄는 편이다(반대 방향이 훨씬 위험하다).
    """
    assert Principal().role_filter_values == ["*"]
    assert Principal(roles=frozenset({"hr"})).role_filter_values == ["*", "hr"]


def test_principal_is_immutable():
    # 요청 처리 도중 권한이 넓어지는 사고를 문법으로 막는다.
    p = Principal(tenant_id="a", roles=frozenset({"hr"}))
    with pytest.raises(Exception):
        p.tenant_id = "b"  # type: ignore[misc]


def test_qdrant_filter_pins_tenant_with_AND():
    """★ 이 테스트가 지키는 것이 유출 방지의 전부다 ★

    must는 AND다 — 역할이 아무리 많아도 테넌트가 다르면 못 본다. 이걸 should(OR)로
    잘못 쓰면 "역할만 맞으면 남의 테넌트도 보이는" 상태가 되는데, **검색 결과가
    늘어날 뿐 에러는 안 나서** 아무도 눈치채지 못한다.
    """
    flt = QdrantStore._access_filter(Principal(tenant_id="acme", roles=frozenset({"hr"})))

    conditions = {c.key: c for c in flt.must}
    assert set(conditions) == {"tenant_id", "allowed_roles"}
    assert conditions["tenant_id"].match.value == "acme"
    assert set(conditions["allowed_roles"].match.any) == {"*", "hr"}
    # should(OR)가 아니라 must(AND)여야 한다.
    assert not flt.should


def test_search_requires_a_principal():
    """★ M12의 설계 원칙을 못 박는 테스트 ★

    principal에 기본값을 주면 언젠가 누가 안 넘기고, 그 호출만 조용히 전체 문서를
    본다. 필수 인자면 그 실수가 TypeError로 즉시 걸린다 —
    "런타임에 조용히 넓어지는 권한"보다 "호출 시점의 시끄러운 실패"가 낫다.
    """
    import inspect

    for store_class in (PgVectorStore, QdrantStore):
        sig = inspect.signature(store_class.search)
        assert "principal" in sig.parameters, f"{store_class.__name__}.search에 principal이 없다"
        assert sig.parameters["principal"].default is inspect.Parameter.empty, (
            f"{store_class.__name__}.search의 principal에 기본값이 있다 — 빼먹을 수 있게 된다"
        )
