# 임베딩 캐시. 같은 텍스트를 두 번 임베딩하지 않는다. (M13-c)
#
# ★ 왜 "인입 경로"에만 넣는가 ★
# 13-b 계측에서 질의 임베딩이 검색 층의 70%(p50 113ms)였다. 그래서 "질의도 캐시하면
# 되겠다"가 첫 반응인데, 두 가지 이유로 **일부러 안 한다**:
#   1) 실사용에서 질문 문자열이 정확히 일치할 확률이 낮다. 히트하지 않는 캐시는
#      복잡도만 늘린다(FAQ성 서비스라면 결론이 다르다 — 그때는 히트율을 먼저 잰다).
#   2) ★ 더 중요한 이유: 계측 대상 경로에 캐시를 넣으면 그 계측기가 못 쓰게 된다 ★
#      질의를 캐시하면 `scripts/measure_latency.py`의 `embed` 항목이 두 번째 실행부터
#      0ms가 되고, 13-e에서 "무엇이 실제로 빨라졌는가"를 판단할 근거가 사라진다.
#
# 반면 인입은 캐시가 정확히 맞는 자리다:
#   - 문서를 한 줄 고치고 재인입하면 **대부분의 청크가 글자 하나 안 바뀐다.**
#   - 그런데 지금은 138개를 전부 다시 임베딩한다(M11의 doc_hash 스킵은 문서 전체가
#     같을 때만 걸리므로, 한 글자만 바뀌어도 통째로 다시 돈다).
#   - M7처럼 청킹 실험을 반복할 때도 같은 조각이 계속 재등장한다.
#
# ★ README의 "doc_hash 키 임베딩 캐시"를 정정한다 ★ 문서 단위 해시로는 부분 수정을
# 구제하지 못한다(그건 M11이 이미 하는 전체 스킵이다). 키는 **청크 본문 자체**여야 한다.
#
# ★ BM25(sparse)는 캐시하지 않는다 ★ 13-b 실측에서 0~1ms였다. 신경망이 아니라 토큰
# 통계라서 그렇다. **계측이 "여기는 캐시할 필요가 없다"까지 알려줬다.**
import array
import hashlib
import logging
import sqlite3
from collections.abc import Iterable
from contextlib import closing
from pathlib import Path

logger = logging.getLogger(__name__)

