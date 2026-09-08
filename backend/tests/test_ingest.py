# 청킹 유닛 테스트. (M7-1에서 chunk_text -> split_markdown으로 명세가 바뀌었다)
#
# ★ 테스트를 "고친" 게 아니라 명세가 바뀐 것이다 ★ 3-1의 chunk_text는 "N자마다
# 자르기"였고 그 테스트들은 겹침·꼬리 처리를 검증했다. M7-1의 split_markdown은
# 다른 일을 하므로(구조 인식 + 토큰 기반) 옛 테스트는 존재하지 않는 함수를 기술한다.
# 2b에서 test_full_history_is_forwarded를 test_client_history_is_ignored로 교체한 것과
# 같은 판단이다 — 전자는 대개 버그 은폐지만 이건 명세 교체다.
#
# ★ length_function을 주입해 임베딩 모델 없이 돈다 ★ 기본값(token_length)은 2.24GB
# 모델을 로딩하므로 CI에서 절대 부르면 안 된다. 여기서는 len(문자 수)을 넣어
# **분할 구조만** 검증한다 — 토큰 계산의 정확성은 이 테스트의 관심사가 아니다.
import pytest

from app.rag.chunking import heading_path_of, split_markdown

# 문자 수로 재면 e5 한도(508)를 훌쩍 넘는 값도 유효하므로, 테스트에서는
# "몇 글자"가 곧 max_tokens다. 읽는 사람이 헷갈리지 않게 이름을 붙여둔다.
CHARS = len

SAMPLE = """# 문서 제목

머리말이다.

## 아키텍처

요청은 브라우저에서 시작한다.

### 요청 흐름

브라우저 → Vite → FastAPI → Postgres 순서다.

## 배포

k8s와 docker-compose 두 경로가 있다.
"""


def test_sections_are_split_on_headers():
    chunks = split_markdown(SAMPLE, max_tokens=500, overlap_tokens=0, length_function=CHARS)

    # 헤더가 4개(h1 + h2 + h3 + h2)이므로 섹션도 4개다. 본문이 작아서 재분할은 없다.
    assert len(chunks) == 4
    assert [c.chunk_index for c in chunks] == [0, 1, 2, 3]


def test_heading_path_carries_the_full_ancestry():
    chunks = split_markdown(SAMPLE, max_tokens=500, overlap_tokens=0, length_function=CHARS)
    paths = [c.heading_path for c in chunks]

    # ★ 이 값이 M7-2의 재료다 ★ 청크만 떼어놓으면 무슨 문서의 어느 대목인지 모른다는
    # 문제(실패 ②)를 고치려면, 조상 헤딩 전체가 있어야 한다 — 직계 헤딩만으로는
    # "요청 흐름"이 무엇의 요청 흐름인지 알 수 없다.
    assert paths[0] == "문서 제목"
    assert paths[1] == "문서 제목 > 아키텍처"
    assert paths[2] == "문서 제목 > 아키텍처 > 요청 흐름"
    assert paths[3] == "문서 제목 > 배포"


def test_headings_stay_in_the_body_by_default():
    # strip_headers 기본값이 False다. True(라이브러리 기본)면 헤딩 텍스트가 본문에서
    # 사라져 '아키텍처'라는 단어를 잃은 채 임베딩된다 — 베이스라인보다 나빠질 수 있다.
    kept = split_markdown(SAMPLE, max_tokens=500, overlap_tokens=0, length_function=CHARS)
    assert any("## 아키텍처" in c.content for c in kept)

    stripped = split_markdown(
        SAMPLE, max_tokens=500, overlap_tokens=0, strip_headers=True, length_function=CHARS
    )
    assert all("## 아키텍처" not in c.content for c in stripped)
    # 지워져도 heading_path에는 남는다 — 그래서 M7-2에서 되살릴 수 있다.
    assert any(c.heading_path.endswith("아키텍처") for c in stripped)


def test_long_section_is_split_further_but_keeps_its_heading_path():
    long_doc = "# 제목\n\n## 긴 섹션\n\n" + ("가나다라마바사 " * 200)
    chunks = split_markdown(long_doc, max_tokens=120, overlap_tokens=20, length_function=CHARS)

    # 한 섹션이 여러 청크로 쪼개져도 모두 같은 heading_path를 갖는다.
    section = [c for c in chunks if c.heading_path == "제목 > 긴 섹션"]
    assert len(section) > 1
    assert all(c.token_count <= 120 for c in section)


def test_code_block_separator_has_priority_over_blank_line():
    # ★ 실패 ①(코드블록 중간을 자른다)을 막는 성질 ★
    # 마크다운 구분자 우선순위에서 '```\n'이 '\n\n'보다 앞에 있어서, 여유가 있으면
    # 코드블록을 통째로 유지하려 시도한다. 3-1의 "600자마다 무조건"에는 이 개념이 없었다.
    doc = "# 제목\n\n## 명령어\n\n설명 문장.\n\n```bash\nuv run pytest -q\nruff check .\n```\n"
    chunks = split_markdown(doc, max_tokens=500, overlap_tokens=0, length_function=CHARS)

    body = "\n".join(c.content for c in chunks)
    assert "```bash\nuv run pytest -q\nruff check .\n```" in body


