#!/usr/bin/env bash
# 클라우드 VM에 k3s(Traefik 비활성화) + ingress-nginx를 설치한다.
# 새 VM당 1회 실행. 멱등적으로 작성되어 재실행해도 안전하다.
#
# 사전 준비 (스크립트 밖에서 수동으로): 클라우드 콘솔에서 이 VM의
# 방화벽/보안그룹에 인바운드 TCP 22(SSH), 80(HTTP) 허용. 6443(k8s API)은
# 외부에 열 필요 없음 — kubectl은 항상 VM 내부(SSH 세션 안)에서만 실행한다.
#
# 사용법: ./scripts/provision-vm.sh <user>@<VM_PUBLIC_IP>
set -euo pipefail

SSH_TARGET="${1:?사용법: provision-vm.sh <user>@<VM_PUBLIC_IP>}"
INGRESS_NGINX_TAG="${INGRESS_NGINX_TAG:-controller-v1.11.3}"  # 최신 안정 태그는 https://github.com/kubernetes/ingress-nginx/releases 확인

ssh "$SSH_TARGET" INGRESS_NGINX_TAG="$INGRESS_NGINX_TAG" bash -s <<'REMOTE'
set -euo pipefail

if ! command -v k3s >/dev/null 2>&1; then
  echo "==> k3s 설치 (Traefik 비활성화)"
  curl -sfL https://get.k3s.io | \
    INSTALL_K3S_EXEC="server --disable=traefik" sh -
else
  echo "==> k3s 이미 설치됨, 설치 단계 건너뜀"
  echo "    (플래그를 바꾸려면 위 curl 명령을 수동으로 다시 실행)"
fi

echo "==> k3s API 준비 대기"
until sudo k3s kubectl get nodes >/dev/null 2>&1; do sleep 2; done

echo "==> kubectl을 sudo 없이 쓸 수 있도록 kubeconfig 복사"
mkdir -p ~/.kube
sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown "$(id -u)":"$(id -g)" ~/.kube/config
chmod 600 ~/.kube/config

echo "==> local-path StorageClass 확인 (k3s 기본 제공, 별도 설치 불필요)"
kubectl get storageclass

echo "==> ingress-nginx 설치 (${INGRESS_NGINX_TAG})"
kubectl apply -f "https://raw.githubusercontent.com/kubernetes/ingress-nginx/${INGRESS_NGINX_TAG}/deploy/static/provider/cloud/deploy.yaml"

echo "==> ingress-nginx admission webhook 준비 대기"
kubectl wait --namespace ingress-nginx \
  --for=condition=complete job \
  --selector=app.kubernetes.io/component=admission-webhook \
  --timeout=180s

echo "==> ingress-nginx controller 준비 대기"
kubectl wait --namespace ingress-nginx \
  --for=condition=ready pod \
  --selector=app.kubernetes.io/component=controller \
  --timeout=180s

echo "==> 완료. 노드 공인 IP의 80번 포트를 ingress-nginx가 처리한다."
kubectl get svc -n ingress-nginx ingress-nginx-controller
REMOTE
