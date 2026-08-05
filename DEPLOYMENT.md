# DEPLOYMENT.md

클라우드 VM 실배포(k3s / docker-compose)와 CI/CD 파이프라인 관련 내용을 정리한 문서다. 로컬 개발, 저장소 구조, 코드 아키텍처 전반은 [CLAUDE.md](./CLAUDE.md) 참고.

------------------------------------------------------------------------------------------------------------------------

## 운영 (CI/CD → 클라우드 VM 배포)

| 단계 | 무엇을 하는가 | 실행 명령 |
|---|---|---|
| **5. GitHub push (main)** | CI/CD 트리거 | `git push origin main` |
| **6. CI** (`ci.yml`) | push/PR마다 자동 검증 | lint · pytest · vitest · docker build · kind manifest check |
| **7. CD** (`cd.yml`) | main 푸시 시 이미지 배포 | GHCR에 backend/frontend 이미지 push |
| **8. 클라우드 VM 실배포** (k3s) | 최초 1회 프로비저닝 후 반복 배포 | `./scripts/provision-vm.sh`(최초) → `secret.yaml` 실값 준비 → `./scripts/deploy-prod.sh` |
| **8-B. 클라우드 VM 실배포** (docker-compose, k3s 불필요) | Docker + Compose만 설치된 서버용 대안 경로 | `.env.prod` 실값 준비 → `./scripts/deploy-prod-compose.sh` |

8단계는 k3s 기반, 8-B는 Docker/Compose만 설치된 서버를 위한 대안 경로다 — 둘 중 서버 환경에 맞는 쪽 하나만 쓰면 된다. 배포 완료 후 접속: k3s 경로는 `http://app.<VM_PUBLIC_IP>.nip.io`, docker-compose 경로는 `http://<VM_PUBLIC_IP>`. 각 단계의 상세 명령어는 아래 "자주 쓰는 명령어" 절 참고.

------------------------------------------------------------------------------------------------------------------------

## 자주 쓰는 명령어

### Kubernetes (클라우드 VM, k3s 실제 배포)

SSH로 접속 가능한 공인 IP를 가진 VM에 k3s를 직접 설치해 배포한다. TLS/도메인 없이 IP + nip.io로 시작하는 범위이며, GitHub Actions가 자동으로 원격 배포하지는 않는다(수동 스크립트).

최초 1회(VM당):
1. 클라우드 콘솔에서 방화벽/보안그룹에 22, 80 인바운드 허용.
2. GitHub → Packages에서 `react-python-backend`/`react-python-frontend` 패키지를 Public으로 전환(익명 pull 허용 — private로 유지하려면 `imagePullSecrets` 별도 구성 필요).
3. `./scripts/provision-vm.sh <user>@<VM_PUBLIC_IP>` — k3s(Traefik 비활성화) + ingress-nginx 설치. 6443(k8s API)은 외부에 열 필요 없음, kubectl은 항상 SSH 세션 안에서만 실행된다.
4. `cp k8s/base/secret.yaml.example k8s/base/secret.yaml` 후 실제 강한 값으로 수정(로컬, gitignore됨).

이후 반복 배포(코드 변경 → `main` 푸시로 CI가 GHCR에 새 `:latest` 푸시 후):
```bash
./scripts/deploy-prod.sh <user>@<VM_PUBLIC_IP>   # 또는 deploy-prod.ps1 (Windows)
```
`k8s/overlays/prod`(base 상속, ingress host/CORS만 VM IP로 patch)를 로컬에서 `kubectl kustomize`로 렌더링해 SSH 파이프로 원격 `kubectl apply -f -`에 전달한다. `:latest` + `imagePullPolicy: IfNotPresent` 조합은 레지스트리 pull 환경에서 재배포해도 새 이미지를 받아오지 않으므로, 배포 시점에 `imagePullPolicy: Always`로 치환하고 `kubectl rollout restart`로 최신 이미지 수신을 강제한다. 완료 후 `http://app.<VM_PUBLIC_IP>.nip.io`로 접속.

------------------------------------------------------------------------------------------------------------------------

### Docker Compose (클라우드 VM, k3s 없이 실제 배포)

