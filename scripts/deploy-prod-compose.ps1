# 클라우드 VM(Docker + Compose만 설치된 서버)에 SSH로 원격 배포한다.
# k3s가 필요한 scripts/deploy-prod.ps1(k8s 경로)의 대안이다 - k8s 경로는
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
# 사용법: ./scripts/deploy-prod-compose.ps1 <user>@<VM_PUBLIC_IP> [-VmPublicIp <IP>]
param(
    [Parameter(Mandatory = $true)] [string]$SshTarget,
    [string]$VmPublicIp
)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

if (-not $VmPublicIp) { $VmPublicIp = $SshTarget.Split('@')[-1] }
$RemoteDir = "react-python-deploy"

if (-not (Test-Path ".env.prod")) {
    Write-Host ".env.prod가 없다. cp .env.prod.example .env.prod 후 실제 값으로 수정."
    exit 1
}
if (Select-String -Path ".env.prod" -Pattern "POSTGRES_PASSWORD=postgres$" -Quiet) {
    Write-Host "경고: example 더미 비밀번호가 그대로 있다. 이 VM은 공인 IP를 가진다."
    $confirm = Read-Host "그래도 계속할까? [y/N]"
    if ($confirm -ne "y") { exit 1 }
}

# .env.prod 전체를 파싱하지 않고 필요한 값들만 뽑아온다.
$DomainOverride = ""
$GhcrUsername = ""
$GhcrToken = ""
foreach ($line in Get-Content ".env.prod") {
    if ($line -match '^DOMAIN=(.*)$') { $DomainOverride = $Matches[1] }
    if ($line -match '^GHCR_USERNAME=(.*)$') { $GhcrUsername = $Matches[1] }
    if ($line -match '^GHCR_TOKEN=(.*)$') { $GhcrToken = $Matches[1] }
}
$AppDomain = if ($DomainOverride) { $DomainOverride } else { "app.$VmPublicIp.nip.io" }

Write-Host "==> nginx-proxy/conf.d 렌더링 (host: $AppDomain)"
$RenderDir = Join-Path ([System.IO.Path]::GetTempPath()) ([System.IO.Path]::GetRandomFileName())
New-Item -ItemType Directory -Path $RenderDir | Out-Null
try {
    Get-ChildItem "nginx-proxy/conf.d/*.conf" | ForEach-Object {
        (Get-Content $_.FullName -Raw) -replace '__APP_DOMAIN__', $AppDomain |
            Set-Content -Path (Join-Path $RenderDir $_.Name) -NoNewline
    }

    Write-Host "==> $SshTarget 에 docker-compose.prod.yml / .env.prod / nginx-proxy 전송"
    ssh $SshTarget "mkdir -p $RemoteDir/nginx-proxy/conf.d $RemoteDir/nginx-proxy/ssl"
    scp docker-compose.prod.yml .env.prod "${SshTarget}:${RemoteDir}/"
    # scp.exe는 bash와 달리 와일드카드를 자동 확장하지 않으므로 파일별로 전송한다.
    Get-ChildItem $RenderDir -Filter "*.conf" | ForEach-Object {
        scp $_.FullName "${SshTarget}:${RemoteDir}/nginx-proxy/conf.d/"
    }
    ssh $SshTarget "chmod 600 $RemoteDir/.env.prod"

    # SSL 인증서가 준비돼 있으면(nginx-proxy/ssl/README.md 참고) 함께 전송한다.
    # 아직 파일이 없으면(테스트 단계) 조용히 건너뛴다.
    $SslFiles = Get-ChildItem "nginx-proxy/ssl/*.pem" -ErrorAction SilentlyContinue
    if ($SslFiles) {
        Write-Host "==> SSL 인증서 전송"
        $SslFiles | ForEach-Object {
            scp $_.FullName "${SshTarget}:${RemoteDir}/nginx-proxy/ssl/"
        }
        ssh $SshTarget "chmod 600 $RemoteDir/nginx-proxy/ssl/privkey.pem 2>/dev/null || true"
    }
} finally {
    Remove-Item -Recurse -Force $RenderDir
}

if ($GhcrToken) {
    Write-Host "==> GHCR 로그인 (private 패키지 pull용, PAT은 stdin으로만 전달)"
    $GhcrToken | ssh $SshTarget "docker login ghcr.io -u $GhcrUsername --password-stdin"
}

Write-Host "==> 최신 GHCR 이미지 pull"
ssh $SshTarget "cd $RemoteDir && docker compose -f docker-compose.prod.yml --env-file .env.prod pull"

Write-Host "==> 스택 기동/갱신"
ssh $SshTarget "cd $RemoteDir && docker compose -f docker-compose.prod.yml --env-file .env.prod up -d"

Write-Host "==> 마이그레이션 적용 (alembic upgrade head는 멱등적이라 매번 실행해도 안전)"
ssh $SshTarget "cd $RemoteDir && docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm backend alembic upgrade head"

Write-Host "==> 완료"
Write-Host "http://$AppDomain"
