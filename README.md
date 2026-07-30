# react-python

FastAPI + React(TypeScript/Vite) + PostgreSQL 풀스택 스터디 프로젝트. 개발 → 테스트 → Docker → Kubernetes → CI/CD까지 실무 흐름을 학습한다. 전체 아키텍처와 명령어 레퍼런스는 [CLAUDE.md](./CLAUDE.md) 참고.

## 전체 흐름 한눈에 보기

### 로컬 (개발 · 검증)

| 단계 | 무엇을 하는가 | 실행 명령 |
|---|---|---|
| **1. 최초 셋팅** | 저장소 클론, 의존성 설치 | `git clone` → `uv sync` / `npm install` → `cp *.env.example *.env` |
| **2. 로컬 개발** (hot-reload) | DB → 백엔드 → 프론트 순서로 기동 | `docker compose up -d db` → `uv run uvicorn app.main:app --reload` / `npm run dev` |
| **3. docker-compose 통합 검증** | 전체를 컨테이너로 한 번에 띄워 확인 | `docker compose up --build` |
| **4. k8s 로컬 배포** (minikube/kind) | 로컬 쿠버네티스에 배포해보기 | `minikube start` → `secret.yaml` 준비 → `./scripts/deploy-local.sh` |

로컬 단계는 이 문서 아래 "사전 준비"~"로컬 개발 시작하기"에서 자세히 다룬다.

### 운영 (CI/CD → 클라우드 VM 배포)

| 단계 | 무엇을 하는가 | 실행 명령 |
|---|---|---|
| **5. GitHub push (main)** | CI/CD 트리거 | `git push origin main` |
| **6. CI** (`ci.yml`) | push/PR마다 자동 검증 | lint · pytest · vitest · docker build · kind manifest check |
| **7. CD** (`cd.yml`) | main 푸시 시 이미지 배포 | GHCR에 backend/frontend 이미지 push |
| **8. 클라우드 VM 실배포** (k3s) | 최초 1회 프로비저닝 후 반복 배포 | `./scripts/provision-vm.sh`(최초) → `secret.yaml` 실값 준비 → `./scripts/deploy-prod.sh` |
| **8-B. 클라우드 VM 실배포** (docker-compose, k3s 불필요) | Docker + Compose만 설치된 서버용 대안 경로 | `.env.prod` 실값 준비 → `./scripts/deploy-prod-compose.sh` |

8단계는 k3s가 설치된 서버용, 8-B는 Docker/Compose만 있는 서버용 대안 경로다 — 서버 환경에 맞는 쪽 하나만 쓰면 된다. 배포 완료 후 접속: 두 경로 모두 `http://app.<VM_PUBLIC_IP>.nip.io`. 운영 단계 상세는 [CLAUDE.md](./CLAUDE.md)의 "CI/CD", "Kubernetes (클라우드 VM, k3s 실제 배포)", "Docker Compose (클라우드 VM, k3s 없이 실제 배포)" 절 참고.

### 8단계 상세: 클라우드 VM(서버)에서 실제로 처리되는 일

`provision-vm.sh`/`deploy-prod.sh`는 전부 **로컬 컴퓨터에서 실행하는 스크립트**다 — 서버로 파일을 옮길 필요가 없다. 대신 스크립트 안에서 SSH로 서버에 접속해 명령을 원격 실행한다. "서버 쪽에서" 처리되는 일만 정리하면:

**사람이 클라우드 콘솔에서 직접 처리해야 하는 것 (스크립트로 자동화 안 됨, 최초 1회)**
- 방화벽/보안그룹에 인바운드 22(SSH), 80(HTTP) 포트 허용 (AWS는 보안 그룹, GCP는 방화벽 규칙, 오라클 클라우드는 시큐리티 리스트 등 이름은 다르지만 개념은 동일)
- 그 VM에 SSH로 접속 가능한 계정(키 페어 등록 완료) 준비 — 클라우드에서 VM을 만들 때 보통 같이 설정됨