k3s/kubernetes를 설치할 수 없거나 원하지 않는, Docker + Compose 플러그인만 있는 서버를 위한 대안 경로. k8s 경로(`scripts/deploy-prod.*`, `k8s/`)와 완전히 독립적이며 서로 영향을 주지 않는다 — 서버 환경에 맞는 쪽 하나만 고르면 된다.

이미지는 k8s 경로와 동일하게 `cd.yml`이 이미 GHCR에 푸시해둔 것을 그대로 pull만 한다(로컬/서버 어디서도 새로 빌드하지 않음). Ingress가 없으므로 그 역할은 `docker-compose.prod.yml`의 공유 `nginx` 서비스(`nginx-proxy/conf.d/`)가 대신한다 — 이 VM에 이 앱 말고 다른 앱(예: Spring Boot)도 함께 올릴 수 있도록, `frontend`/`backend`는 호스트 포트를 갖지 않고 `nginx` 서비스만 80번 포트를 잡는다(아래 아키텍처 절 참고).

최초 1회(VM당):
1. 클라우드 콘솔에서 방화벽/보안그룹에 22, 80 인바운드 허용(SSL 쓸 계획이면 443도 함께) — k3s 경로와 동일, 6443은 애초에 안 씀.
2. GHCR 패키지(`react-python-backend`/`react-python-frontend`) 접근 방식 결정 — 둘 중 하나:
   - **Public 전환** (k3s 경로와 동일): GitHub → Packages에서 두 패키지를 Public으로. 별도 인증 불필요.
   - **Private 유지**: 저장소/패키지를 private로 둔 채로 가려면, `.env.prod`의 `GHCR_USERNAME`/`GHCR_TOKEN`(read:packages 권한만 있는 PAT)을 채운다. `deploy-prod-compose.sh`/`.ps1`가 pull 직전에 VM에서 `docker login ghcr.io`를 자동 실행해준다(PAT은 SSH stdin으로만 전달되고, 원격에 저장되는 `.env.prod`는 `chmod 600`으로 보호됨).

   **`GHCR_USERNAME`/`GHCR_TOKEN` 발급 방법** (이 저장소에서는 이미 `.env.prod.example`에 주석으로도 적혀 있다):
   - `GHCR_USERNAME`: 표시 이름/이메일이 아니라 GitHub **로그인 계정명**(아이디) 그대로.
   - `GHCR_TOKEN`: GitHub Personal Access Token — 반드시 **"Tokens (classic)"**(Fine-grained 아님, GHCR 로그인은 classic PAT 기준으로만 지원됨).
     1. GitHub 우측 상단 프로필 → **Settings** → **Developer settings** → **Personal access tokens** → **Tokens (classic)**
     2. **Generate new token** → **Generate new token (classic)**
     3. Note에 용도 기입(예: `react-python-ghcr-pull`), Expiration은 무기한 대신 기간을 정해서 설정(만료되면 재발급 후 `.env.prod`에 값 갱신 필요)
     4. **Select scopes**에서 `read:packages` 딱 하나만 체크 (`write:packages`/`delete:packages`/`repo` 등은 불필요 — 최소 권한 원칙)
     5. **Generate token** 클릭 → 화면에 표시되는 `ghp_`로 시작하는 값은 이때 한 번만 보이므로(재조회 불가) 바로 복사해서 `.env.prod`의 `GHCR_TOKEN`에 붙여넣을 것
   - 채우고 나서 VM에 배포하기 전에 로컬에서 토큰이 유효한지 미리 확인하려면:
     ```bash
     echo "$GHCR_TOKEN" | docker login ghcr.io -u "$GHCR_USERNAME" --password-stdin
     ```
   - 토큰이 만료/폐기되면 `deploy-prod-compose.sh`의 `docker login` 단계에서 실패한다 — 위 1~5 절차로 재발급 후 `.env.prod`의 `GHCR_TOKEN`만 갱신하고 스크립트를 다시 실행하면 된다.
3. `cp .env.prod.example .env.prod` 후 실제 강한 값으로 수정(로컬, gitignore됨).

