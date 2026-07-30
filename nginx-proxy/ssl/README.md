# SSL 인증서 배치 위치

이 디렉터리에 아래 두 파일을 넣으면 `docker-compose.prod.yml`의 `nginx` 서비스가
`/etc/nginx/ssl/`로 그대로 마운트해서 읽는다 (Let's Encrypt/`certbot` 기준 파일명 관례):

- `fullchain.pem` — 인증서 체인(도메인 인증서 + 중간 CA 인증서)
- `privkey.pem` — 개인키

파일을 채운 뒤 `nginx-proxy/conf.d/app.conf` 안의 "HTTP → HTTPS 리다이렉트"와
"HTTPS" 주석 블록 두 개의 주석을 해제하고(대신 그 위의 "HTTP" 활성 블록은
지우거나 주석 처리), `.env.prod`에 실제 도메인을 `DOMAIN=`에 채운 뒤 다시
`deploy-prod-compose.sh`(또는 `.ps1`)를 실행하면 된다.

**실제 인증서/개인키 파일은 이 디렉터리에 두더라도 git에는 절대 커밋되지 않는다**
(`.gitignore`의 `nginx-proxy/ssl/*.pem` 규칙). 이 README.md만 저장소에 남아
디렉터리 존재와 사용법을 기록한다.
