# 문서 인입(ingest): 파일을 읽어 → 청킹 → 임베딩 → document_chunks에 저장한다.
#
# 실행 (backend/에서):
#   uv run python -m app.rag.ingest ../CLAUDE.md ../SETUP.md ../DEPLOYMENT.md
#
# 같은 문서를 다시 넣으면 옛 청크를 지우고 새로 넣는다(멱등) — ingest_file() 참고.
# 청킹은 "고정 길이 + 오버랩" 베이스라인이다. M7에서 구조 인식·토큰 기반으로
# 교체하며 chunking.py로 분리할 예정이라, 지금은 일부러 단순하게 둔다.

import sys
import time
from pathlib import Path

from app.core.config import settings
from app.rag.base import VectorStore
from app.rag.embedding import embed_passages
from app.rag.factory import get_store, pop_store_arg

# 청크 크기(문자 수). e5-large의 입력 한도는 512 "토큰"이라, 문자 기준인 지금은
# 한도를 넘는 청크의 뒷부분이 조용히 잘린 채 임베딩될 수 있다(에러 없음).
# 알고 감수하는 베이스라인이다 — 토큰 기준 분할은 M7에서.
CHUNK_SIZE = 600
# 인접 청크가 공유하는 길이. 경계에서 문장이 반토막 나면 그 문장은 어느 쪽
# 청크로도 검색되지 않는데, 겹침이 있으면 최소 한쪽에는 온전하게 남는다.
CHUNK_OVERLAP = 100

# source 키의 기준점: …/backend/app/rag/ingest.py에서 세 단계 위 = 저장소 루트
REPO_ROOT = Path(__file__).resolve().parents[3]


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    # 순수 함수로 둔다: 파일도 DB도 모델도 안 만진다 → pytest로 그냥 테스트된다.
    if overlap >= chunk_size:
        # 이 가드가 없으면 step이 0(range가 ValueError) 또는 음수가 되는데,
        # 음수면 range()가 에러 없이 "빈 범위"가 되어 문서가 조용히 통째로 사라진다.
        raise ValueError(f"overlap({overlap})은 chunk_size({chunk_size})보다 작아야 한다")
    step = chunk_size - overlap
    chunks: list[str] = []
    for start in range(0, len(text), step):
        # 마지막 꼬리 처리: 직전 청크가 덮는 범위의 끝이 start + overlap 이므로,
        # 텍스트가 그 앞에서 끝나면 이번 조각은 통째로 직전 청크의 부분집합이다.
        # 넣으면 같은 내용이 검색 결과에 두 번 나온다(에러 없이).
        if start > 0 and start + overlap >= len(text):
            break
        piece = text[start : start + chunk_size].strip()
        if piece:  # 공백뿐인 조각(연속 빈 줄 구간)은 저장할 가치가 없다
            chunks.append(piece)
    return chunks


def normalize_source(path: Path) -> str:
    # source는 "재인입의 키"다: 같은 문서는 실행 위치·경로 표기와 무관하게 항상
    # 같은 문자열이어야 한다. 오늘 'CLAUDE.md', 내일 '../CLAUDE.md'로 넣었을 때
    # 문자열이 다르면 ingest_file()의 delete 조건이 어긋나 같은 문서가 두 벌 쌓인다.
    # 그래서 절대경로로 편 뒤 저장소 루트 기준 상대경로로 고정하고, as_posix()로
    # 구분자도 통일한다 — Windows에서도 "chatbot/README.md"처럼 저장된다.
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        # 저장소 밖의 문서면 파일명만 쓴다 (학습 문서는 전부 저장소 안이라 드문 경로).
        return resolved.name


def insert_file(path: Path, source: str, store: VectorStore) -> tuple[int, int]:
    text = path.read_text(encoding="utf-8")
    chunks = chunk_text(text)

    # 임베딩은 파일 단위로 한 번에 — 청크마다 부르면 호출 오버헤드가 곱해진다.
    # 배치 분할은 fastembed가 내부에서 알아서 한다(기본 batch_size=256).
    vectors = embed_passages(chunks)

    # ★ 3-3a: "지우고 새로 넣기"를 이 함수가 더 이상 모른다 ★
    # 3-1에서 여기 있던 delete + add_all + commit은 pgvector_store.py로 옮겼다.
    # Postgres는 그 셋을 한 트랜잭션으로 묶을 수 있지만 Qdrant는 못 한다 —
    # "어떻게 멱등을 달성하는가"는 저장소마다 다른 구현 세부라 계약에 두면 안 된다.
    # 이 함수에 남은 것은 "무엇을 하는가"(읽기 → 청킹 → 임베딩 → 업서트)뿐이고,
    # 그 넷은 저장소가 바뀌어도 같다.
    deleted = store.upsert_document(source, chunks, vectors)
    return len(chunks), deleted


def main() -> None:
    # Windows 콘솔(cp949)에서 한글 print가 깨지지 않게 (2c 함정 4와 동일).
    # probe 스크립트들과 달리 모듈 레벨이 아니라 main() 안에서 하는 이유:
    # 이 모듈은 pytest가 chunk_text를 import한다 — "import만 했는데 전역
    # 상태(stdout)가 바뀌는" 부수효과는 라이브러리가 되는 순간 민폐다.
    sys.stdout.reconfigure(encoding="utf-8")

    # ★ 3-4: --store 플래그를 먼저 빼낸다 ★ pop_store_arg가 args를 제자리에서
    # 수정하므로, 아래 존재 검증은 남은 "파일 경로"만 보면 된다.
    # 이 순서가 중요하다 — 먼저 빼내지 않으면 "--store"가 파일 경로로 취급돼
    # "파일이 없다: --store"로 죽는다.
    args = sys.argv[1:]
    store_name = pop_store_arg(args)

    if not args:
        print("사용법: uv run python -m app.rag.ingest [--store pgvector|qdrant] <문서 경로>...")
        print("예:     uv run python -m app.rag.ingest ../CLAUDE.md ../SETUP.md")
        print("        uv run python -m app.rag.ingest --store qdrant ../CLAUDE.md")
        raise SystemExit(1)

    # 존재 검증을 먼저 전부 끝낸다 — 세 번째 경로의 오타 때문에, 몇 분짜리
    # 임베딩을 마친 앞 파일들만 인입된 "반쯤 된 상태"로 끝나느니 시작 전에 죽는다.
    paths = [Path(raw) for raw in args]
    missing = [raw for raw, path in zip(args, paths, strict=True) if not path.is_file()]
    if missing:
        raise SystemExit(f"파일이 없다:{','.join(missing)}")

    # ★ 3-4: 예고한 대로 이 한 줄만 바뀌었다 ★ (3-3a에서는 PgVectorStore() 고정)
    #
    # ★ 루프 "밖"에서 한 번만 만드는 것이 중요하다 ★ PgVectorStore는 상태가 없어
    # 차이가 없었지만, QdrantStore는 HTTP 커넥션을 들고 있어서 파일마다 새로 만들면
    # 연결이 파일 수만큼 생긴다. 3-3a에서 위치를 잡아둔 덕에 여기서 고칠 게 없었다.
    store = get_store(store_name)
    print(f"[저장소: {store_name or settings.vector_store}]")

    for path in paths:
        source = normalize_source(path)
        startd = time.perf_counter()
        inserted, deleted = insert_file(path, source, store)
        elapsed = time.perf_counter() - startd
        print(f"{source}:청크 {inserted}개 저장 (기존 {deleted}개 삭제, {elapsed:.1f}초)")


if __name__ == "__main__":
    main()
