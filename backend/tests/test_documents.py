# 문서 업로드/인입 테스트. (M11)
#
# ★ 파싱·해시·source 키 생성은 API도 임베딩도 안 쓴다 → CI에 넣는다 ★
# 실제 인입(임베딩 + 업서트)만 백그라운드로 빠지므로, 여기서는 그 앞까지를 검증한다.
# "무엇을 테스트할 수 있게 설계했는가"가 그대로 드러나는 파일이다.
import io

import pytest

from app.rag.documents import (
    content_hash,
    normalize_source_for_upload,
    parse,
    upsert_record,
)


def test_text_and_markdown_are_decoded_as_utf8():
    assert parse("a.md", "# 제목\n본문".encode()) == "# 제목\n본문"
    assert parse("a.txt", "본문".encode()) == "본문"


def test_cp949_file_fails_loudly():
    # ★ 한국어 문서에서 가장 흔한 실패 ★ Windows에서 만든 텍스트는 cp949인 경우가 많다.
    # errors="replace"로 뭉개면 깨진 글자가 그대로 임베딩되어 "검색은 되는데 답이
    # 이상한" 상태가 된다 — 조용한 손상보다 시끄러운 실패가 낫다.
    with pytest.raises(ValueError, match="UTF-8"):
        parse("a.txt", "한글".encode("cp949"))


@pytest.mark.parametrize("name", ["a.exe", "a.docx", "noextension"])
def test_unsupported_formats_are_rejected(name):
    # 임의 파일을 받는 엔드포인트라 화이트리스트를 처음부터 건다.
    with pytest.raises(ValueError, match="지원하지 않는"):
        parse(name, b"data")


def test_upload_source_is_namespaced_and_path_safe():
    # ★ uploads/ 접두어가 핵심이다 ★ 사용자가 CLAUDE.md를 올렸을 때 저장소의 진짜
    # CLAUDE.md 청크를 지워버리면 안 된다 — upsert_document는 source로 지우고 넣는다.
    assert normalize_source_for_upload("CLAUDE.md") == "uploads/CLAUDE.md"
    # 경로 조작 시도도 파일명만 남긴다.
    assert normalize_source_for_upload("../../etc/passwd") == "uploads/passwd"
    assert normalize_source_for_upload(r"C:\docs\a.md") == "uploads/a.md"


def test_content_hash_is_stable_and_content_sensitive():
    assert content_hash("같은 내용") == content_hash("같은 내용")
    assert content_hash("A") != content_hash("B")


def test_same_content_is_skipped_only_after_a_successful_ingest(db_session):
    # ★ 이 조건 실수가 "고쳤는데 왜 안 되지"의 흔한 원인이다 ★
    # done + 같은 해시일 때만 건너뛴다. 지난번이 failed였다면 같은 내용이라도 다시 해야 한다.
    doc, needs = upsert_record(db_session, "a.md", "본문")
    assert needs is True  # 처음이니 인입 필요

    doc.status = "done"
    db_session.commit()
    _, needs = upsert_record(db_session, "a.md", "본문")
    assert needs is False  # 같은 내용 + done -> 건너뛴다

    doc.status = "failed"
    db_session.commit()
    _, needs = upsert_record(db_session, "a.md", "본문")
    assert needs is True  # 같은 내용이지만 실패했었다 -> 다시 한다

    _, needs = upsert_record(db_session, "a.md", "바뀐 본문")
    assert needs is True  # 내용이 바뀌었다 -> 다시 한다


def test_reupload_updates_the_same_row(db_session):
    # source가 unique라 같은 파일명을 다시 올려도 행이 늘지 않는다.
    # 늘어나면 "이 문서의 상태"가 두 개가 되어 어느 쪽이 참인지 알 수 없다.
    first, _ = upsert_record(db_session, "a.md", "v1")
    second, _ = upsert_record(db_session, "a.md", "v2")
    assert first.id == second.id
    assert second.doc_hash == content_hash("v2")


def test_upload_rejects_empty_and_oversized(client):
    empty = client.post("/api/v1/documents", files={"file": ("a.md", b"", "text/markdown")})
    assert empty.status_code == 400

    big = client.post(
        "/api/v1/documents",
        files={"file": ("a.md", b"x" * (10 * 1024 * 1024 + 1), "text/markdown")},
    )
    assert big.status_code == 413


def test_upload_rejects_unextractable_pdf_instead_of_creating_an_empty_document(client):
    # ★ 스캔 이미지 PDF에서 실제로 나는 상황 ★ 추출되는 텍스트가 없으면 청크 0개짜리
    # 문서가 done이 되어 "올렸는데 검색이 안 된다"가 된다. 여기서 막는다.
    # (pypdf가 파싱조차 못 하면 400 - 어느 쪽이든 200이 아니면 된다)
    blank = client.post(
        "/api/v1/documents",
        files={"file": ("scan.pdf", b"%PDF-1.4\n%broken", "application/pdf")},
    )
    assert blank.status_code == 400


def test_limits_endpoint_tells_the_frontend_the_rules(client):
    # 같은 숫자를 프론트에 하드코딩하면 서버가 제한을 바꿀 때 두 곳이 어긋난다.
    body = client.get("/api/v1/documents/meta/limits").json()
    assert body["max_bytes"] == 10 * 1024 * 1024
    assert ".pdf" in body["allowed_suffixes"]


def test_pdf_text_is_extracted(tmp_path):
    # pypdf가 실제로 붙어 있는지 확인한다. 라이브러리를 넣고 import만 하고
    # 안 써보는 일이 흔하다.
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)

    # 빈 페이지라 텍스트는 없지만, 파싱 자체가 예외 없이 끝나야 한다.
    assert parse("a.pdf", buffer.getvalue()) == ""