def test_chunk_index_is_global_and_gapless():
    # 3-1에서 chunk_index를 i 대신 1로 오타 낸 사고가 있었다. 4중 검증이 전부
    # 통과하고 DB에만 잘못 들어갔던 종류라, 여기서 못 박는다.
    long_doc = "# 제목\n\n## A\n\n" + ("가 " * 300) + "\n\n## B\n\n" + ("나 " * 300)
    chunks = split_markdown(long_doc, max_tokens=100, overlap_tokens=10, length_function=CHARS)

    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_heading_path_of_ignores_missing_levels():
    # h2가 없고 h3만 있는 문서도 있다(들여쓰기를 건너뛴 마크다운). 그때 " > > "처럼
    # 빈 칸이 생기면 안 된다.
    assert heading_path_of({"h1": "A", "h3": "C"}) == "A > C"
    assert heading_path_of({}) == ""


def test_overlap_must_be_smaller_than_max_tokens():
    # 3-1의 chunk_text와 같은 가드. 없으면 분할기가 이상한 경계를 조용히 만든다.
    with pytest.raises(ValueError, match="작아야 한다"):
        split_markdown(SAMPLE, max_tokens=100, overlap_tokens=100, length_function=CHARS)


def test_max_tokens_cannot_exceed_the_embedding_limit():
    # ★ e5는 한도를 넘으면 에러가 아니라 조용히 자른다 ★ 그래서 우리가 시끄럽게 막는다.
    with pytest.raises(ValueError, match="한도"):
        split_markdown(SAMPLE, max_tokens=600, length_function=CHARS)


def test_tiny_pieces_are_merged_into_their_neighbour():
    # ★ 실측이 만든 테스트 ★ 코드펜스 경계에서 자르면 섹션의 첫 줄("## 제목")만
    # 떨어져 나오고, 닫는 펜스 "```" 하나가 청크가 되기도 한다. 실제 인입에서
    # 4~9토큰짜리 조각이 전체의 4.9%였다 — 검색되면 top-k 한 자리를 잡아먹으면서
    # 모델에게는 아무 근거도 주지 않는 순수 잡음이다.
    doc = "# 제목\n\n## 명령어\n\n```bash\nuv run pytest -q\n```\n\n실행하면 통과한다.\n"

    # ★ max_tokens 값을 실측으로 골랐다 ★ 처음엔 40으로 썼다가 테스트가 실패했는데
    # 버그가 아니었다 — 40에서는 합치면 한도를 넘어서 "안 합치는 것이 정답"이었다.
    # 반대로 100으로 키우면 분할 자체가 안 일어나 비교할 대상이 없어진다. 실제로
    # 재보니 45~50 구간에서만 "쪼개지고 + 합쳐진다"(scripts로 스윕해 확인).
    # 병합이 max_tokens 예산 안에서만 가능하다는 성질이 이 좁은 창으로 드러난다.
    without = split_markdown(
        doc, max_tokens=45, overlap_tokens=0, min_tokens=0, length_function=CHARS
    )
    with_merge = split_markdown(
        doc, max_tokens=45, overlap_tokens=0, min_tokens=20, length_function=CHARS
    )

    tiny_before = sum(1 for c in without if c.token_count < 20)
    tiny_after = sum(1 for c in with_merge if c.token_count < 20)

    assert tiny_before > 0  # 병합 전에는 작은 조각이 있다
    assert tiny_after < tiny_before  # 병합이 줄였다
    # ★ 0이 되기를 요구하지 않는다 ★ 합쳐서 한도를 넘는 조각은 작은 채로 남는 것이
    # 정답이다. "작은 조각을 전부 없애라"는 요구는 e5 한도를 깨라는 요구가 된다.


def test_merge_never_exceeds_max_tokens():
    # ★ 작은 조각을 없애려다 거대 청크를 만들면 본말전도다 ★
    # e5 한도에 가까운 청크는 뒷부분이 조용히 잘린다 — 병합이 그걸 만들면 안 된다.
    # 그래서 일부 조각은 작은 채로 남을 수 있고, 그게 맞다.
    doc = "# 제목\n\n## A\n\n" + ("가 " * 200)
    chunks = split_markdown(
        doc, max_tokens=100, overlap_tokens=10, min_tokens=90, length_function=CHARS
    )

    assert all(c.token_count <= 100 for c in chunks)


def test_merge_does_not_cross_section_boundaries():
    # ★ 섹션을 넘어가며 합치지 않는다 ★ heading_path가 달라지기 때문이다.
    # 합쳐버리면 "이 청크는 어느 절인가"가 거짓이 되고, M10 인용 카드가 틀린 곳을 가리킨다.
    doc = "# 제목\n\n## A\n\n짧다.\n\n## B\n\n이것도 짧다.\n"
    chunks = split_markdown(
        doc, max_tokens=500, overlap_tokens=0, min_tokens=200, length_function=CHARS
    )

    paths = [c.heading_path for c in chunks]
    assert "제목 > A" in paths
    assert "제목 > B" in paths