이후 반복 배포(코드 변경 → `main` 푸시로 CI가 GHCR에 새 `:latest` 푸시 후):
```bash
./scripts/deploy-prod-compose.sh <user>@<VM_PUBLIC_IP>   # 또는 deploy-prod-compose.ps1 (Windows)
```
`nginx-proxy/conf.d/*.conf`의 `__APP_DOMAIN__` 플레이스홀더를 실제 호스트네임으로 치환(`k8s/overlays/prod`의 `__VM_PUBLIC_IP__`와 동일한 "배포 시점 치환" 패턴 — `.env.prod`의 `DOMAIN`이 비어있으면 `app.<VM_PUBLIC_IP>.nip.io`를 자동 계산, 채워져 있으면 그 값을 그대로 사용)한 뒤, `docker-compose.prod.yml` + `.env.prod` + 렌더링된 conf를 SSH로 원격에 전송하고, 원격에서 `docker compose pull` → `up -d` → `alembic upgrade head`(멱등적이라 매번 실행해도 안전, k8s의 불변 Job 재생성 트릭이 불필요)를 순서대로 실행한다. 완료 후 `http://<위에서 계산된 호스트네임>`으로 접속(k8s 경로와 동일한 host 기반 접속 방식).

**한 VM에 다른 앱(예: Spring Boot)을 추가로 올리려면**: `docker-compose.prod.yml`에 서비스 블록 하나 추가 + `nginx-proxy/conf.d/`에 `server_name <이름>.__APP_DOMAIN__`로 라우팅하는 conf 파일 하나만 추가하면 된다. 공유 `nginx` 서비스가 유일하게 80/443번 포트를 잡고 있고 각 앱은 내부 네트워크에서만 도달 가능하므로, 기존 앱(`app.conf`, `frontend`, `backend`)은 전혀 건드릴 필요가 없다.