**`provision-vm.sh` 실행 시 서버 안에서 벌어지는 일 (최초 1회)**
1. k3s(경량 쿠버네티스 배포판) 설치 — 이미 설치돼 있으면 건너뜀
2. 설치 시 Traefik(k3s 기본 내장 ingress controller)은 비활성화 — 이 프로젝트 매니페스트가 기대하는 `ingress-nginx`와 종류를 맞추기 위함
3. kubeconfig를 서버의 사용자 홈 디렉토리(`~/.kube/config`)로 복사 — 이후 SSH 세션에서 `sudo` 없이 `kubectl`을 바로 쓸 수 있게 함
4. `local-path` StorageClass(k3s 기본 제공)가 있는지 확인 — Postgres가 쓸 스토리지를 자동으로 만들어주는 부품
5. `ingress-nginx` 설치 후, controller Pod과 admission webhook이 준비될 때까지 대기

**`deploy-prod.sh` 실행 시 서버 안에서 벌어지는 일 (배포/재배포마다)**
1. 로컬에서 렌더링해 SSH로 흘려보낸 매니페스트를 서버의 `kubectl apply -f -`가 받아서 적용
2. backend/frontend Deployment가 GHCR에서 이미지를 pull해 Pod을 새로 띄움
3. `kubectl rollout restart`로 기존 Pod을 내리고 새 이미지로 다시 띄움 (최신 이미지 강제 반영)
4. migrate Job이 서버 안에서 실행되어 Postgres에 스키마 마이그레이션 적용
5. `ingress-nginx`가 80번 포트로 들어오는 실제 요청을 backend/frontend Service로 라우팅하기 시작

즉 서버에 직접 뭔가를 설치하거나 파일을 복사해두는 작업은 사실상 없고(2번 섹션의 최초 프로비저닝 제외), 이후로는 로컬에서 스크립트 한 줄 실행하는 것으로 서버 쪽 상태가 전부 갱신된다.

### 8-B단계 상세: k3s 없이 docker-compose로 배포할 때 서버 안에서 벌어지는 일

서버에 k3s/kubernetes를 설치할 수 없거나(회사 정책, 리소스 부족 등) 원하지 않는 경우를 위한 대안 경로다. `deploy-prod-compose.sh`도 8단계와 마찬가지로 **로컬 컴퓨터에서 실행하는 스크립트**이고, 서버에는 `docker-compose.prod.yml` / `.env.prod` / `nginx-proxy/conf.d/*.conf` 몇 개 파일만 전송된다 — git clone도, 소스 코드 체크아웃도 서버에서 필요 없다(애플리케이션 코드는 GHCR에 이미 빌드되어 있는 이미지 안에 들어있다).

이 경로는 이 앱 하나만 올린다고 가정하지 않는다 — 같은 VM에 다른 앱(예: Spring Boot)을 나중에 추가로 올릴 수 있도록, 호스트의 80번 포트는 `docker-compose.prod.yml`의 공유 `nginx` 서비스 하나만 잡고 각 앱(`frontend`, `backend`)은 이 서비스를 통해서만 도달 가능한 내부 전용 컨테이너로 둔다. `nginx`가 어떤 요청을 어떤 앱으로 보낼지는 `nginx-proxy/conf.d/`에 마운트된 설정 파일이 결정한다(이미지 재빌드 불필요, conf 파일만 추가/수정).

**사람이 클라우드 콘솔에서 직접 처리해야 하는 것 (최초 1회)**
- 방화벽/보안그룹에 인바운드 22(SSH), 80(HTTP) 포트 허용(SSL을 쓸 계획이면 443도 함께) — k3s 경로와 동일, 6443은 애초에 안 씀
- 그 VM에 SSH로 접속 가능한 계정 준비 (k3s 경로와 동일)
- 서버에 Docker + Docker Compose 플러그인 설치 (`docker compose version`으로 확인 가능하면 준비 끝, k3s 설치 불필요)
- GHCR 패키지(`react-python-backend`/`react-python-frontend`) 접근 방식 결정 — 둘 중 하나
  - Public으로 전환 (GitHub → Packages): 별도 인증 없이 서버가 익명으로 이미지를 pull할 수 있음
  - Private로 유지: `.env.prod`의 `GHCR_USERNAME`/`GHCR_TOKEN`(read:packages 권한만 있는 PAT)을 채워두면, 아래 스크립트가 pull 직전에 서버에서 로그인을 자동으로 처리해준다
