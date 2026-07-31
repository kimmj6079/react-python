#!/usr/bin/env bash
# 운영 서버(VM) 안에서 cron이 주기적으로 실행하는 DB 백업 스크립트.
# 다른 scripts/*.sh(로컬에서 SSH로 원격을 조작)와 달리, 이 파일은 배포 시
# VM의 react-python-deploy/ 안으로 복사되어 그 자리에서 직접 실행된다
# (deploy-prod-compose.sh가 전송 + crontab 등록까지 자동으로 처리한다).
#
# 수동으로 한 번 테스트하려면 VM에서: cd react-python-deploy && ./backup-db.sh
set -euo pipefail
cd "$(dirname "$0")"

BACKUP_DIR="backups"
RETENTION_DAYS=7
mkdir -p "$BACKUP_DIR"

# .env.prod를 통째로 source하지 않고 필요한 값만 뽑아온다(다른 스크립트들과
# 동일한 이유 - 비밀번호에 셸 특수문자가 있어도 안전하게).
POSTGRES_USER="$(grep -E '^POSTGRES_USER=' .env.prod | cut -d= -f2-)"
POSTGRES_DB="$(grep -E '^POSTGRES_DB=' .env.prod | cut -d= -f2-)"

TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
FILE="${BACKUP_DIR}/db_${TIMESTAMP}.sql.gz"

docker compose -f docker-compose.prod.yml --env-file .env.prod exec -T db \
  pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" | gzip > "$FILE"

# 오래된 백업 정리 (VM 로컬 보관이라 디스크가 무한정 늘지 않도록)
find "$BACKUP_DIR" -name 'db_*.sql.gz' -mtime "+${RETENTION_DAYS}" -delete

echo "backup complete: ${FILE}"

# 참고: 이건 VM 로컬 디스크에만 남는 최소한의 백업이다. VM 자체가 사라지는
# 재해(리전 장애, 실수로 인스턴스 삭제 등)까지 대비하려면 이 파일을 S3 등
# 오브젝트 스토리지에 추가로 업로드하는 단계를 여기에 덧붙여야 한다 - 클라우드
# 제공자마다 방식이 달라 이 스크립트 범위 밖으로 남겨둔다.
