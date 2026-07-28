#!/usr/bin/env bash
# Build the app images and deploy them to a local minikube cluster.
# Prereqs: `minikube start` and `minikube addons enable ingress` already run.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> Building images"
docker build -t backend:local ./backend
docker build --target production -t frontend:local ./frontend

echo "==> Loading images into minikube"
minikube image load backend:local
minikube image load frontend:local

if [ ! -f k8s/base/secret.yaml ]; then
  echo "==> k8s/base/secret.yaml missing, copying from .example (edit with real values for anything beyond local study use)"
  cp k8s/base/secret.yaml.example k8s/base/secret.yaml
fi

echo "==> Applying manifests"
kubectl apply -k k8s/overlays/dev

echo "==> Running migrations"
kubectl delete job/migrate -n study-app --ignore-not-found
# migrate-job.yaml is outside overlays/dev's resources (Jobs are immutable,
# applied separately), so the dev overlay's images: transform never touches
# it -- substitute it here too, or it'll try to pull the GHCR tag instead of
# the image just loaded into minikube.
sed 's/ghcr.io\/kimmj6079\/react-python-backend:latest/backend:local/' k8s/base/migrate-job.yaml | kubectl apply -f -
kubectl wait --for=condition=complete job/migrate -n study-app --timeout=120s

kubectl wait --for=condition=available deployment/backend -n study-app --timeout=120s
kubectl wait --for=condition=available deployment/frontend -n study-app --timeout=120s

echo "==> Done"
echo "If the ingress addon is enabled: http://app.127.0.0.1.nip.io"
echo "Otherwise: minikube service frontend -n study-app --url"
