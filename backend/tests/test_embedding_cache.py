# 임베딩 캐시 테스트. (M13-c)
#
# ★ 임베딩 모델을 부르지 않는다 ★ 캐시는 "텍스트 → 벡터"를 보관할 뿐이라 진짜 벡터가
# 필요 없다. 모델을 띄우면 테스트 하나에 1GB 로딩 + 13초(13-b 실측)가 붙는다.
# 아래 embed_passages 테스트도 모델을 가짜로 갈아끼워, **캐시가 모델을 몇 번 부르는지**만 본다.
import pytest

from app.core.config import settings
from app.rag import embedding
from app.rag.base import EMBEDDING_DIM
from app.rag.embedding_cache import EmbeddingCache

MODEL = "test-model"


@pytest.fixture
def cache(tmp_path):
    # tmp_path를 쓴다 = 테스트마다 새 파일. 실제 캐시(.cache/embeddings.sqlite3)를
    # 건드리면 개발자의 로컬 상태에 따라 결과가 달라진다 — conftest의 _langfuse_off와
    # 같은 원칙이다(테스트는 자기가 만든 상태에만 의존한다).
    return EmbeddingCache(tmp_path / "embeddings.sqlite3")


def test_roundtrip(cache):
    cache.put_many(MODEL, [("안녕", [0.5, -0.25, 0.125])])

    assert cache.get_many(MODEL, ["안녕"]) == {"안녕": [0.5, -0.25, 0.125]}


def test_miss_returns_no_key(cache):
    # None이 아니라 "키가 없다"로 표현한다. None을 값으로 쓰면 "캐시에 None이 저장된
    # 경우"와 구분되지 않는다.
    assert cache.get_many(MODEL, ["없는 것"]) == {}


def test_float32_roundtrip_is_lossy_but_stable(cache):
    """★ float32로 저장하므로 값이 정확히 같지 않을 수 있다 ★

    임베딩 원본이 float32라(fastembed의 numpy 배열) 실제 손실은 없지만, 파이썬
    float(=C double) 리터럴을 넣으면 근사된다. 그 사실을 테스트로 드러내 둔다 —
    나중에 "왜 캐시된 벡터가 원본과 != 인가"를 디버깅하지 않도록.
    """
    cache.put_many(MODEL, [("x", [0.1, 0.2, 0.3])])

    got = cache.get_many(MODEL, ["x"])["x"]

    assert got != [0.1, 0.2, 0.3]  # 비트가 다르다
    assert all(abs(a - b) < 1e-6 for a, b in zip(got, [0.1, 0.2, 0.3], strict=True))


def test_model_name_is_part_of_the_key(cache):
    """★ 이 테스트가 막는 것은 "조용한 검색 품질 붕괴"다 ★

    임베딩 모델을 바꾸면 옛 벡터는 **다른 의미 공간**의 것이라 쓰면 안 된다. 키에 모델이
    없으면 캐시가 그걸 되살려주고, 에러 없이 순위만 무작위에 가까워진다.
    embedding.py 머리 주석이 경고하는 실패를 캐시가 재현하지 않도록 못 박는다.
    """
    cache.put_many("model-a", [("공유 텍스트", [1.0, 2.0])])

    assert cache.get_many("model-b", ["공유 텍스트"]) == {}
    assert cache.get_many("model-a", ["공유 텍스트"]) != {}


def test_put_overwrites(cache):
    cache.put_many(MODEL, [("x", [1.0])])
    cache.put_many(MODEL, [("x", [2.0])])

    assert cache.get_many(MODEL, ["x"]) == {"x": [2.0]}
    assert cache.count(MODEL) == 1


def test_large_batch_does_not_hit_the_sql_variable_limit(cache):
    # sqlite 기본 변수 상한은 999다. IN 절을 안 쪼갰다면 여기서
    # "too many SQL variables"로 죽는다 — 문서 하나가 커지는 날 인입 전체가 실패한다.
    texts = [f"chunk-{i}" for i in range(1200)]
    cache.put_many(MODEL, [(t, [float(i)]) for i, t in enumerate(texts)])

    found = cache.get_many(MODEL, texts)

    assert len(found) == 1200


def test_empty_inputs_are_safe(cache):
    assert cache.get_many(MODEL, []) == {}
    cache.put_many(MODEL, [])  # 예외가 안 나야 한다


