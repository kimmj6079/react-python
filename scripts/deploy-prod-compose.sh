#!/usr/bin/env bash
# 클라우드 VM(Docker + Compose만 설치된 서버)에 SSH로 원격 배포한다.
# k3s가 필요한 scripts/deploy-prod.sh(k8s 경로)의 대안이다 - k8s 경로는
# 그대로 두고, 이 스크립트는 순수 docker-compose로만 배포한다.
#
# 사전 준비: VM에 Docker + Compose 플러그인 설치 완료, 방화벽에 22(SSH)/80(HTTP,
# SSL 쓸 경우 443도) 인바운드 허용, .env.prod 준비(실제 강한 값). GHCR 패키지를
# Public으로 전환했다면 그걸로 끝이고, Private로 유지한다면 .env.prod의
# GHCR_USERNAME/GHCR_TOKEN을 채워야 한다(이 스크립트가 pull 전에 VM에서
# docker login을 자동 실행해준다). .env.prod의 DOMAIN을 비워두면(테스트 단계)
# app.<VM_PUBLIC_IP>.nip.io를 자동 계산하고, 실제 도메인을 채우면(운영 단계)
# 그 값을 그대로 쓴다. SSL 인증서는 nginx-proxy/ssl/README.md 참고.
#
# 이미지는 여기서 빌드하지 않는다 - cd.yml이 main 푸시 시 이미 GHCR에
# :latest로 푸시해뒀다는 전제.
#
# 사용법: ./scripts/deploy-prod-compose.sh <user>@<VM_PUBLIC_IP> [VM_PUBLIC_IP]
#   두 번째 인자는 선택. ssh 대상이 곧 IP가 아닌 경우(ssh config 별칭 등)
#   접속 URL에 쓸 IP를 따로 지정할 때 사용.
set -euo pipefail
cd "$(dirname "$0")/.."

SSH_TARGET="${1:?사용법: deploy-prod-compose.sh <user>@<VM_PUBLIC_IP> [VM_PUBLIC_IP]}"
VM_PUBLIC_IP="${2:-${SSH_TARGET#*@}}"
REMOTE_DIR="react-python-deploy"

if [ ! -f .env.prod ]; then
  echo ".env.prod가 없다. 먼저 example을 복사해 실제 값으로 채워라:"
  echo "  cp .env.prod.example .env.prod"
  exit 1
fi

if grep -q "POSTGRES_PASSWORD=postgres$" .env.prod; then
  echo "경고: .env.prod에 example 더미 비밀번호가 그대로 있다."
  echo "이 VM은 공인 IP를 가진다 - postgres/postgres 기본값은 안전하지 않다."
  read -r -p "그래도 계속할까? [y/N] " confirm
  [ "${confirm:-}" = "y" ] || exit 1
fi

# .env.prod 전체를 source하지 않고 필요한 값들만 뽑아온다(비밀번호에 셸 특수문자가
# 있어도 안전하게, 그리고 임의 코드 실행 없이).
DOMAIN_OVERRIDE="$(grep -E '^DOMAIN=' .env.prod | cut -d= -f2-)"
APP_DOMAIN="${DOMAIN_OVERRIDE:-app.${VM_PUBLIC_IP}.nip.io}"
GHCR_USERNAME="$(grep -E '^GHCR_USERNAME=' .env.prod | cut -d= -f2-)"
GHCR_TOKEN="$(grep -E '^GHCR_TOKEN=' .env.prod | cut -d= -f2-)"

echo "==> nginx-proxy/conf.d 렌더링 (host: ${APP_DOMAIN})"
RENDER_DIR="$(mktemp -d)"
trap 'rm -rf "$RENDER_DIR"' EXIT
cp nginx-proxy/conf.d/*.conf "$RENDER_DIR/"
sed -i "s/__APP_DOMAIN__/${APP_DOMAIN}/g" "$RENDER_DIR"/*.conf

echo "==> ${SSH_TARGET}에 docker-compose.prod.yml / .env.prod / nginx-proxy 전송"
ssh "$SSH_TARGET" "mkdir -p ${REMOTE_DIR}/nginx-proxy/conf.d ${REMOTE_DIR}/nginx-proxy/ssl"
scp docker-compose.prod.yml .env.prod "${SSH_TARGET}:${REMOTE_DIR}/"
scp "$RENDER_DIR"/*.conf "${SSH_TARGET}:${REMOTE_DIR}/nginx-proxy/conf.d/"
ssh "$SSH_TARGET" "chmod 600 ${REMOTE_DIR}/.env.prod"

# SSL 인증서가 준비돼 있으면(nginx-proxy/ssl/README.md 참고) 함께 전송한다.
# 아직 파일이 없으면(테스트 단계) 조용히 건너뛴다.
if compgen -G "nginx-proxy/ssl/*.pem" > /dev/null 2>&1; then
  echo "==> SSL 인증서 전송"
  scp nginx-proxy/ssl/*.pem "${SSH_TARGET}:${REMOTE_DIR}/nginx-proxy/ssl/"
  ssh "$SSH_TARGET" "chmod 600 ${REMOTE_DIR}/nginx-proxy/ssl/privkey.pem 2>/dev/null || true"
fi

if [ -n "$GHCR_TOKEN" ]; then
  echo "==> GHCR 로그인 (private 패키지 pull용, PAT은 stdin으로만 전달)"
  ssh "$SSH_TARGET" "docker login ghcr.io -u '${GHCR_USERNAME}' --password-stdin" <<< "$GHCR_TOKEN"
fi

echo "==> 최신 GHCR 이미지 pull"
ssh "$SSH_TARGET" "cd ${REMOTE_DIR} && docker compose -f docker-compose.prod.yml --env-file .env.prod pull"

echo "==> 스택 기동/갱신"
ssh "$SSH_TARGET" "cd ${REMOTE_DIR} && docker compose -f docker-compose.prod.yml --env-file .env.prod up -d"

echo "==> 마이그레이션 적용 (alembic upgrade head는 멱등적이라 매번 실행해도 안전)"
ssh "$SSH_TARGET" "cd ${REMOTE_DIR} && docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm backend alembic upgrade head"

echo "==> 완료"
echo "http://${APP_DOMAIN}"