- 도메인: 지금 당장은 필요 없다(`.env.prod`의 `DOMAIN`을 비워두면 `app.<VM_PUBLIC_IP>.nip.io`를 자동으로 씀). 나중에 실제 도메인을 구매하면 그때 `DOMAIN`에 채우면 된다.

**`deploy-prod-compose.sh` 실행 시 서버 안에서 벌어지는 일 (배포/재배포마다)**
1. 로컬에서 `.env.prod`의 `DOMAIN`(비어있으면 `app.<VM_PUBLIC_IP>.nip.io`로 자동 계산)을 계산해 `nginx-proxy/conf.d/*.conf`의 `__APP_DOMAIN__` 플레이스홀더를 치환한 뒤, `docker-compose.prod.yml` / `.env.prod` / 렌더링된 conf 파일들을 scp로 서버의 `~/react-python-deploy/`에 저장 (`.env.prod`는 비밀번호가 들어있어 `chmod 600`으로 다른 사용자가 못 읽게 처리)
2. `nginx-proxy/ssl/`에 SSL 인증서 파일이 있으면(아래 "SSL/실제 도메인으로 전환하려면" 참고) 함께 전송하고 개인키를 `chmod 600` 처리 — 아직 없으면(지금 상태) 조용히 건너뜀
3. `.env.prod`에 GHCR 토큰이 채워져 있으면 `docker login ghcr.io` 실행 (토큰은 SSH stdin으로만 전달되고 명령줄에 노출되지 않음)
4. `docker compose pull`로 GHCR에서 최신 backend/frontend 이미지를 받아옴
5. `docker compose up -d`로 db(postgres)·backend·frontend·nginx 컨테이너를 기동/갱신 — 이 중 `nginx`만 호스트 80/443번 포트를 잡고, `nginx-proxy/conf.d/app.conf`가 `server_name __APP_DOMAIN__` 기준으로 `/`는 frontend, `/api`는 backend로 프록시함(k3s 경로의 Ingress 역할을 이 공유 컨테이너가 대신함)
6. `docker compose run --rm backend alembic upgrade head`로 마이그레이션 적용 (멱등적이라 매번 실행해도 안전 — k3s 경로처럼 Job을 지웠다 다시 만드는 절차가 필요 없음)

즉 8단계와 마찬가지로 서버에 뭔가를 미리 설치해둘 필요가 없고(최초 Docker/Compose 설치 제외), 로컬에서 스크립트 한 줄로 서버 쪽 상태가 전부 갱신된다. 완료 후 접속 주소는 `http://app.<VM_PUBLIC_IP>.nip.io`다(k3s 경로와 동일하게 host 기반, 실제 도메인/SSL 전환 후에는 해당 도메인 + https).

**나중에 이 VM에 다른 앱(예: Spring Boot)을 추가로 올리려면**: `docker-compose.prod.yml`에 서비스 블록 하나 추가 + `nginx-proxy/conf.d/`에 `server_name <이름>.__APP_DOMAIN__`로 그 서비스에 프록시하는 conf 파일 하나만 추가하면 된다. 기존 `app.conf`/`frontend`/`backend`는 전혀 건드릴 필요가 없다 — 공유 `nginx` 서비스가 Host 헤더를 보고 어느 앱으로 보낼지 알아서 나눠주기 때문이다.

