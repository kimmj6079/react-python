# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

------------------------------------------------------------------------------------------------------------------------

## 프로젝트 개요

FastAPI(백엔드) + React/TypeScript/Vite(프론트엔드) + PostgreSQL 풀스택 스터디 프로젝트. 로컬 개발 → 테스트 → Docker → Kubernetes(minikube/kind) → GitHub Actions CI/CD까지 실무 표준에 가까운 흐름을 학습하는 것이 목적이다. 예제 도메인은 간단한 `items` CRUD 하나뿐이다.

새 PC 초기 설치 절차(OS별 설치 명령 · 검증 · 트러블슈팅 · Python 버전 고정)는 [SETUP.md](./SETUP.md)에, 클라우드 VM 실배포(k3s / docker-compose)와 CI/CD 파이프라인 상세는 [DEPLOYMENT.md](./DEPLOYMENT.md)에 정리되어 있다.

------------------------------------------------------------------------------------------------------------------------

## 전체 흐름 한눈에 보기

### 로컬 (개발 · 검증)

| 단계 | 무엇을 하는가 | 실행 명령 |
|---|---|---|
| **1. 최초 셋팅** ([SETUP.md](./SETUP.md)) | 저장소 클론, 의존성 설치 | `git clone` → `uv sync` / `npm install` → `cp *.env.example *.env` |
| **2. 로컬 개발** (hot-reload) | DB → 백엔드 → 프론트 순서로 기동 | `docker compose up -d db` → `uv run uvicorn app.main:app --reload` / `npm run dev` |
| **3. docker-compose 통합 검증** | 전체를 컨테이너로 한 번에 띄워 확인 | `docker compose up --build` |
| **4. k8s 로컬 배포** (minikube/kind) | 로컬 쿠버네티스에 배포해보기 | `minikube start` → `secret.yaml` 준비 → `./scripts/deploy-local.sh` |

이후 단계(GitHub push → CI/CD → 클라우드 VM 실배포)는 [DEPLOYMENT.md](./DEPLOYMENT.md)의 "운영 (CI/CD → 클라우드 VM 배포)" 절 참고.

------------------------------------------------------------------------------------------------------------------------

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

`k8s/`, `docker-compose.prod.yml`, `nginx-proxy/` 등 배포 관련 디렉터리의 사용법은 [DEPLOYMENT.md](./DEPLOYMENT.md) 참고.

------------------------------------------------------------------------------------------------------------------------

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

------------------------------------------------------------------------------------------------------------------------

### 프론트엔드 (`frontend/`)

```bash
npm install
npm run dev        # localhost:5173, VITE_API_URL로 백엔드 주소 지정
npm run test -- --run   # Vitest 1회 실행 (watch 없이)
npm run lint        # oxlint
npm run build       # tsc -b && vite build
npm run format      # prettier --write .
```

------------------------------------------------------------------------------------------------------------------------

### 로컬 통합 (docker-compose)

```bash
docker compose up --build                         # db+backend+frontend 동시 기동
docker compose run --rm backend alembic upgrade head   # 마이그레이션은 자동 실행되지 않음, 수동 적용
docker compose down -v                             # 컨테이너+볼륨 정리
```

------------------------------------------------------------------------------------------------------------------------

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

클라우드 VM 실배포(k3s / docker-compose) 명령어는 [DEPLOYMENT.md](./DEPLOYMENT.md)의 "자주 쓰는 명령어" 절 참고.

------------------------------------------------------------------------------------------------------------------------

## 아키텍처

**요청 흐름 (로컬 dev 경로)**: 브라우저 → Vite dev server(`:5173`, CORS 필요) → FastAPI(`:8000`, `--reload`) → Postgres(`:5432`).

배포 환경(k8s Ingress 경유 / docker-compose 공유 nginx 경유)의 요청 흐름은 [DEPLOYMENT.md](./DEPLOYMENT.md)의 "아키텍처" 절 참고.

**`VITE_API_URL`은 빌드 타임 값이다.** Vite는 이 값을 정적 JS 번들에 굽는다(runtime env 아님). 그래서:
- 로컬 dev: `http://localhost:8000` (프론트가 백엔드에 절대경로로 요청, 백엔드가 CORS 허용)
- docker-compose: 마찬가지로 절대경로 + CORS
- 프로덕션 이미지(k8s와 docker-compose 배포 경로가 공유하는 동일 GHCR 이미지): 기본값이 빈 문자열(`""`)이라 프론트 코드가 이미 갖고 있는 `/api/v1/...` 상대경로가 same-origin으로 나간다. k8s는 Ingress가, docker-compose는 공유 `nginx` 서비스(`nginx-proxy/conf.d/app.conf`)가 각각 이 `/api` 프리픽스를 backend로 라우팅한다. 즉 k8s의 `configmap.yaml`에 `VITE_API_URL`을 넣어도 이미 빌드된 프론트 이미지에는 아무 효과가 없다 — 바꾸려면 이미지를 다시 빌드해야 한다.

**마이그레이션은 절대 컨테이너 시작 시 자동 실행되지 않는다.** 로컬은 `alembic upgrade head`를 직접, k8s는 `k8s/base/migrate-job.yaml`(별도 Job)을 통해 명시적으로 실행한다 — 스키마 변경을 감사 가능한 별도 단계로 유지하기 위함.

**백엔드 패키지 구조**: `app/api/routes/*`(라우터) → `app/crud/*`(DB 쿼리) → `app/models/*`(SQLAlchemy 모델) / `app/schemas/*`(Pydantic). `app/db/base.py`의 `Base`는 `app/models/__init__.py`가 전체 모델을 import해야 `Base.metadata`에 다 잡힌다(Alembic autogenerate가 이 metadata를 봄) — 새 모델 추가 시 `app/models/__init__.py`에도 등록해야 한다.

**Alembic ↔ FastAPI 설정 단일 소스**: `alembic/env.py`가 `alembic.ini`의 `sqlalchemy.url`을 무시하고 `app.core.config.settings.database_url`로 덮어쓴다. DB 연결 문자열은 `Settings`(환경변수/`.env`) 한 곳에서만 관리한다.

**uv 기본 editable install**: `uv sync`는 프로젝트 자체를 editable로 설치한다. 그래서 `docker-compose.yml`의 backend 서비스가 `./backend/app:/app/app`을 바인드 마운트하면 컨테이너 안 venv가 그 소스를 그대로 바라봐서 `--reload`가 동작한다. Dockerfile을 바꿔서 non-editable 설치로 바꾸면 이 핫리로드가 깨진다.

**Python 버전은 두 파일에 이중으로 적혀 있고, 항상 같아야 한다**: `backend/.python-version`(현재 `3.14`, uv가 로컬/CI 가상환경을 만들 때 참조)과 `backend/Dockerfile`의 `FROM python:3.14-slim`(운영 이미지, builder·final 두 스테이지 모두). 버전을 올릴 때는 반드시 **양쪽을 함께** 바꾼다 — 한쪽만 바꾸면 CI가 검증한 인터프리터와 실제 배포되는 인터프리터가 달라진다. `pyproject.toml`의 `requires-python = ">=3.12"`는 별개 개념(의존성 해석용 하한선)이라 같이 올릴 필요 없다. `ci.yml`은 `backend/`에서 `uv sync --frozen`을 돌리므로 `.python-version`을 자동으로 따라간다 — 별도 설정 불필요. 배경 설명은 [SETUP.md](./SETUP.md)의 "Python 버전은 어떻게 정해지나" 절 참고.