# ---------------------------------------------------------------------------
# embed_passages가 실제로 캐시를 쓰는가
# ---------------------------------------------------------------------------
class FakeModel:
    """passage_embed만 흉내내는 대역. 몇 번 · 무엇으로 불렸는지 기록한다."""

    def __init__(self):
        self.calls: list[list[str]] = []

    def passage_embed(self, texts):
        self.calls.append(list(texts))
        # _check_dim을 통과해야 하므로 계약 차원을 맞춘다.
        for i, _ in enumerate(texts):
            yield _FakeVector([float(i)] * EMBEDDING_DIM)


class _FakeVector:
    def __init__(self, values):
        self._values = values

    def tolist(self):
        return self._values


@pytest.fixture
def fake_embedding(tmp_path, monkeypatch):
    fake = FakeModel()
    monkeypatch.setattr(embedding, "get_model", lambda: fake)
    monkeypatch.setattr(settings, "embedding_cache_enabled", True, raising=False)
    monkeypatch.setattr(
        settings, "embedding_cache_path", str(tmp_path / "cache.sqlite3"), raising=False
    )
    # 모듈 전역 싱글턴을 비운다 — 안 지우면 앞 테스트가 만든 캐시가 살아남아
    # "단독 실행은 통과, 전체 실행은 실패"가 된다(tracing._client와 같은 이유).
    from app.rag import embedding_cache

    monkeypatch.setattr(embedding_cache, "_cache", None)
    yield fake
    embedding_cache._cache = None


def test_second_call_does_not_touch_the_model(fake_embedding):
    """★ 이 마일스톤의 본론 ★ 같은 텍스트를 두 번 임베딩하지 않는다."""
    first = embedding.embed_passages(["a", "b"])
    second = embedding.embed_passages(["a", "b"])

    assert first == second
    assert len(fake_embedding.calls) == 1  # 두 번째 호출은 모델을 안 불렀다


def test_only_the_changed_chunk_is_recomputed(fake_embedding):
    """★ 실제로 아끼는 상황이 이것이다 ★

    문서를 한 줄 고치면 청크 하나만 바뀌고 나머지는 글자 하나 안 바뀐다.
    M11의 doc_hash 스킵은 **문서 전체가 같을 때만** 걸리므로 이 경우 통째로 다시 돈다.
    """
    embedding.embed_passages(["a", "b", "c"])
    embedding.embed_passages(["a", "b-수정됨", "c"])

    assert fake_embedding.calls[0] == ["a", "b", "c"]
    assert fake_embedding.calls[1] == ["b-수정됨"]  # 바뀐 하나만


def test_order_is_preserved_across_cache_hits_and_misses(fake_embedding):
    # 캐시 히트와 미스가 섞이면 결과를 재조립해야 한다. 여기서 순서가 어긋나면
    # **청크와 벡터의 짝이 뒤바뀐다** — 에러 없이 검색이 엉뚱한 문서를 가리킨다.
    embedding.embed_passages(["b"])  # b만 캐시에 넣어둔다
    fake_embedding.calls.clear()

    result = embedding.embed_passages(["a", "b", "c"])

    assert fake_embedding.calls == [["a", "c"]]
    # 대역은 "입력 안에서의 인덱스"를 값으로 준다. 캐시된 b는 단독 호출 때 만들어져
    # 0.0이고, 이번에 계산된 a·c는 각각 0.0·1.0이다. 그 배치가 그대로 유지돼야 한다.
    assert [v[0] for v in result] == [0.0, 0.0, 1.0]


def test_duplicates_are_embedded_once(fake_embedding):
    result = embedding.embed_passages(["같은 것", "다른 것", "같은 것"])

    assert fake_embedding.calls == [["같은 것", "다른 것"]]
    assert result[0] == result[2]


def test_cache_can_be_turned_off(fake_embedding, monkeypatch):
    # 캐시 버그는 "틀린 벡터를 빠르게 돌려주는" 모양이라 검색 품질만 조용히 무너진다.
    # 껐다 켜서 비교하는 것이 유일한 진단법이라, 스위치가 실제로 동작해야 한다.
    monkeypatch.setattr(settings, "embedding_cache_enabled", False, raising=False)

    embedding.embed_passages(["a"])
    embedding.embed_passages(["a"])

    assert len(fake_embedding.calls) == 2