**SSL/실제 도메인으로 전환하려면** (지금은 HTTP + nip.io 테스트 단계):
1. 도메인 구매 후 `.env.prod`의 `DOMAIN=`에 채운다(예: `DOMAIN=myapp.com`).
2. `nginx-proxy/ssl/`에 `fullchain.pem`/`privkey.pem`을 배치한다(`nginx-proxy/ssl/README.md` 참고 — 실제 파일은 git에 커밋되지 않음).
3. `nginx-proxy/conf.d/app.conf`를 열어 지금 활성 상태인 "HTTP" 블록을 지우거나 주석 처리하고, 이미 파일 안에 준비된 "HTTP → HTTPS 리다이렉트"와 "HTTPS" 두 블록의 주석을 해제한다.
4. `deploy-prod-compose.sh`(또는 `.ps1`)를 다시 실행하면 SSL 파일과 새 설정이 함께 반영된다. `docker-compose.prod.yml`의 `nginx` 서비스는 이미 443 포트 + `nginx-proxy/ssl` 마운트가 준비돼 있어(인증서가 없어도 무해) 이 파일은 따로 안 건드려도 된다.

## 사전 준비 (초기 셋팅)

### 1) 저장소 클론

```bash
git clone https://github.com/kimmj6079/react-python.git
cd react-python
```

### 2) 필요한 프로그램 설치

어떤 방식으로 실행할지에 따라 필요한 게 다르다.

| 실행 방식 | 필요한 프로그램 |
|---|---|
| **Docker로만 실행** (`docker compose up --build`) | [Docker Desktop](https://www.docker.com/products/docker-desktop/) 하나만 있으면 됨 |
| **로컬 프로세스로 실행** (`uv run`, `npm run dev` 직접 실행, hot-reload용) | Docker Desktop(DB용) + [uv](https://docs.astral.sh/uv/getting-started/installation/)(Python 패키지 매니저, Python 인터프리터도 같이 관리해줌) + [Node.js 22+](https://nodejs.org/)(npm 포함) |
| **Kubernetes 배포까지 해볼 경우** | 위에 더해 `kubectl`, [minikube](https://minikube.sigs.k8s.io/docs/start/) 또는 kind |

설치 확인:
```bash
docker --version
docker compose version
uv --version        # 로컬 프로세스로 백엔드 돌릴 경우
node --version       # 로컬 프로세스로 프론트엔드 돌릴 경우
npm --version
```

### 3) 환경변수 파일 준비 (로컬 프로세스로 실행할 경우만 필요)

Docker로만 실행할 거면 이 단계는 건너뛰어도 된다 (`docker-compose.yml`에 필요한 값이 이미 다 들어있음). `uv run`/`npm run dev`로 직접 띄울 거면 각 폴더의 예시 파일을 복사해서 실제 설정 파일을 만들어야 한다:

```bash
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
```

`.env`는 사람/환경마다 값이 다를 수 있어서 `.gitignore`에 등록돼 있고, 저장소에는 `.env.example`(템플릿)만 커밋된다. 기본값 그대로도 아래 "로컬 개발 시작하기" 흐름과 맞게 세팅돼 있어 값을 바꾸지 않아도 동작한다.

## 로컬 개발 시작하기

전체 흐름은 "DB를 띄운다 → 백엔드가 그 DB에 연결해서 API 서버로 뜬다 → 프론트엔드가 그 API를 호출하는 화면을 띄운다" 순서다. 아래 1) → 2) → 3) 순서를 지켜야 한다 (백엔드가 DB보다 먼저 뜨면 접속에 실패하고, 프론트엔드는 백엔드가 없어도 켜지긴 하지만 화면에 데이터가 뜨지 않는다).

### 1) DB만 먼저 띄우기

```bash
docker compose up -d db
```

- `docker compose`는 `docker-compose.yml`에 정의된 서비스(db/backend/frontend)를 관리하는 명령이다. 여기서는 `db` 서비스 하나만 지정했으므로 PostgreSQL 컨테이너만 뜬다.
- `-d`(detach)는 "백그라운드로 띄우고 터미널은 바로 돌려달라"는 뜻이다. 안 붙이면 컨테이너 로그가 터미널을 계속 점유한다.
- 최초 실행 시 `postgres:16-alpine` 이미지를 도커 허브에서 내려받기 때문에 몇 초~몇십 초 걸릴 수 있다. 이후에는 캐시돼서 빠르다.
- 데이터는 `docker-compose.yml`에 정의된 볼륨(`db-data`)에 저장되므로, 컨테이너를 껐다 켜도 데이터는 유지된다. (완전히 지우려면 뒤에서 나오는 `docker compose down -v`)

