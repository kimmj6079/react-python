# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 프로젝트 개요

FastAPI(백엔드) + React/TypeScript/Vite(프론트엔드) + PostgreSQL 풀스택 스터디 프로젝트. 로컬 개발 → 테스트 → Docker → Kubernetes(minikube/kind) → GitHub Actions CI/CD까지 실무 표준에 가까운 흐름을 학습하는 것이 목적이다. 예제 도메인은 간단한 `items` CRUD 하나뿐이다.

## 전체 흐름 한눈에 보기

### 로컬 (개발 · 검증)

| 단계 | 무엇을 하는가 | 실행 명령 |
|---|---|---|
| **1. 최초 셋팅** | 저장소 클론, 의존성 설치 | `git clone` → `uv sync` / `npm install` → `cp *.env.example *.env` |
| **2. 로컬 개발** (hot-reload) | DB → 백엔드 → 프론트 순서로 기동 | `docker compose up -d db` → `uv run uvicorn app.main:app --reload` / `npm run dev` |
| **3. docker-compose 통합 검증** | 전체를 컨테이너로 한 번에 띄워 확인 | `docker compose up --build` |
| **4. k8s 로컬 배포** (minikube/kind) | 로컬 쿠버네티스에 배포해보기 | `minikube start` → `secret.yaml` 준비 → `./scripts/deploy-local.sh` |

### 운영 (CI/CD → 클라우드 VM 배포)

| 단계 | 무엇을 하는가 | 실행 명령 |
|---|---|---|
| **5. GitHub push (main)** | CI/CD 트리거 | `git push origin main` |
| **6. CI** (`ci.yml`) | push/PR마다 자동 검증 | lint · pytest · vitest · docker build · kind manifest check |
| **7. CD** (`cd.yml`) | main 푸시 시 이미지 배포 | GHCR에 backend/frontend 이미지 push |
| **8. 클라우드 VM 실배포** (k3s) | 최초 1회 프로비저닝 후 반복 배포 | `./scripts/provision-vm.sh`(최초) → `secret.yaml` 실값 준비 → `./scripts/deploy-prod.sh` |
| **8-B. 클라우드 VM 실배포** (docker-compose, k3s 불필요) | Docker + Compose만 설치된 서버용 대안 경로 | `.env.prod` 실값 준비 → `./scripts/deploy-prod-compose.sh` |

8단계는 k3s 기반, 8-B는 Docker/Compose만 설치된 서버를 위한 대안 경로다 — 둘 중 서버 환경에 맞는 쪽 하나만 쓰면 된다. 배포 완료 후 접속: k3s 경로는 `http://app.<VM_PUBLIC_IP>.nip.io`, docker-compose 경로는 `http://<VM_PUBLIC_IP>`. 각 단계의 상세 명령어는 아래 "자주 쓰는 명령어" 절 참고.

## 저장소 구조

```
backend/    FastAPI 앱 (app/), Alembic 마이그레이션, pytest
frontend/   React + TS + Vite, Vitest
k8s/        Kustomize 매니페스트 (base/ + overlays/dev, prod/)
.github/workflows/  ci.yml, cd.yml
scripts/    minikube 배포(deploy-local) + 클라우드 VM 배포(provision-vm, deploy-prod, deploy-prod-compose) 스크립트 (.sh / .ps1)
            + backup-db.sh (docker-compose 운영 배포 시 VM에 전송되어 cron으로 매일 실행되는 DB 백업)
docker-compose.yml       로컬 통합 개발 환경
docker-compose.prod.yml  운영 배포용 (k3s 없이 Docker/Compose만 있는 서버, GHCR 이미지 pull-only)
nginx-proxy/conf.d/      docker-compose 운영 배포의 공유 리버스 프록시 설정 (앱별 server 블록, 이미지 재빌드 없이 마운트)
nginx-proxy/ssl/         SSL 인증서/개인키 배치 위치 (실제 파일은 gitignore, README.md만 커밋됨)
```

## 자주 쓰는 명령어

### 백엔드 (`backend/`, 패키지 매니저는 uv)

우선 DB가 떠 있어야 한다: `docker compose up -d db` (프로젝트 루트에서).

```bash
uv sync                                          # 의존성 설치 (.venv 자동 생성)
uv run alembic upgrade head                      # 최초 1회 / 마이그레이션 추가 시
uv run uvicorn app.main:app --reload             # 개발 서버 (localhost:8000)
uv run pytest -v                                 # 전체 테스트
uv run pytest tests/test_items.py::test_create_item -v   # 단일 테스트
uv run ruff check .                              # 린트
uv run alembic revision --autogenerate -m "msg"  # 마이그레이션 생성 (DB 연결 필요)
uv run alembic upgrade head                      # 마이그레이션 적용
uv run alembic check                             # 모델과 마이그레이션 정합성 확인
```

pytest는 SQLite 인메모리 DB로 `get_db`를 오버라이드해서 돈다(`tests/conftest.py`). 실제 Postgres 연동 확인은 `docker compose up -d db` 등으로 별도로 한다.

