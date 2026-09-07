# backend/.env.enc(커밋된 암호문)를 backend/.env(평문)로 복원한다.
#
#   .\scripts\env-decrypt.ps1          # .env가 이미 있으면 거부
#   .\scripts\env-decrypt.ps1 -Force   # 덮어쓰기
#
# ★ 개인키가 있어야 동작한다 ★ 개인키는 리포에 없다. 새 PC에서는 먼저:
#   gpg --import react-python-env-secret.asc
# 백업 방법은 SETUP.md 참고. 키를 잃으면 .env.enc는 영원히 못 연다.
param([switch]$Force)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$plain = Join-Path $root "backend\.env"
$enc = Join-Path $root "backend\.env.enc"

# gpg 위치 찾기 (env-encrypt.ps1과 동일한 이유 - 그쪽 주석 참고)
$gpg = (Get-Command gpg -ErrorAction SilentlyContinue).Source
if (-not $gpg) {
    $fallback = Join-Path $env:ProgramFiles "Git\usr\bin\gpg.exe"
    if (Test-Path $fallback) { $gpg = $fallback }
}
if (-not $gpg) {
    throw "gpg를 찾을 수 없다. Git for Windows에 포함돼 있다 - Git Bash에서 실행하거나 PATH에 usr\bin을 추가한다"
}
if (-not (Test-Path $enc)) { throw "없다: backend\.env.enc" }

# 기본은 덮어쓰기 거부 - .env에 이 PC에서만 쓰는 로컬 값이 있을 수 있다
if ((Test-Path $plain) -and (-not $Force)) {
    Write-Output "이미 있다: backend\.env"
    Write-Output "덮어쓰려면: .\scripts\env-decrypt.ps1 -Force"
    exit 1
}

& $gpg --yes --quiet --output $plain --decrypt $enc
if ($LASTEXITCODE -ne 0) { throw "gpg 복호화 실패 - 개인키를 import했는지 확인한다" }

$lines = (Get-Content $plain | Measure-Object -Line).Lines
Write-Output "OK  backend\.env.enc -> backend\.env ($lines 줄)"