### 2) 백엔드 (터미널 1)

```bash
cd backend
uv sync                                   # 최초 1회 (.venv 자동 생성)
cp .env.example .env                      # 최초 1회, 필요 시 값 수정
uv run alembic upgrade head               # 최초 1회 / 마이그레이션 추가 시
uv run uvicorn app.main:app --reload      # http://localhost:8000
```

- `uv sync`: `pyproject.toml`/`uv.lock`을 읽어서 `backend/.venv`라는 가상환경을 만들고 FastAPI, SQLAlchemy 등 의존성을 그 안에 설치한다. 한 번 만들어두면 이후엔 다시 실행할 필요 없고, 의존성이 추가될 때만 다시 실행하면 된다.
- `cp .env.example .env`: `.env.example`은 "이런 환경변수가 필요하다"는 템플릿이고, `.env`는 실제로 앱이 읽는 파일이다. `.env`는 `.gitignore`에 등록돼 있어 깃에 올라가지 않는다(사람마다 DB 접속정보가 다를 수 있으므로). 지금은 기본값(`postgresql+psycopg://postgres:postgres@localhost:5432/app`)이 `docker compose up -d db`로 띄운 DB와 그대로 맞으므로 값을 안 바꿔도 동작한다.
- `uv run alembic upgrade head`: Alembic은 DB 스키마 버전 관리 도구다(코드로 치면 git과 비슷하게, DB 테이블 구조 변경 이력을 `backend/alembic/versions/`에 순서대로 기록해둔다). "head"는 "가장 최신 버전까지 적용해라"는 뜻이다. 이 명령을 실행해야 `items` 테이블이 실제로 DB에 생성된다 — 안 하면 백엔드는 뜨지만 API 호출 시 "테이블이 없다"는 에러가 난다.
- `uv run uvicorn app.main:app --reload`: `uvicorn`은 FastAPI 앱을 실제로 구동하는 ASGI 서버다. `app.main:app`은 "`app/main.py` 파일 안의 `app`이라는 변수(FastAPI 인스턴스)를 실행해라"는 의미. `--reload`는 코드를 수정하고 저장할 때마다 서버가 자동으로 재시작되게 해주는 개발용 옵션이다(운영 배포 시에는 끈다). 뜨고 나면 `http://localhost:8000/health`로 정상 기동을 확인할 수 있고, `http://localhost:8000/docs`에서 자동 생성된 Swagger API 문서도 볼 수 있다.

### 3) 프론트엔드 (터미널 2)

```bash
cd frontend
npm install                               # 최초 1회
cp .env.example .env                      # 최초 1회
npm run dev                               # http://localhost:5173
```

- `npm install`: `package.json`에 적힌 React, Vite 등의 의존성을 `node_modules/`에 설치한다. 백엔드의 `uv sync`와 같은 역할이라고 보면 된다.
- `cp .env.example .env`: 프론트엔드의 `.env`에는 `VITE_API_URL`(백엔드 주소)이 들어있다. 기본값이 `http://localhost:8000`이라 방금 띄운 백엔드를 그대로 가리킨다.
- `npm run dev`: Vite 개발 서버를 띄운다. 파일을 저장하면 브라우저 새로고침 없이 화면 일부만 즉시 갱신되는 HMR(Hot Module Replacement)이 지원된다. 콘솔에 뜨는 `http://localhost:5173` 주소로 접속하면 된다.

