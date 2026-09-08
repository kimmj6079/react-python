# 문서 인입(ingest): 파일을 읽어 → 청킹 → 임베딩 → document_chunks에 저장한다.
#
# 실행 (backend/에서):
#   uv run python -m app.rag.ingest ../CLAUDE.md ../SETUP.md ../DEPLOYMENT.md
#
# 같은 문서를 다시 넣으면 옛 청크를 지우고 새로 넣는다(멱등) — insert_file() 참고.
#
# ★ M7-1: 청킹이 app/rag/chunking.py로 빠졌다 ★
# 3-1의 "600자마다 자르기"(chunk_text)는 마크다운 구조도 토큰 수도 몰랐다.
# 이 파일에 남은 책임은 "파일을 읽어 store에 넣는 절차"뿐이고, "어떻게 자르는가"는
# chunking.py가 안다 — 저장소를 factory.py가 아는 것과 같은 분리다.

import sys
import time
from pathlib import Path

from app.core.config import settings
from app.rag.access import DEFAULT_ALLOWED_ROLES, DEFAULT_TENANT_ID
from app.rag.base import Chunk, HybridStore, VectorStore
from app.rag.chunking import MAX_TOKENS, OVERLAP_TOKENS, split_markdown
from app.rag.embedding import embed_passages, embed_sparse_passages
from app.rag.factory import get_store, pop_store_arg

# source 키의 기준점: …/backend/app/rag/ingest.py에서 세 단계 위 = 저장소 루트
REPO_ROOT = Path(__file__).resolve().parents[3]


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


def ingest_text(
    text: str,
    source: str,
    store: VectorStore,
    *,
    max_tokens: int = MAX_TOKENS,
    overlap_tokens: int = OVERLAP_TOKENS,
    strip_headers: bool = False,
    embed_heading_path: bool = False,
    tenant_id: str = DEFAULT_TENANT_ID,
    allowed_roles: list[str] | None = None,
) -> tuple[int, int, list[int]]:
    """청킹 → 임베딩 → 업서트. (청크 수, 삭제 수, 청크별 토큰 수)를 돌려준다.

    ★ M11에서 파일이 아니라 텍스트를 받도록 바꿨다 ★ 업로드 인입(documents.py)은
    디스크의 파일이 아니라 **메모리의 바이트**에서 출발한다. "읽기"를 호출자에게
    밀어내면 CLI(파일)와 업로드(멀티파트) 둘 다 같은 코어를 쓴다 —
    build_graph가 model을 인자로 받는 것과 같은 사고방식이다.

    ★ 토큰 수를 돌려주는 이유 ★ M7의 주장은 "청크가 더 나은 경계로 잘린다"인데,
    그게 사실인지 보려면 분포를 봐야 한다. 개수만 찍으면 "청크가 늘었다/줄었다"까지만
    알 수 있고, 평균 220 토큰인지 한쪽에 쏠려 있는지는 안 보인다.
    """
    chunks = split_markdown(
        text,
        max_tokens=max_tokens,
        overlap_tokens=overlap_tokens,
        strip_headers=strip_headers,
    )

    # ★★ M7-2: heading_path를 임베딩 텍스트에 붙이는 것은 기본값이 False다 ★★
    #
    # README의 M7 계획은 "청크 본문 맨 앞에 heading_path를 넣어 임베딩한다 — 코드 세
    # 줄로 지표가 눈에 띄게 움직이는 경우가 많다"였다. **우리 말뭉치에서는 반대였다.**
    # M6 하네스로 다섯 설정을 돌린 결과(evals/results/BASELINE-M7.md):
    #
    #   구조인식+토큰, 헤딩 본문 유지, 경로 미부착   MRR 0.794  <- 최고
    #   (베이스라인 600자 고정)                      MRR 0.791
    #   헤딩 본문 유지 + 경로도 부착(중복)           MRR 0.732
    #   헤딩 제거, 경로 미부착                       MRR 0.721
    #   헤딩 제거 + 경로 부착                        MRR 0.667  <- 최악
    #
    # 왜 안 통했는지의 가설: 우리 청크는 평균 133토큰으로 짧고 heading_path는 한글이라
    # 길다("CLAUDE.md > 작업 방식 — 이 저장소는 학습용이다" 만 20토큰 남짓). 짧은 청크에
    # 긴 제목을 붙이면 **같은 섹션의 청크들이 서로 가까워지고 각자의 본문에서 멀어진다.**
    # 게다가 문서가 3개뿐이라 "어느 문서인가"는 source가 이미 구분해준다.
    #
    # ★ 그래도 heading_path를 저장하고 출처에 표시하는 것은 유지한다 ★ 임베딩에 넣는
    # 것과 저장/표시하는 것은 다른 결정이다. 저장은 M10 인용 카드가 쓰고, 출처 표기
    # (graph.py의 _format_context)는 모델에게 "이건 어느 절 이야기"를 알려준다.
    # 끈 것은 "임베딩 벡터에 섞는 것" 하나뿐이다.
    #
    # 말뭉치가 커지거나(수십 문서) 헤딩이 짧은 영어 문서라면 결론이 달라질 수 있어
    # 플래그로 남겨뒀다 — 지우지 않고 끄는 이유다.
    def embed_text(c: Chunk) -> str:
        if embed_heading_path and c.heading_path:
            return f"{c.heading_path}\n\n{c.content}"
        return c.content

    # ★ M12: 청크에 권한을 새긴다 ★ 인입 시점에 정해지고, 검색은 그걸 필터로만 본다.
    # 인입할 때 안 붙이면 나중에 붙일 방법이 없다 - 전부 재인입해야 한다.
    roles = allowed_roles or list(DEFAULT_ALLOWED_ROLES)
    for chunk in chunks:
        chunk.tenant_id = tenant_id
        chunk.allowed_roles = list(roles)

    texts = [embed_text(c) for c in chunks]

    # 임베딩은 파일 단위로 한 번에 — 청크마다 부르면 호출 오버헤드가 곱해진다.
    # 배치 분할은 fastembed가 내부에서 알아서 한다(기본 batch_size=256).
    vectors = embed_passages(texts)

    # ★ M8: 저장소가 하이브리드를 할 수 있을 때만 BM25를 계산한다 ★
    # pgvector에 넣을 때 sparse를 계산하면 CPU만 쓰고 버려진다. "능력을 물어보고
    # 분기한다"는 retriever.py의 판단과 같은 것을 인입 쪽에서도 한다.
    sparse = embed_sparse_passages(texts) if isinstance(store, HybridStore) else None

    # ★ 3-3a: "지우고 새로 넣기"를 이 함수가 더 이상 모른다 ★
    # 3-1에서 여기 있던 delete + add_all + commit은 pgvector_store.py로 옮겼다.
    # Postgres는 그 셋을 한 트랜잭션으로 묶을 수 있지만 Qdrant는 못 한다 —
    # "어떻게 멱등을 달성하는가"는 저장소마다 다른 구현 세부라 계약에 두면 안 된다.
    # 이 함수에 남은 것은 "무엇을 하는가"(읽기 → 청킹 → 임베딩 → 업서트)뿐이고,
    # 그 넷은 저장소가 바뀌어도 같다.
    deleted = store.upsert_document(source, chunks, vectors, sparse)
    return len(chunks), deleted, [c.token_count for c in chunks]