### 프론트엔드 (`frontend/`)

```bash
npm install
npm run dev        # localhost:5173, VITE_API_URL로 백엔드 주소 지정
npm run test -- --run   # Vitest 1회 실행 (watch 없이)
npm run lint        # oxlint
npm run build       # tsc -b && vite build
npm run format      # prettier --write .
```

### 로컬 통합 (docker-compose)

```bash
docker compose up --build                         # db+backend+frontend 동시 기동
docker compose run --rm backend alembic upgrade head   # 마이그레이션은 자동 실행되지 않음, 수동 적용
docker compose down -v                             # 컨테이너+볼륨 정리
```

### Kubernetes (로컬 minikube/kind 기준)

```bash
minikube start
minikube addons enable ingress
cp k8s/base/secret.yaml.example k8s/base/secret.yaml   # 최초 1회, 실제 값으로 수정
./scripts/deploy-local.sh      # 또는 deploy-local.ps1 (Windows)
```

`deploy-local.*` 스크립트가 이미지 빌드 → `minikube image load` → `kubectl apply -k k8s/overlays/dev` → 마이그레이션 Job 실행까지 처리한다. Ingress 활성화 시 `http://app.127.0.0.1.nip.io`로 접속.

마이그레이션 Job은 불변(immutable)이라 재실행하려면:
```bash
kubectl delete job/migrate -n study-app --ignore-not-found
kubectl apply -f k8s/base/migrate-job.yaml
```

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

### Docker Compose (클라우드 VM, k3s 없이 실제 배포)

k3s/kubernetes를 설치할 수 없거나 원하지 않는, Docker + Compose 플러그인만 있는 서버를 위한 대안 경로. k8s 경로(`scripts/deploy-prod.*`, `k8s/`)와 완전히 독립적이며 서로 영향을 주지 않는다 — 서버 환경에 맞는 쪽 하나만 고르면 된다.

이미지는 k8s 경로와 동일하게 `cd.yml`이 이미 GHCR에 푸시해둔 것을 그대로 pull만 한다(로컬/서버 어디서도 새로 빌드하지 않음). Ingress가 없으므로 그 역할은 `docker-compose.prod.yml`의 공유 `nginx` 서비스(`nginx-proxy/conf.d/`)가 대신한다 — 이 VM에 이 앱 말고 다른 앱(예: Spring Boot)도 함께 올릴 수 있도록, `frontend`/`backend`는 호스트 포트를 갖지 않고 `nginx` 서비스만 80번 포트를 잡는다(아래 아키텍처 절 참고).

최초 1회(VM당):
1. 클라우드 콘솔에서 방화벽/보안그룹에 22, 80 인바운드 허용(SSL 쓸 계획이면 443도 함께) — k3s 경로와 동일, 6443은 애초에 안 씀.
2. GHCR 패키지(`react-python-backend`/`react-python-frontend`) 접근 방식 결정 — 둘 중 하나:
   - **Public 전환** (k3s 경로와 동일): GitHub → Packages에서 두 패키지를 Public으로. 별도 인증 불필요.
   - **Private 유지**: 저장소/패키지를 private로 둔 채로 가려면, `.env.prod`의 `GHCR_USERNAME`/`GHCR_TOKEN`(read:packages 권한만 있는 PAT)을 채운다. `deploy-prod-compose.sh`/`.ps1`가 pull 직전에 VM에서 `docker login ghcr.io`를 자동 실행해준다(PAT은 SSH stdin으로만 전달되고, 원격에 저장되는 `.env.prod`는 `chmod 600`으로 보호됨).
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

## 아키텍처

**요청 흐름 (k8s 경로, Ingress 경유)**: 브라우저 → Ingress(dev: `app.127.0.0.1.nip.io`, 클라우드 VM 실배포: `app.<VM_PUBLIC_IP>.nip.io`) → `/` 경로는 frontend(nginx, 정적 빌드) / `/api` 경로는 backend(FastAPI) → Postgres(StatefulSet).

**요청 흐름 (docker-compose 운영 배포 경로, Ingress 없음)**: 브라우저 → 공유 `nginx` 서비스(80/443번 포트 호스트에 직접 노출, 설정은 `nginx-proxy/conf.d/`에서 마운트) → `nginx-proxy/conf.d/app.conf`가 `server_name __APP_DOMAIN__`(배포 시 `app.<VM_PUBLIC_IP>.nip.io` 또는 실제 도메인으로 치환) 기준으로 `/` 경로는 frontend 컨테이너(`:80`, 정적 빌드) / `/api` 경로는 backend 컨테이너(`:8000`)로 프록시 → Postgres. `frontend`/`backend`는 호스트 포트가 없어 이 `nginx` 서비스를 통해서만 도달 가능하다 — k8s의 Ingress 역할을 이미지 밖의 별도 컨테이너+설정 마운트로 옮겨온 것이라, 이 VM에 다른 앱을 추가할 때도 `nginx-proxy/conf.d/`에 conf 파일 하나만 더 추가하면 된다(위 "한 VM에 다른 앱을 추가로 올리려면" 참고). `frontend/nginx.conf`는 k8s 경로와 완전히 동일하게 SPA 정적 서빙만 담당한다(라우팅 로직 없음). SSL은 아직 기본 비활성 상태다(위 "SSL/실제 도메인으로 전환하려면" 참고) — `nginx-proxy/ssl/`에 인증서를 넣고 `app.conf`의 주석 블록을 해제하기 전까지는 순수 HTTP로만 서비스한다.