브라우저에서 `http://localhost:5173`을 열면 프론트엔드가 `http://localhost:8000`의 백엔드 API를 호출한다. 이때 백엔드가 `http://localhost:5173`을 CORS 허용 목록(`backend/app/core/config.py`의 `backend_cors_origins`)에 넣어뒀기 때문에 브라우저가 이 요청을 차단하지 않는다 — 만약 프론트 포트를 바꾸면 이 값도 같이 바꿔야 한다.

### 한 번에 띄우기 (docker-compose)

위 과정을 개별 실행하는 대신 전체를 컨테이너로 띄울 수도 있다:

```bash
docker compose up --build
docker compose run --rm backend alembic upgrade head   # 최초 1회 / 마이그레이션 추가 시
```

- 프론트: http://localhost:5173
- 백엔드: http://localhost:8000

### 백그라운드로 한 번에 띄우기

**컨테이너로 (가장 간단, 이미 백그라운드)**

`docker compose up -d`의 `-d`가 곧 백그라운드 실행이라 별도 처리가 필요 없다:

```bash
docker compose up -d --build
docker compose run --rm backend alembic upgrade head   # 최초 1회 / 마이그레이션 추가 시
```

- 로그 보기: `docker compose logs -f backend` (frontend/db도 동일)
- 상태 확인: `docker compose ps`

**로컬 프로세스로 (uv/npm, 터미널을 점유하지 않고 실행)**

DB는 컨테이너로 띄우고, 백엔드/프론트엔드는 hot-reload가 되는 로컬 프로세스로 백그라운드 실행하고 싶을 때:

*PowerShell*
```powershell
docker compose up -d db

Start-Process pwsh -WindowStyle Hidden -ArgumentList `
  "-NoExit", "-Command", "cd backend; uv run alembic upgrade head; uv run uvicorn app.main:app --reload *> ..\backend.log 2>&1"
Start-Process pwsh -WindowStyle Hidden -ArgumentList `
  "-NoExit", "-Command", "cd frontend; npm run dev *> ..\frontend.log 2>&1"
```
- 로그 보기: `Get-Content backend.log -Wait` / `Get-Content frontend.log -Wait`
- 종료:
  ```powershell
  Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "uvicorn|vite" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
  ```

*Git Bash*
```bash
docker compose up -d db

(cd backend && uv run alembic upgrade head && nohup uv run uvicorn app.main:app --reload > ../backend.log 2>&1 &)
(cd frontend && nohup npm run dev > ../frontend.log 2>&1 &)
```
- 로그 보기: `tail -f backend.log` / `tail -f frontend.log`
- 종료: `lsof -ti:8000 -sTCP:LISTEN | xargs -r kill` / `lsof -ti:5173 -sTCP:LISTEN | xargs -r kill`

### Visual Studio 사용 시

Visual Studio는 이 스택(FastAPI/uv, Vite/npm)에 전용 프로젝트 템플릿이나 실행 버튼을 제공하지 않는다. 내장 터미널로 위 명령어들을 그대로 실행하면 된다.

1. 메뉴 `보기(View) > 터미널(Terminal)` 또는 `` Ctrl+` `` 로 터미널 창을 연다 (기본 PowerShell).
2. 터미널 창 안에서 탭을 3개 추가로 열어(터미널 창의 `+` 버튼) 아래 순서대로 각각 실행한다. 세 프로세스 모두 명령이 끝나지 않고 계속 떠 있는 상태(서버)라서, 탭을 분리해야 동시에 돌릴 수 있다.

**탭 1 — DB**
```powershell
docker compose up -d db
```
- PostgreSQL 컨테이너만 백그라운드로 띄운다. `-d` 덕분에 이 탭은 명령을 치자마자 프롬프트로 돌아오고, 이후 다른 명령을 계속 쳐도 된다(컨테이너는 탭과 무관하게 백그라운드에서 계속 실행됨).
- 반드시 탭 2(백엔드)보다 먼저 실행해야 한다. DB가 없는 상태에서 백엔드를 띄우면 연결 실패로 죽는다.

**탭 2 — 백엔드**
```powershell
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```
- `uv sync`: `backend/.venv`에 Python 가상환경을 만들고 의존성을 설치한다. 최초 1회만 필요하고, 이미 설치돼 있으면 순식간에 끝난다.
- `uv run alembic upgrade head`: DB에 `items` 테이블을 생성하는 마이그레이션을 적용한다. 최초 1회, 그리고 이후 스키마가 바뀔 때마다 실행하면 된다.
- `uv run uvicorn app.main:app --reload`: 마지막 줄이 실제 서버를 띄우는 명령이라 이 탭은 여기서 "멈춰있는 것처럼" 보이지만 정상이다(서버가 요청을 기다리는 중). 코드 저장 시 `--reload` 덕분에 자동 재시작된다. 이 탭을 다른 명령을 치는 용도로 쓰려면 안 되고, 서버를 끄려면 `Ctrl+C`.
- 정상 기동 확인: 브라우저나 새 탭에서 `curl http://localhost:8000/health`, API 문서는 `http://localhost:8000/docs`.

