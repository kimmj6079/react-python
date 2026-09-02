# chunk_text는 순수 함수(파일·DB·임베딩 모델 없음)라 CI에서 안전하게 돈다.
# ingest의 나머지 절반(임베딩·DB 저장)은 실제 리소스가 필요해 pytest 대상이 아니다 —
# 그쪽의 품질 검증은 M6 평가 하네스의 몫이다.
import pytest

from app.rag.ingest import chunk_text


def test_short_text_is_a_single_chunk():
    assert chunk_text("짧은 텍스트", chunk_size=100, overlap=20) == ["짧은 텍스트"]


def test_adjacent_chunks_share_the_overlap():
    # "0000000100020003..." — 전부 다른 내용 200자. 같은 글자 반복("aaa...")으로는
    # 겹침이 "어느 위치의 20자"인지 검증할 수 없어서 위치가 내용에 새겨진 텍스트를 쓴다.
    text = "".join(f"{i:04d}" for i in range(50))
    chunks = chunk_text(text, chunk_size=100, overlap=20)
    assert len(chunks) == 3  # step=80 → [0:100], [80:180], [160:200]
    assert chunks[0][-20:] == chunks[1][:20]
    assert chunks[1][-20:] == chunks[2][:20]


def test_tail_contained_in_previous_chunk_is_dropped():
    # 95자, step=80 → 두 번째 조각 [80:95)는 첫 청크 [0:95)에 통째로 들어 있다.
    # 가드가 없으면 같은 내용이 두 번 저장돼 검색 결과에 중복으로 나온다.
    chunks = chunk_text("x" * 95, chunk_size=100, overlap=20)
    assert chunks == ["x" * 95]


def test_overlap_must_be_smaller_than_chunk_size():
    # 가드가 없으면 음수 step의 range()가 에러 없이 빈 리스트가 되어
    # 문서가 조용히 사라진다 — "시끄럽게 죽는다"를 명세로 못 박는다.
    with pytest.raises(ValueError):
        chunk_text("아무 텍스트", chunk_size=100, overlap=100)