# backend/ 디렉터리. 상대 경로 설정을 여기 기준으로 푼다 — 그래야 CLI를 어디서
# 실행하든(backend/에서든 루트에서든) 같은 캐시 파일을 본다. cwd 기준으로 두면
# "왜 캐시가 매번 비어 있지"의 원인이 되고, 그건 조용히 느려지기만 하는 버그다.
BACKEND_DIR = Path(__file__).resolve().parents[2]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS embeddings (
    model TEXT NOT NULL,
    hash  TEXT NOT NULL,
    dim   INTEGER NOT NULL,
    vec   BLOB NOT NULL,
    PRIMARY KEY (model, hash)
) WITHOUT ROWID;
"""


def _key(text: str) -> str:
    # 텍스트 전문을 키로 쓰지 않고 해시로 줄인다. 청크가 수백~수천 자라 그대로 넣으면
    # 인덱스가 본문만큼 커진다. sha256은 충돌을 실무적으로 무시할 수 있다.
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class EmbeddingCache:
    """텍스트 → 벡터를 sqlite 파일에 담아두는 캐시.

    ★ 왜 Postgres 테이블이 아니라 sqlite 파일인가 ★
    새 SQLAlchemy 모델 + Alembic 리비전 + `models/__init__.py` 등록이 따라오는데,
    **이건 지워도 아무것도 잃지 않는 캐시**다. 스키마 마이그레이션이 필요한 물건과
    캐시를 같은 곳에 두면, 캐시를 비우는 일이 "DB 작업"이 되어버린다. 파일 하나면
    `rm`으로 끝난다. 표준 라이브러리라 의존성도 안 는다.

    ★ 연결을 들고 있지 않고 호출마다 연다 ★ sqlite 연결은 기본적으로 스레드 간
    공유가 안 된다(`check_same_thread`). 이 캐시는 CLI(메인 스레드)뿐 아니라 M11의
    업로드 인입(`BackgroundTasks` = 별도 스레드)에서도 불린다. 연결을 모듈 전역에
    두면 그 경로에서 `ProgrammingError`가 난다 — 연결 비용(수 ms)보다 이 사고가 비싸다.
    """

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn:
            conn.execute(_SCHEMA)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        """★ 반드시 closing()으로 감싸서 쓴다 ★

        `with sqlite3.connect(...) as conn:` 은 파이썬에서 가장 자주 틀리는 관용구다 —
        그 `with`는 **트랜잭션** 컨텍스트라 커밋/롤백만 하고 **연결을 닫지 않는다.**
        연결을 호출마다 새로 여는 이 설계에서 그대로 뒀다면 인입 한 번에 파일 핸들이
        수십 개씩 새고, GC가 치워주는 타이밍에 의존하는 코드가 된다.
        그래서 아래 호출부는 전부 `with closing(self._connect()) as conn:` 이고,
        커밋이 필요한 쓰기에서는 `conn.commit()`을 명시한다.
        """
        conn = sqlite3.connect(self.path, timeout=5.0)
        # WAL: 읽기와 쓰기가 서로를 막지 않는다. 인입이 두 개 동시에 돌 수 있는
        # 상황(업로드 + CLI)에서 "database is locked"를 줄인다.
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def get_many(self, model: str, texts: list[str]) -> dict[str, list[float]]:
        """캐시에 있는 것만 돌려준다. 없는 것은 키 자체가 없다."""
        if not texts:
            return {}

        keys = {_key(t): t for t in texts}
        found: dict[str, list[float]] = {}
        with closing(self._connect()) as conn:
            # IN 절을 청크로 나눈다 — sqlite의 기본 변수 상한(999)을 넘으면
            # "too many SQL variables"로 죽는다. 문서 하나가 1000청크를 넘는 일은
            # 드물지만, 드문 일이 나면 인입 전체가 실패한다.
            key_list = list(keys)
            for i in range(0, len(key_list), 500):
                batch = key_list[i : i + 500]
                placeholders = ",".join("?" * len(batch))
                # placeholders는 우리가 만든 "?" 문자열뿐이라 SQL 인젝션 여지가 없다.
                # 값은 전부 파라미터 바인딩으로 넘어간다.
                sql = (
                    "SELECT hash, dim, vec FROM embeddings "
                    f"WHERE model = ? AND hash IN ({placeholders})"
                )
                rows = conn.execute(sql, (model, *batch)).fetchall()
                for key, dim, blob in rows:
                    vector = array.array("f")
                    vector.frombytes(blob)
                    if len(vector) != dim:
                        # 파일이 깨졌다. 캐시는 버려도 되는 물건이라 조용히 미스 처리한다.
                        continue
                    found[keys[key]] = list(vector)
        return found

    def put_many(self, model: str, pairs: Iterable[tuple[str, list[float]]]) -> None:
        rows = [
            (model, _key(text), len(vector), array.array("f", vector).tobytes())
            for text, vector in pairs
        ]
        if not rows:
            return
        with closing(self._connect()) as conn:
            # ★ float32로 저장한다 ★ 임베딩 원본은 float32이고(fastembed의 numpy 배열),
            # 파이썬 float(=C double)로 두면 파일이 두 배가 된다. 벡터 하나가 4KB다.
            conn.executemany(
                "INSERT OR REPLACE INTO embeddings (model, hash, dim, vec) VALUES (?, ?, ?, ?)",
                rows,
            )
            conn.commit()

    def count(self, model: str | None = None) -> int:
        with closing(self._connect()) as conn:
            if model is None:
                return conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
            return conn.execute(
                "SELECT COUNT(*) FROM embeddings WHERE model = ?", (model,)
            ).fetchone()[0]


_cache: EmbeddingCache | None = None


def get_cache() -> EmbeddingCache:
    """프로세스당 하나. 파일을 만들고 스키마를 거는 비용을 매번 내지 않는다."""
    global _cache
    if _cache is None:
        from app.core.config import settings

        path = Path(settings.embedding_cache_path)
        if not path.is_absolute():
            path = BACKEND_DIR / path
        _cache = EmbeddingCache(path)
        logger.info("임베딩 캐시: %s (%d개 보관 중)", path, _cache.count())
    return _cache