**탭 3 — 프론트엔드**
```powershell
cd frontend
npm install
npm run dev
```
- `npm install`: `frontend/node_modules`에 React/Vite 의존성을 설치한다(최초 1회, 이후엔 생략 가능).
- `npm run dev`: Vite 개발 서버를 띄운다. 이 탭도 탭 2와 마찬가지로 서버가 떠서 대기 중인 상태로 남는다. 콘솔에 나오는 `Local: http://localhost:5173/` 주소를 클릭하거나 브라우저에 직접 입력한다.

이후 브라우저에서 `http://localhost:5173` 접속하면 화면이 뜨고, 백엔드 API(`/api/v1/items`)를 호출해 데이터를 가져온다.

**중지 명령어**

종료 순서는 상관없다 (DB를 먼저 꺼도 이미 떠 있는 백엔드/프론트엔드가 즉시 죽지는 않고, 다음 요청부터 실패한다).

- **탭 3(프론트엔드)**: 해당 탭에 커서를 두고 `Ctrl+C`. Vite 개발 서버가 종료되고 프롬프트로 돌아온다.
- **탭 2(백엔드)**: 마찬가지로 `Ctrl+C`. `--reload`로 띄운 uvicorn은 가끔 자식 프로세스가 남는 경우가 있는데, 안 꺼지면 `Ctrl+C`를 한 번 더 누른다.
- **탭 1(DB)**: 컨테이너는 탭을 그냥 닫아도 안 꺼진다(백그라운드로 떴기 때문). 아무 탭에서나 아래 명령으로 꺼야 한다.
  ```powershell
  docker compose stop db      # 컨테이너만 정지 (데이터는 볼륨에 그대로 남음, 다시 시작은 docker compose up -d db)
  # 또는
  docker compose down -v      # 컨테이너 + 볼륨(DB 데이터)까지 완전히 삭제
  ```
  - `stop`은 "잠깐 끄기"(다음에 다시 켜면 데이터 그대로), `down -v`는 "완전히 지우기"(다음에 켜면 마이그레이션부터 다시 실행해야 함) — 평소엔 `stop`, 프로젝트를 완전히 정리하고 싶을 때만 `down -v`를 쓰면 된다.
- 혹시 탭을 실수로 닫아서 `Ctrl+C`를 못 눌렀다면(프로세스가 백그라운드에 남은 경우), 포트로 찾아서 강제 종료:
  ```powershell
  Get-NetTCPConnection -LocalPort 8000 | Select-Object -ExpandProperty OwningProcess | ForEach-Object { Stop-Process -Id $_ -Force }   # 백엔드(8000)
  Get-NetTCPConnection -LocalPort 5173 | Select-Object -ExpandProperty OwningProcess | ForEach-Object { Stop-Process -Id $_ -Force }   # 프론트엔드(5173)
  ```

### 정리

```bash
docker compose down -v
```

## 더 알아보기

- 테스트/린트/빌드, Docker 이미지 빌드, Kubernetes 배포, CI/CD 구조는 [CLAUDE.md](./CLAUDE.md)에 정리되어 있다.
