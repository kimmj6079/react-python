#!/usr/bin/env bash
# backend/.env.enc(커밋된 암호문)를 backend/.env(평문)로 복원한다.
#
#   ./scripts/env-decrypt.sh          # .env가 이미 있으면 거부
#   ./scripts/env-decrypt.sh --force  # 덮어쓰기
#
# ★ 이 스크립트는 개인키가 있어야 동작한다 ★
# 개인키는 리포에 없다. 새 PC에서는 먼저 키를 가져와야 한다:
#
#   gpg --import react-python-env-secret.asc
#
# 그 파일은 비밀번호 관리자(1Password 등)에 보관한다. 백업 방법은 SETUP.md 참고.
# 키를 잃어버리면 .env.enc는 영원히 못 연다 — 그게 암호화의 정의다.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLAIN="$ROOT/backend/.env"
ENC="$ROOT/backend/.env.enc"

command -v gpg >/dev/null || { echo "gpg가 필요하다 (Git for Windows에 포함돼 있다)"; exit 1; }
[ -f "$ENC" ] || { echo "없다: backend/.env.enc"; exit 1; }

# ★ 기본은 덮어쓰기 거부 ★ .env에는 이 PC에서만 쓰는 로컬 값이 들어 있을 수 있고
# (다른 포트, 다른 DB), 복호화가 그걸 조용히 날리면 원인을 찾기 어렵다.
if [ -f "$PLAIN" ] && [ "${1:-}" != "--force" ]; then
  echo "이미 있다: backend/.env"
  echo "덮어쓰려면: ./scripts/env-decrypt.sh --force"
  exit 1
fi

gpg --yes --quiet --output "$PLAIN" --decrypt "$ENC"
echo "✔ backend/.env.enc → backend/.env ($(wc -l < "$PLAIN") 줄)"
