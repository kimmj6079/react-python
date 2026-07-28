#!/usr/bin/env bash
# 클라우드 VM(k3s)에 SSH로 원격 배포한다.
# 사전 준비: scripts/provision-vm.sh 1회 실행 완료, k8s/base/secret.yaml
# 준비(실제 강한 값), GHCR 패키지 Public 전환(또는 imagePullSecrets).
#
# 이미지는 여기서 빌드하지 않는다 — cd.yml이 main 푸시 시 이미 GHCR에
# :latest로 푸시해뒀다는 전제.
#
# 사용법: ./scripts/deploy-prod.sh <user>@<VM_PUBLIC_IP> [VM_PUBLIC_IP]
#   두 번째 인자는 선택. ssh 대상이 곧 IP가 아닌 경우(ssh config 별칭 등)
#   nip.io 호스트에 쓸 IP를 따로 지정할 때 사용.
set -euo pipefail
cd "$(dirname "$0")/.."

SSH_TARGET="${1:?사용법: deploy-prod.sh <user>@<VM_PUBLIC_IP> [VM_PUBLIC_IP]}"
VM_PUBLIC_IP="${2:-${SSH_TARGET#*@}}"
APP_HOST="app.${VM_PUBLIC_IP}.nip.io"
NS=study-app

if [ ! -f k8s/base/secret.yaml ]; then
  echo "k8s/base/secret.yaml이 없다. 먼저 example을 복사해 실제 값으로 채워라:"
  echo "  cp k8s/base/secret.yaml.example k8s/base/secret.yaml"
  exit 1
fi

if grep -q "postgres:postgres@" k8s/base/secret.yaml; then
  echo "경고: k8s/base/secret.yaml에 example 더미 비밀번호가 그대로 있다."
  echo "이 VM은 공인 IP를 가진다 — postgres/postgres 기본값은 안전하지 않다."
  read -r -p "그래도 계속할까? [y/N] " confirm
  [ "${confirm:-}" = "y" ] || exit 1
fi

echo "==> k8s/overlays/prod 렌더링 (host: ${APP_HOST})"
manifest="$(kubectl kustomize k8s/overlays/prod \
  | sed -e "s/__VM_PUBLIC_IP__/${VM_PUBLIC_IP}/g" \
        -e "s/imagePullPolicy: IfNotPresent/imagePullPolicy: Always/g")"

echo "==> ${SSH_TARGET}에 매니페스트 적용"
printf '%s\n' "$manifest" | ssh "$SSH_TARGET" "kubectl apply -f -"

echo "==> 최신 GHCR 이미지 강제 재수신을 위한 rollout restart"
ssh "$SSH_TARGET" "kubectl rollout restart deployment/backend deployment/frontend -n ${NS}"
ssh "$SSH_TARGET" "kubectl rollout status deployment/backend -n ${NS} --timeout=120s"
ssh "$SSH_TARGET" "kubectl rollout status deployment/frontend -n ${NS} --timeout=120s"

echo "==> 마이그레이션 재실행 (Job은 불변이라 delete 후 재생성)"
ssh "$SSH_TARGET" "kubectl delete job/migrate -n ${NS} --ignore-not-found"
sed 's/imagePullPolicy: IfNotPresent/imagePullPolicy: Always/' k8s/base/migrate-job.yaml \
  | ssh "$SSH_TARGET" "kubectl apply -f -"
ssh "$SSH_TARGET" "kubectl wait --for=condition=complete job/migrate -n ${NS} --timeout=120s"

echo "==> 완료"
echo "http://${APP_HOST}"
