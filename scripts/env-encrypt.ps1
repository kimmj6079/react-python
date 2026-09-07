# backend/.env(평문 시크릿)를 backend/.env.enc(커밋 가능)로 암호화한다.
#
#   .\scripts\env-encrypt.ps1
#
# env-encrypt.sh의 PowerShell 판. 이 저장소는 deploy-prod.sh/.ps1처럼 두 벌을 두는
# 관례를 쓴다 — 주 개발 환경이 Windows이기 때문이다.
# 설계 의도와 "왜 이런 게 필요한가"는 .sh 쪽 주석에 자세히 적어뒀다.
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$plain = Join-Path $root "backend\.env"
$enc = Join-Path $root "backend\.env.enc"
$pubkey = Join-Path $root "backend\.env.pubkey.asc"

# ★ gpg 위치 찾기 ★ Git for Windows가 gpg를 같이 깔지만, 설치 시 PATH에 넣는 것은
# cmd 디렉터리뿐이라 usr\bin은 PowerShell에서 안 보인다(Git Bash에서는 보인다).
# "Git Bash에서는 되는데 PowerShell에서는 gpg를 못 찾는다"의 정체가 이것이다.
$gpg = (Get-Command gpg -ErrorAction SilentlyContinue).Source
if (-not $gpg) {
    $fallback = Join-Path $env:ProgramFiles "Git\usr\bin\gpg.exe"
    if (Test-Path $fallback) { $gpg = $fallback }
}
if (-not $gpg) {
    throw "gpg를 찾을 수 없다. Git for Windows에 포함돼 있다 - Git Bash에서 실행하거나 PATH에 usr\bin을 추가한다"
}
if (-not (Test-Path $plain)) {
    throw "없다: backend\.env - 먼저 값을 채우거나 env-decrypt.ps1로 복원한다"
}
if (-not (Test-Path $pubkey)) { throw "없다: backend\.env.pubkey.asc" }

& $gpg --yes --armor --recipient-file $pubkey --output $enc --encrypt $plain
if ($LASTEXITCODE -ne 0) { throw "gpg 암호화 실패" }

# 안전핀: 암호문에 평문 시크릿이 남아 있으면 즉시 죽는다 (.sh와 동일)
$leaked = Select-String -Path $enc -Pattern 'sk-ant-|sk-lf-|pk-lf-' -Quiet
if ($leaked) {
    Remove-Item $enc -Force
    throw "암호문에 평문 시크릿이 남아 있다 - .env.enc를 삭제했다. 커밋하지 말 것"
}

$size = (Get-Item $enc).Length
Write-Output "OK  backend\.env -> backend\.env.enc ($size bytes)"
Write-Output "    이 파일은 커밋해도 된다. .env는 여전히 gitignore 대상이다."
