#!/usr/bin/env bash
# backend/.env(평문 시크릿)를 backend/.env.enc(커밋 가능)로 암호화한다.
#
#   ./scripts/env-encrypt.sh
#
# ★ 왜 이런 게 필요한가 ★
# .env에는 살아있는 시크릿(ANTHROPIC_API_KEY, LANGFUSE_SECRET_KEY, DB 비밀번호)이 있어서
# 그대로 커밋하면 GitHub push protection이 막고, 뚫더라도 git 히스토리에 영구히 남는다.
# 그렇다고 커밋을 안 하면 새 PC마다 값을 손으로 다시 채워야 한다.
# 암호화해서 커밋하면 둘 다 해결된다 — 실무에서 시크릿을 리포에 넣는 유일하게 허용되는 방식이다.
#
# ★ 공개키만 있으면 암호화된다 (비대칭의 핵심) ★
# --recipient-file로 커밋된 공개키를 직접 쓰므로 gpg 키링에 아무것도 없어도 된다.
# 즉 CI나 팀원이 "시크릿을 추가"할 수는 있어도 "읽을" 수는 없다.
# 읽으려면 개인키가 필요하고, 그건 리포 밖에 있다(scripts/env-decrypt.sh 참고).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLAIN="$ROOT/backend/.env"
ENC="$ROOT/backend/.env.enc"
PUBKEY="$ROOT/backend/.env.pubkey.asc"

command -v gpg >/dev/null || { echo "gpg가 필요하다 (Git for Windows에 포함돼 있다)"; exit 1; }
[ -f "$PLAIN" ] || { echo "없다: backend/.env — 먼저 값을 채우거나 env-decrypt.sh로 복원한다"; exit 1; }
[ -f "$PUBKEY" ] || { echo "없다: backend/.env.pubkey.asc"; exit 1; }

gpg --yes --armor --recipient-file "$PUBKEY" --output "$ENC" --encrypt "$PLAIN"

# ★ 안전핀: 암호문에 평문 시크릿이 남아 있으면 즉시 죽는다 ★
# 암호화가 어떤 이유로 실패했는데 exit code가 0이면(또는 파일이 그대로 복사되면)
# 시크릿을 그대로 커밋하게 된다. 그런 사고는 조용히 일어나므로 여기서 시끄럽게 막는다.
if grep -qE 'sk-ant-|sk-lf-|pk-lf-|POSTGRES_PASSWORD=[^[:space:]]' "$ENC"; then
  rm -f "$ENC"
  echo "✘ 암호문에 평문 시크릿이 남아 있다 — .env.enc를 삭제했다. 커밋하지 말 것"
  exit 1
fi

echo "✔ backend/.env → backend/.env.enc ($(wc -c < "$ENC") bytes)"
echo "  이 파일은 커밋해도 된다. .env는 여전히 gitignore 대상이다."