**SSL/실제 도메인으로 전환하려면** (지금은 HTTP + nip.io 테스트 단계, 나중에 운영 전환 시):
1. 도메인을 구매했다면 `.env.prod`의 `DOMAIN=`에 채운다(예: `DOMAIN=myapp.com`). 비워두면 계속 `app.<VM_PUBLIC_IP>.nip.io`로 동작.
2. `nginx-proxy/ssl/`에 `fullchain.pem`(인증서 체인)과 `privkey.pem`(개인키)을 배치한다(`nginx-proxy/ssl/README.md` 참고, Let's Encrypt/certbot 기준 파일명). 실제 파일은 `.gitignore`로 커밋 방지됨.
3. `nginx-proxy/conf.d/app.conf`를 연다 — 지금 활성 상태인 "HTTP" 블록을 지우거나 주석 처리하고, 파일에 이미 주석으로 준비되어 있는 "HTTP → HTTPS 리다이렉트" + "HTTPS" 두 블록의 주석을 해제한다.
4. `./scripts/deploy-prod-compose.sh <user>@<VM_PUBLIC_IP>`를 다시 실행 — `.env.prod`에 SSL 파일이 있으면 스크립트가 자동으로 함께 전송하고 `chmod 600` 처리한다.

`docker-compose.prod.yml`의 `nginx` 서비스는 이미 443 포트 노출 + `nginx-proxy/ssl` 볼륨 마운트가 되어 있으므로(인증서가 없어도 무해함), 이 전환 시 `docker-compose.prod.yml`은 건드릴 필요가 없다.

**롤백하려면**: `docker-compose.prod.yml`의 backend/frontend 이미지는 `:${IMAGE_TAG:-latest}`를 참조한다. 배포 직후 문제가 생기면 GitHub → Packages → `react-python-backend`/`react-python-frontend`에서 직전 정상 커밋의 `sha-xxxxxxx` 태그를 확인해 `.env.prod`의 `IMAGE_TAG`에 채우고 `deploy-prod-compose.sh`를 재실행하면 그 시점 이미지로 즉시 되돌아간다. 단, 이건 애플리케이션 코드만 롤백할 뿐 DB 마이그레이션까지 자동으로 되돌리지 않는다 — 롤백 대상 이후에 스키마 변경이 있었다면 별도로 `alembic downgrade`가 필요할 수 있다.

**DB 백업**: 배포할 때마다 `scripts/backup-db.sh`가 VM에 전송되고, 매일 03:00에 `pg_dump` 결과를 `react-python-deploy/backups/`에 gzip으로 저장하도록 crontab에 자동 등록/갱신된다(7일 지난 백업은 자동 삭제). 이건 VM 로컬 디스크 안에서의 최소한의 백업이라 VM 자체가 사라지는 재해까지는 대비하지 못한다 — 그 수준까지 필요하면 이 스크립트에 오브젝트 스토리지(S3 등) 업로드 단계를 추가로 붙이는 걸 고려할 것(클라우드 제공자마다 방식이 달라 기본 구현에는 포함하지 않았다).

**모니터링(선택)**: 코드 변경 없이, UptimeRobot·healthchecks.io 같은 무료 외부 서비스에 `http://<도메인>/api/v1/items`(또는 백엔드의 `/health`, `/health/ready`)를 주기적으로 호출하도록 등록해두면 컨테이너가 죽었을 때(예: `restart: unless-stopped`가 반복 재시작 중이어도) 이메일/슬랙 등으로 알림을 받을 수 있다.

------------------------------------------------------------------------------------------------------------------------

## 수동 배포 (스크립트 없이 직접 따라 하기)

`deploy-prod.sh`/`deploy-prod-compose.sh`가 내부적으로 처리하는 과정을 손으로 직접 재현하는 절이다. 학습 목적이거나 스크립트 없이 원인을 진단해야 할 때만 필요하고, 평소 배포는 위 "자주 쓰는 명령어"의 스크립트 한 줄이면 충분하다. **어떤 파일을 서버에 올리는지 → 올린 뒤 무엇을 설치하는지 → 무엇을 설정하는지** 순서로 정리한다.

### A. Docker Compose 경로 (k3s 불필요)

#### 1단계 — VM에 미리 설치되어 있어야 하는 것

| 항목 | 확인 명령 | 없으면 설치 |
|---|---|---|
| Docker Engine + Compose plugin | `docker compose version` | `curl -fsSL https://get.docker.com \| sudo sh` (공식 편의 스크립트, Ubuntu/Debian 계열 기준 Compose plugin까지 함께 설치됨) |
| sudo 없이 docker 명령 실행(선택) | `docker ps` (권한 에러 없이 실행되면 OK) | `sudo usermod -aG docker $USER` 후 SSH 재접속 |
| cron | `crontab -l` (에러 없이 실행되면 OK) | 표준 Ubuntu/Debian 이미지는 기본 포함, 없으면 `sudo apt install -y cron` |

#### 2단계 — 클라우드 콘솔에서 처리 (최초 1회)

- 방화벽/보안그룹에 인바운드 22(SSH), 80(HTTP) 허용 — SSL을 쓸 계획이면 443도 함께 (AWS는 보안 그룹, GCP는 방화벽 규칙, 오라클 클라우드는 시큐리티 리스트로 이름이 다르지만 개념은 동일)
- 해당 VM에 SSH로 접속 가능한 키 페어/계정 준비
- GHCR 패키지(`react-python-backend`/`react-python-frontend`) 접근 방식 결정 — **Public 전환**(권장, GitHub → Packages에서 설정, 별도 인증 불필요) 또는 **Private 유지**(`.env.prod`의 `GHCR_USERNAME`/`GHCR_TOKEN`에 `read:packages` 권한만 있는 PAT 채움 — 발급 방법은 위 "Docker Compose (클라우드 VM, k3s 없이 실제 배포)" 절 참고)

#### 3단계 — 로컬에서 미리 준비할 파일

- **`.env.prod`**: `cp .env.prod.example .env.prod` 후 최소한 `POSTGRES_PASSWORD`(예시 더미값 `postgres` 그대로 두면 안 됨), `APP_HOST`(VM 공인 IP) 채우기. `DOMAIN`은 비워두면 `app.<APP_HOST>.nip.io`로 자동 계산되므로 테스트 단계에서는 안 채워도 된다.
- **`nginx-proxy/conf.d/app.conf`의 `__APP_DOMAIN__` 치환**: 스크립트는 이걸 자동으로 하지만, 손으로 하려면
  ```bash
  sed "s/__APP_DOMAIN__/app.<VM_PUBLIC_IP>.nip.io/g" nginx-proxy/conf.d/app.conf > /tmp/app.conf
  ```
  처럼 렌더링해서 별도 파일로 만들어둔다(원본 `nginx-proxy/conf.d/app.conf`는 플레이스홀더 그대로 두고 git에 커밋된 상태를 유지).
- **(SSL 쓸 경우만)** `nginx-proxy/ssl/fullchain.pem`, `privkey.pem` 배치 — 없어도 HTTP 배포는 정상 동작한다.

#### 4단계 — 서버로 파일 업로드 (scp)

```bash
ssh <user>@<VM_IP> "mkdir -p react-python-deploy/nginx-proxy/conf.d react-python-deploy/nginx-proxy/ssl"

scp docker-compose.prod.yml .env.prod scripts/backup-db.sh \
    <user>@<VM_IP>:react-python-deploy/

scp /tmp/app.conf <user>@<VM_IP>:react-python-deploy/nginx-proxy/conf.d/app.conf
scp nginx-proxy/conf.d/_default.conf <user>@<VM_IP>:react-python-deploy/nginx-proxy/conf.d/

# SSL 쓸 경우만
scp nginx-proxy/ssl/*.pem <user>@<VM_IP>:react-python-deploy/nginx-proxy/ssl/
```

업로드 결과 서버의 디렉터리 구조:
```
~/react-python-deploy/
├── docker-compose.prod.yml
├── .env.prod
├── backup-db.sh
└── nginx-proxy/
    ├── conf.d/
    │   ├── app.conf        (도메인 치환 완료된 버전)
    │   └── _default.conf
    └── ssl/                 (SSL 쓸 때만: fullchain.pem, privkey.pem)
```

#### 5단계 — 서버에 SSH 접속 후 순서대로 실행

```bash
ssh <user>@<VM_IP>
cd react-python-deploy

# 권한 정리 - .env.prod에는 DB 비밀번호가 평문으로 들어있다
chmod 600 .env.prod
chmod +x backup-db.sh

# GHCR 패키지를 Private로 유지했다면만 실행 (Public 전환했다면 생략)
docker login ghcr.io -u <GHCR_USERNAME>   # 비밀번호 프롬프트에 PAT 붙여넣기

# 이미지 받기 (backend/frontend는 GHCR, db/nginx는 Docker Hub에서 pull - 로컬 빌드 없음)
docker compose -f docker-compose.prod.yml --env-file .env.prod pull

# db(헬스체크 통과 대기) → backend → frontend → nginx 순서로 기동
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d

# 스키마 마이그레이션 적용 - 최초엔 반드시 필요(안 하면 items 테이블이 없어 API가 500)
docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm backend alembic upgrade head

# 매일 03:00 DB 백업이 돌도록 cron 등록 (기존 등록분 제거 후 재등록해 중복 방지)
(crontab -l 2>/dev/null | grep -v "$(pwd)/backup-db.sh"; \
 echo "0 3 * * * cd $(pwd) && ./backup-db.sh >> backup.log 2>&1") | crontab -
```

#### 6단계 — 정상 기동 확인

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod ps      # 4개 서비스(db/backend/frontend/nginx) 모두 Up/healthy인지
curl -sf http://localhost/                                              # SPA(프론트) 응답 확인
curl -sf http://localhost/api/v1/items                                  # API 응답 확인 (빈 배열 [] 이면 정상)
docker compose -f docker-compose.prod.yml --env-file .env.prod logs -f backend   # 문제 있으면 로그 확인
```
브라우저에서는 `http://app.<VM_PUBLIC_IP>.nip.io`(또는 `.env.prod`에 채운 실제 `DOMAIN`)로 접속.

------------------------------------------------------------------------------------------------------------------------

### B. k3s 경로

#### 1단계 — VM에 미리 설치되어 있어야 하는 것

이 경로는 "미리 설치돼 있어야 하는 것"이 따로 없다 — k3s 설치 자체가 배포의 첫 단계다. 필요한 건 SSH 접속 가능한 계정뿐.

#### 2단계 — 클라우드 콘솔에서 처리 (최초 1회)

- 방화벽/보안그룹에 22(SSH), 80(HTTP) 인바운드 허용. **6443(k8s API)은 열지 않는다** — kubectl은 항상 SSH 세션 안에서만 실행되므로 외부에 노출할 필요가 없다.
- GHCR 패키지 Public 전환(또는 `imagePullSecrets` 구성)

#### 3단계 — k3s + ingress-nginx 설치 (VM 안에서 직접 실행, 최초 1회)

SSH로 접속해 아래 명령을 그대로 실행한다(`scripts/provision-vm.sh`가 원격으로 대신 실행해주는 것과 동일한 내용):

```bash
ssh <user>@<VM_IP>

# k3s 설치 - Traefik(기본 내장 ingress)은 비활성화, 이 프로젝트는 ingress-nginx를 쓰기 때문
curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="server --disable=traefik" sh -

# API 서버가 준비될 때까지 대기
until sudo k3s kubectl get nodes >/dev/null 2>&1; do sleep 2; done

# kubeconfig를 홈 디렉토리로 복사 - 이후 sudo 없이 kubectl 사용 가능
mkdir -p ~/.kube
sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown "$(id -u)":"$(id -g)" ~/.kube/config
chmod 600 ~/.kube/config

# ingress-nginx 설치
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.11.3/deploy/static/provider/cloud/deploy.yaml

# admission webhook과 controller가 준비될 때까지 대기
kubectl wait --namespace ingress-nginx --for=condition=complete job \
  --selector=app.kubernetes.io/component=admission-webhook --timeout=180s
kubectl wait --namespace ingress-nginx --for=condition=ready pod \
  --selector=app.kubernetes.io/component=controller --timeout=180s
```
Postgres가 쓸 `local-path` StorageClass는 k3s에 기본 내장돼 있어 별도 설치가 필요 없다 — `kubectl get storageclass`로 존재만 확인하면 된다.

#### 4단계 — 로컬에서 미리 준비할 파일

- **`k8s/base/secret.yaml`**: `cp k8s/base/secret.yaml.example k8s/base/secret.yaml` 후 `POSTGRES_PASSWORD`와 `DATABASE_URL` 안의 비밀번호 부분을 실제 강한 값으로 수정(더미값 `postgres:postgres@`를 그대로 두면 안 됨). 이 파일은 서버로 업로드되는 게 아니라, 아래 6단계에서 `kubectl kustomize`가 매니페스트를 렌더링할 때 로컬에서 재료로만 쓰인다(`k8s/base/kustomization.yaml`의 `resources` 목록에 포함돼 있어 렌더링 결과물 안에 자동으로 합쳐진다).

#### 5단계 — 서버로 올라가는 파일은 없다

이 경로는 서버 디스크에 남는 파일이 없다. 로컬에서 `kubectl kustomize`로 완성한 YAML 텍스트를 SSH 파이프로 그대로 흘려보내 서버의 `kubectl apply -f -`가 표준입력으로 받는다 — "파일을 두고 오는 것"이 아니라 "명령의 입력으로 텍스트를 전달하는 것"에 가깝다.

#### 6단계 — 매니페스트 적용 (로컬에서 실행, 내부적으로 SSH 사용)

```bash
# k8s/overlays/prod(=base 전체 + ingress host/CORS patch)를 렌더링하면서 플레이스홀더 치환
kubectl kustomize k8s/overlays/prod \
  | sed -e "s/__VM_PUBLIC_IP__/<VM_PUBLIC_IP>/g" \
        -e "s/imagePullPolicy: IfNotPresent/imagePullPolicy: Always/g" \
  | ssh <user>@<VM_IP> "kubectl apply -f -"

# 최신 이미지를 강제로 받도록 롤아웃 재시작 (:latest + 기존 IfNotPresent 조합은 재배포해도 새 이미지를 안 받아오므로)
ssh <user>@<VM_IP> "kubectl rollout restart deployment/backend deployment/frontend -n study-app"
ssh <user>@<VM_IP> "kubectl rollout status deployment/backend -n study-app --timeout=120s"
ssh <user>@<VM_IP> "kubectl rollout status deployment/frontend -n study-app --timeout=120s"

# 마이그레이션 Job 실행 (Job은 불변이라 재실행하려면 삭제 후 재생성해야 함)
ssh <user>@<VM_IP> "kubectl delete job/migrate -n study-app --ignore-not-found"
sed 's/imagePullPolicy: IfNotPresent/imagePullPolicy: Always/' k8s/base/migrate-job.yaml \
  | ssh <user>@<VM_IP> "kubectl apply -f -"
ssh <user>@<VM_IP> "kubectl wait --for=condition=complete job/migrate -n study-app --timeout=120s"
```

#### 7단계 — 정상 기동 확인

```bash
ssh <user>@<VM_IP> "kubectl get pods -n study-app"                      # 전부 Running인지
ssh <user>@<VM_IP> "kubectl get ingress -n study-app"                   # ADDRESS 필드가 채워졌는지
curl -sf http://app.<VM_PUBLIC_IP>.nip.io/                              # SPA(프론트) 응답 확인
curl -sf http://app.<VM_PUBLIC_IP>.nip.io/api/v1/items                  # API 응답 확인
ssh <user>@<VM_IP> "kubectl logs -n study-app deployment/backend --tail=50"   # 문제 있으면 로그 확인
```
브라우저에서는 `http://app.<VM_PUBLIC_IP>.nip.io`로 접속.

------------------------------------------------------------------------------------------------------------------------

## 아키텍처

**요청 흐름 (k8s 경로, Ingress 경유)**: 브라우저 → Ingress(dev: `app.127.0.0.1.nip.io`, 클라우드 VM 실배포: `app.<VM_PUBLIC_IP>.nip.io`) → `/` 경로는 frontend(nginx, 정적 빌드) / `/api` 경로는 backend(FastAPI) → Postgres(StatefulSet).

**요청 흐름 (docker-compose 운영 배포 경로, Ingress 없음)**: 브라우저 → 공유 `nginx` 서비스(80/443번 포트 호스트에 직접 노출, 설정은 `nginx-proxy/conf.d/`에서 마운트) → `nginx-proxy/conf.d/app.conf`가 `server_name __APP_DOMAIN__`(배포 시 `app.<VM_PUBLIC_IP>.nip.io` 또는 실제 도메인으로 치환) 기준으로 `/` 경로는 frontend 컨테이너(`:80`, 정적 빌드) / `/api` 경로는 backend 컨테이너(`:8000`)로 프록시 → Postgres. `frontend`/`backend`는 호스트 포트가 없어 이 `nginx` 서비스를 통해서만 도달 가능하다 — k8s의 Ingress 역할을 이미지 밖의 별도 컨테이너+설정 마운트로 옮겨온 것이라, 이 VM에 다른 앱을 추가할 때도 `nginx-proxy/conf.d/`에 conf 파일 하나만 더 추가하면 된다(위 "한 VM에 다른 앱을 추가로 올리려면" 참고). `frontend/nginx.conf`는 k8s 경로와 완전히 동일하게 SPA 정적 서빙만 담당한다(라우팅 로직 없음). SSL은 아직 기본 비활성 상태다(위 "SSL/실제 도메인으로 전환하려면" 참고) — `nginx-proxy/ssl/`에 인증서를 넣고 `app.conf`의 주석 블록을 해제하기 전까지는 순수 HTTP로만 서비스한다.

로컬 개발 경로의 요청 흐름과 `VITE_API_URL` 빌드 타임 동작은 [CLAUDE.md](./CLAUDE.md)의 "아키텍처" 절 참고.

------------------------------------------------------------------------------------------------------------------------

## CI/CD

- **`ci.yml`**: backend(ruff+실제 Postgres에 마이그레이션 적용+pytest) / frontend(lint+test+build) / docker-build(두 이미지 빌드 검증) / k8s-manifest-check(kind로 임시 클러스터를 띄워 `kubectl apply -k` + 마이그레이션 Job + `/health` 확인 후 클러스터 삭제 — 실제 배포가 아니라 매니페스트 정합성 검증용).
- **`cd.yml`**: `main` 푸시 시 두 이미지를 GHCR(`ghcr.io/<owner>/react-python-backend|frontend`)에 빌드+푸시. **GitHub 호스팅 러너는 개발자의 로컬 minikube나 클라우드 VM에 접근할 수 없으므로** 실제 클러스터 반영은 `scripts/deploy-local.*`(로컬) 또는 `scripts/deploy-prod.*`(클라우드 VM)를 로컬에서 수동 실행하는 것으로 마무리한다.
- 실제 시크릿은 `k8s/base/secret.yaml`(gitignore됨)에만 두고, 커밋되는 것은 `secret.yaml.example`(더미 값) 뿐이다.
- 클라우드 VM 배포 시 GHCR 패키지가 private면 새 노드의 익명 pull이 `ErrImagePull`로 실패한다 — Public 전환 필요 (자세한 내용은 위 "Kubernetes (클라우드 VM, k3s 실제 배포)" 참고).