def insert_file(
    path: Path, source: str, store: VectorStore, **kwargs
) -> tuple[int, int, list[int]]:
    """파일 경로용 얇은 껍데기. CLI가 쓴다."""
    return ingest_text(path.read_text(encoding="utf-8"), source, store, **kwargs)


def main() -> None:
    # Windows 콘솔(cp949)에서 한글 print가 깨지지 않게 (2c 함정 4와 동일).
    # probe 스크립트들과 달리 모듈 레벨이 아니라 main() 안에서 하는 이유:
    # 이 모듈은 다른 모듈이 import한다 — "import만 했는데 전역 상태(stdout)가
    # 바뀌는" 부수효과는 라이브러리가 되는 순간 민폐다.
    sys.stdout.reconfigure(encoding="utf-8")

    # ★ 3-4: --store 플래그를 먼저 빼낸다 ★ pop_store_arg가 args를 제자리에서
    # 수정하므로, 아래 존재 검증은 남은 "파일 경로"만 보면 된다.
    # 이 순서가 중요하다 — 먼저 빼내지 않으면 "--store"가 파일 경로로 취급돼
    # "파일이 없다: --store"로 죽는다.
    args = sys.argv[1:]
    store_name = pop_store_arg(args)

    # ★ M7-1: 청킹 파라미터를 플래그로 뺐다 ★ M6 하네스로 A/B를 돌리려면 재인입
    # 설정을 명령 한 줄로 바꿀 수 있어야 한다. --strip-headers는 "헤딩을 본문에서
    # 지울 것인가"인데, 그 한 줄이 지표를 얼마나 움직이는지가 M7-2의 근거가 된다.
    strip_headers = "--strip-headers" in args
    if strip_headers:
        args.remove("--strip-headers")
    embed_heading_path = "--embed-heading" in args
    if embed_heading_path:
        args.remove("--embed-heading")
    max_tokens = MAX_TOKENS
    if "--max-tokens" in args:
        i = args.index("--max-tokens")
        args.pop(i)
        max_tokens = int(args.pop(i))

    if not args:
        print(
            "사용법: uv run python -m app.rag.ingest [--store pgvector|qdrant] "
            "[--strip-headers] [--embed-heading] [--max-tokens N] <문서 경로>..."
        )
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
    print(
        f"[저장소: {store_name or settings.vector_store}] "
        f"[max_tokens={max_tokens} overlap={OVERLAP_TOKENS} "
        f"strip_headers={strip_headers} embed_heading={embed_heading_path}]"
    )

    all_tokens: list[int] = []
    for path in paths:
        source = normalize_source(path)
        startd = time.perf_counter()
        inserted, deleted, tokens = insert_file(
            path,
            source,
            store,
            max_tokens=max_tokens,
            strip_headers=strip_headers,
            embed_heading_path=embed_heading_path,
        )
        elapsed = time.perf_counter() - startd
        all_tokens += tokens
        span = f"{min(tokens)}~{max(tokens)}" if tokens else "-"
        avg = sum(tokens) / len(tokens) if tokens else 0
        print(
            f"{source}: 청크 {inserted}개 저장 (기존 {deleted}개 삭제, {elapsed:.1f}초) "
            f"토큰 {span} 평균 {avg:.0f}"
        )

    if all_tokens:
        # 전체 분포를 한 줄로. 3-1의 "chunk_index=1 오타" 교훈과 같은 성질이다 —
        # "행이 있는가"가 아니라 "값이 맞는가"를 본다.
        over = sum(1 for t in all_tokens if t > 508)
        print(
            f"\n합계 {len(all_tokens)}청크 · 토큰 {min(all_tokens)}~{max(all_tokens)} "
            f"평균 {sum(all_tokens) / len(all_tokens):.0f} · e5 한도 초과 {over}개"
        )


if __name__ == "__main__":
    main()
