# 클라우드 VM(k3s)에 SSH로 원격 배포한다.
# 사전 준비: scripts/provision-vm.sh 1회 실행 완료, k8s/base/secret.yaml
# 준비(실제 강한 값), GHCR 패키지 Public 전환(또는 imagePullSecrets).
#
# 이미지는 여기서 빌드하지 않는다 - cd.yml이 main 푸시 시 이미 GHCR에
# :latest로 푸시해뒀다는 전제.
#
# 사용법: ./scripts/deploy-prod.ps1 <user>@<VM_PUBLIC_IP> [-VmPublicIp <IP>]
param(
    [Parameter(Mandatory = $true)] [string]$SshTarget,
    [string]$VmPublicIp
)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

if (-not $VmPublicIp) { $VmPublicIp = $SshTarget.Split('@')[-1] }
$AppHost = "app.$VmPublicIp.nip.io"
$Ns = "study-app"

if (-not (Test-Path "k8s/base/secret.yaml")) {
    Write-Host "k8s/base/secret.yaml이 없다. cp k8s/base/secret.yaml.example k8s/base/secret.yaml 후 실제 값으로 수정."
    exit 1
}
if (Select-String -Path "k8s/base/secret.yaml" -Pattern "postgres:postgres@" -Quiet) {
    Write-Host "경고: example 더미 비밀번호가 그대로 있다. 이 VM은 공인 IP를 가진다."
    $confirm = Read-Host "그래도 계속할까? [y/N]"
    if ($confirm -ne "y") { exit 1 }
}

Write-Host "==> k8s/overlays/prod 렌더링 (host: $AppHost)"
$manifest = (kubectl kustomize k8s/overlays/prod) `
    -replace '__VM_PUBLIC_IP__', $VmPublicIp `
    -replace 'imagePullPolicy: IfNotPresent', 'imagePullPolicy: Always'

Write-Host "==> $SshTarget 에 매니페스트 적용"
$manifest | ssh $SshTarget "kubectl apply -f -"

Write-Host "==> 최신 GHCR 이미지 강제 재수신을 위한 rollout restart"
ssh $SshTarget "kubectl rollout restart deployment/backend deployment/frontend -n $Ns"
ssh $SshTarget "kubectl rollout status deployment/backend -n $Ns --timeout=120s"
ssh $SshTarget "kubectl rollout status deployment/frontend -n $Ns --timeout=120s"

Write-Host "==> 마이그레이션 재실행 (Job은 불변이라 delete 후 재생성)"
ssh $SshTarget "kubectl delete job/migrate -n $Ns --ignore-not-found"
(Get-Content "k8s/base/migrate-job.yaml" -Raw) -replace 'imagePullPolicy: IfNotPresent', 'imagePullPolicy: Always' |
    ssh $SshTarget "kubectl apply -f -"
ssh $SshTarget "kubectl wait --for=condition=complete job/migrate -n $Ns --timeout=120s"

Write-Host "==> 완료"
Write-Host "http://$AppHost"