**요청 흐름 (로컬 dev 경로)**: 브라우저 → Vite dev server(`:5173`, CORS 필요) → FastAPI(`:8000`, `--reload`) → Postgres(`:5432`).

**`VITE_API_URL`은 빌드 타임 값이다.** Vite는 이 값을 정적 JS 번들에 굽는다(runtime env 아님). 그래서:
- 로컬 dev: `http://localhost:8000` (프론트가 백엔드에 절대경로로 요청, 백엔드가 CORS 허용)
- docker-compose: 마찬가지로 절대경로 + CORS
- 프로덕션 이미지(k8s와 docker-compose 배포 경로가 공유하는 동일 GHCR 이미지): 기본값이 빈 문자열(`""`)이라 프론트 코드가 이미 갖고 있는 `/api/v1/...` 상대경로가 same-origin으로 나간다. k8s는 Ingress가, docker-compose는 공유 `nginx` 서비스(`nginx-proxy/conf.d/app.conf`)가 각각 이 `/api` 프리픽스를 backend로 라우팅한다. 즉 k8s의 `configmap.yaml`에 `VITE_API_URL`을 넣어도 이미 빌드된 프론트 이미지에는 아무 효과가 없다 — 바꾸려면 이미지를 다시 빌드해야 한다.

**마이그레이션은 절대 컨테이너 시작 시 자동 실행되지 않는다.** 로컬은 `alembic upgrade head`를 직접, k8s는 `k8s/base/migrate-job.yaml`(별도 Job)을 통해 명시적으로 실행한다 — 스키마 변경을 감사 가능한 별도 단계로 유지하기 위함.

**백엔드 패키지 구조**: `app/api/routes/*`(라우터) → `app/crud/*`(DB 쿼리) → `app/models/*`(SQLAlchemy 모델) / `app/schemas/*`(Pydantic). `app/db/base.py`의 `Base`는 `app/models/__init__.py`가 전체 모델을 import해야 `Base.metadata`에 다 잡힌다(Alembic autogenerate가 이 metadata를 봄) — 새 모델 추가 시 `app/models/__init__.py`에도 등록해야 한다.

**Alembic ↔ FastAPI 설정 단일 소스**: `alembic/env.py`가 `alembic.ini`의 `sqlalchemy.url`을 무시하고 `app.core.config.settings.database_url`로 덮어쓴다. DB 연결 문자열은 `Settings`(환경변수/`.env`) 한 곳에서만 관리한다.

**uv 기본 editable install**: `uv sync`는 프로젝트 자체를 editable로 설치한다. 그래서 `docker-compose.yml`의 backend 서비스가 `./backend/app:/app/app`을 바인드 마운트하면 컨테이너 안 venv가 그 소스를 그대로 바라봐서 `--reload`가 동작한다. Dockerfile을 바꿔서 non-editable 설치로 바꾸면 이 핫리로드가 깨진다.

## CI/CD

- **`ci.yml`**: backend(ruff+실제 Postgres에 마이그레이션 적용+pytest) / frontend(lint+test+build) / docker-build(두 이미지 빌드 검증) / k8s-manifest-check(kind로 임시 클러스터를 띄워 `kubectl apply -k` + 마이그레이션 Job + `/health` 확인 후 클러스터 삭제 — 실제 배포가 아니라 매니페스트 정합성 검증용).
- **`cd.yml`**: `main` 푸시 시 두 이미지를 GHCR(`ghcr.io/<owner>/react-python-backend|frontend`)에 빌드+푸시. **GitHub 호스팅 러너는 개발자의 로컬 minikube나 클라우드 VM에 접근할 수 없으므로** 실제 클러스터 반영은 `scripts/deploy-local.*`(로컬) 또는 `scripts/deploy-prod.*`(클라우드 VM)를 로컬에서 수동 실행하는 것으로 마무리한다.
- 실제 시크릿은 `k8s/base/secret.yaml`(gitignore됨)에만 두고, 커밋되는 것은 `secret.yaml.example`(더미 값) 뿐이다.
- 클라우드 VM 배포 시 GHCR 패키지가 private면 새 노드의 익명 pull이 `ErrImagePull`로 실패한다 — Public 전환 필요 (자세한 내용은 위 "Kubernetes (클라우드 VM, k3s 실제 배포)" 참고).
