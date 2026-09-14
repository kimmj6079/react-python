# 체크포인터 테이블을 만드는 **명시적 단계**. (M5-2)
#
# 실행 (backend/에서):
#   uv run python -m app.db.checkpointer_setup
#
# ★ 왜 앱 기동 시점에 안 부르는가 ★
# 인터넷 예제 대부분은 `await checkpointer.setup()`을 lifespan이나 첫 요청에서 부른다.
# 이 저장소는 안 그런다 — CLAUDE.md가 "마이그레이션은 절대 컨테이너 시작 시 자동
# 실행되지 않는다"고 정한 것과 **완전히 같은 이유**다:
#   - 스키마 변경은 감사 가능한 별도 단계여야 한다. 언제 무엇이 바뀌었는지 답할 수 있어야 한다.
#   - 롤링 업데이트 중에는 파드가 여러 개 동시에 뜬다. 그 전부가 DDL을 시도한다.
#   - 앱 계정이 DDL 권한을 갖고 있어야 한다는 뜻이기도 하다. 실무에서는 보통 안 준다.
#
# ★ 왜 동기 PostgresSaver를 쓰는가 (런타임은 비동기인데) ★
# 만드는 테이블이 **완전히 같기 때문**이다(실측: 두 클래스가 같은 MIGRATIONS 리스트를
# 공유한다, 10개). 그리고 동기 쪽을 쓰면 Windows의 이벤트 루프 함정을 통째로 피한다 —
# psycopg 비동기는 Windows 기본 루프에서 동작하지 않는데, 이 스크립트는 개발자가
# 손으로 돌리는 것이라 그 제약을 받을 이유가 없다.
# **DDL은 동기로, 런타임은 비동기로.** 한 번 쓰고 버리는 연결에 비동기가 줄 값이 없다.
#
# ★ alembic과 나란히 두지만 alembic이 관리하지 않는다 ★
# 이 테이블들의 스키마는 langgraph가 정의하고 자기 버전 테이블(checkpoint_migrations)로
# 관리한다. 우리가 alembic 리비전으로 베껴 쓰면 라이브러리를 올리는 날 어긋난다 —
# **남의 스키마를 우리 마이그레이션에 복사하지 않는다.** 대신 실행 시점만 우리가 정한다.
import logging
import sys

from app.core.checkpointer import to_psycopg_dsn
from app.core.config import settings


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if settings.checkpointer == "memory":
        # ★ 조용히 성공하지 않는다 ★ memory 모드에서 이 스크립트가 "완료"를 찍으면,
        # 테이블이 생긴 줄 알고 넘어갔다가 재시작 때 대화가 사라진 것을 보고 헤맨다.
        raise SystemExit(
            "CHECKPOINTER=memory 라서 만들 테이블이 없다. "
            "대화를 영속화하려면 CHECKPOINTER=postgres로 두고 다시 실행한다."
        )

    dsn = to_psycopg_dsn(settings.database_url)

    # 함수 안에서 import: memory 모드로만 쓰는 환경에 이 패키지를 강제하지 않는다.
    from langgraph.checkpoint.postgres import PostgresSaver

    # from_conn_string은 컨텍스트 매니저다(실측 시그니처: -> Iterator[PostgresSaver]).
    # 연결 하나를 열고 setup()만 돌린 뒤 바로 닫는다 — 풀이 필요 없다.
    with PostgresSaver.from_conn_string(dsn) as saver:
        # setup()은 멱등이다. checkpoint_migrations 테이블에 적용된 버전을 남겨두고,
        # 이미 적용된 것은 건너뛴다 — alembic이 alembic_version을 쓰는 것과 같은 방식이다.
        # 그래서 몇 번을 돌려도 안전하고, 라이브러리를 올린 뒤 다시 돌리는 것이 정상 절차다.
        saver.setup()

    print("체크포인터 테이블 준비 완료 (checkpoints · checkpoint_blobs · checkpoint_writes)")
    print("★ langgraph를 올린 뒤에는 이 스크립트를 다시 돌린다 — 새 마이그레이션이 있을 수 있다")


if __name__ == "__main__":
    main()
