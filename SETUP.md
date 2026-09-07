# SETUP.md — 초기 설치 가이드

새 PC(또는 새로 클론한 저장소)에서 이 프로젝트를 **처음 한 번** 돌아가게 만드는 절차를 다룬다. 아무것도 깔려 있지 않은 상태를 가정한다.

**Python은 따로 설치하지 않는다.** 패키지 매니저인 `uv`가 프로젝트에 필요한 Python 인터프리터까지 알아서 내려받아 관리한다 (자세한 이유는 아래 [5. Python 버전은 어떻게 정해지나](#5-python-버전은-어떻게-정해지나) 참고).

설치가 끝난 뒤의 일상적인 실행/중지 절차는 [README.md](./README.md)의 "로컬 개발 시작하기", 배포는 [DEPLOYMENT.md](./DEPLOYMENT.md)를 참고한다.

------------------------------------------------------------------------------------------------------------------------

## 0. 어떤 경로로 갈지 먼저 고른다

목적에 따라 설치할 것이 달라진다. **둘 중 하나만** 하면 된다.

| | **경로 A — 실행만** | **경로 B — 개발** |
|---|---|---|
| 목적 | 앱이 어떻게 생겼는지 확인 | 코드를 고치며 hot-reload로 개발 |
| Git | 필요 | 필요 |
| Docker Desktop | 필요 | 필요 (DB 용도) |
| uv | 불필요 | **필요** |
| Python | **불필요** | **불필요** (uv가 설치해 줌) |
| Node.js | 불필요 | 필요 |
| 소요 시간 | 약 10분 (대부분 이미지 빌드 대기) | 약 15분 |
| 코드 수정 반영 | 컨테이너 재빌드 필요 | 저장 즉시 반영 |

잘 모르겠으면 **경로 B**를 고르면 된다. 경로 B를 마친 상태에서도 경로 A의 `docker compose up --build`는 그대로 쓸 수 있다.

------------------------------------------------------------------------------------------------------------------------

## 1. 공통 — 저장소 클론

Git이 없다면 먼저 설치한다.

```powershell
# Windows
winget install -e --id Git.Git
```
```bash
# macOS
brew install git
# Linux (Debian/Ubuntu)
sudo apt install -y git
```

```bash
git clone https://github.com/kimmj6079/react-python.git
cd react-python
```

이후의 모든 명령은 **저장소 루트(`react-python/`)에서 시작**하는 것으로 가정한다.

------------------------------------------------------------------------------------------------------------------------

## 2. 경로 A — Docker만 설치해서 실행

Python도 Node.js도 설치하지 않는다. 모든 것이 컨테이너 안에서 돈다.

### A-1) Docker Desktop 설치

```powershell
# Windows (설치 후 Docker Desktop을 한 번 실행해 두어야 한다. WSL2 활성화 안내가 나오면 따른다)
winget install -e --id Docker.DockerDesktop
```
```bash
# macOS
brew install --cask docker
# Linux: Docker Engine + Compose 플러그인 설치 (배포판 문서 참고)
```

확인:
```bash
docker --version
docker compose version
docker ps            # 데몬이 떠 있어야 에러 없이 빈 목록이 나온다
```

> `docker ps`에서 `Cannot connect to the Docker daemon` 이 나오면 Docker Desktop이 실행 중이 아니다. 앱을 켜고 고래 아이콘이 "Running" 상태가 될 때까지 기다린다.

### A-2) 전체 기동

```bash
docker compose up --build
```

- `db`(PostgreSQL) → `backend`(FastAPI) → `frontend`(Vite) 세 컨테이너가 순서대로 뜬다.
- 최초 빌드는 이미지 다운로드 + 의존성 설치 때문에 **5~10분** 걸린다. 두 번째부터는 캐시 덕분에 수십 초.
- 이 터미널은 로그를 계속 출력하며 점유된다. 백그라운드로 띄우려면 `docker compose up -d --build`.

### A-3) 마이그레이션 적용 (필수)

**새 터미널**을 열어서:

```bash
docker compose run --rm backend alembic upgrade head
```

이 프로젝트는 컨테이너가 뜰 때 마이그레이션을 자동 실행하지 **않는다**. 스키마 변경을 명시적이고 감사 가능한 단계로 남기기 위한 의도적인 설계다. 이 명령을 건너뛰면 화면은 뜨지만 API 호출 시 `relation "items" does not exist` 에러가 난다.

### A-4) 접속 확인

| 대상 | 주소 |
|---|---|
| 프론트엔드 | http://localhost:5173 |
| 백엔드 헬스체크 | http://localhost:8000/health |
| API 문서 (Swagger) | http://localhost:8000/docs |

여기까지 됐으면 경로 A는 끝이다. [4. 설치 검증 체크리스트](#4-설치-검증-체크리스트)로 넘어간다.

------------------------------------------------------------------------------------------------------------------------

## 3. 경로 B — 로컬 개발 환경 구성

DB는 컨테이너로 띄우고, 백엔드/프론트엔드는 로컬 프로세스로 직접 실행해 hot-reload를 쓰는 구성이다.

### B-1) uv 설치 — Python은 여기에 딸려 온다

```powershell
# Windows
winget install -e --id astral-sh.uv
# 또는 (winget이 없을 때)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```
```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
# 또는 macOS: brew install uv
```

**설치 후 터미널을 새로 열고** 확인한다 (PATH 변경이 기존 터미널에는 반영되지 않는다):

```bash
uv --version
```

### B-2) Node.js LTS 설치 — 프론트엔드용

```powershell
# Windows
winget install -e --id OpenJS.NodeJS.LTS
```
```bash
# macOS
brew install node
# Linux: nvm 또는 NodeSource 저장소 사용
```

새 터미널에서 확인 (CI가 Node 22를 쓰므로 **22 이상**을 권장):

```bash
node --version
npm --version
```

### B-3) Docker Desktop 설치 — DB용

[A-1](#a-1-docker-desktop-설치)과 동일하다. PostgreSQL을 직접 설치해서 쓰고 싶다면 Docker 없이도 되지만, 그 경우 `backend/.env`의 `DATABASE_URL`을 본인 DB에 맞게 고쳐야 한다.

### B-4) 환경변수 파일 준비

`.env`는 `.gitignore` 대상이라 클론하면 없다. 템플릿을 복사한다.

```powershell
# PowerShell
copy backend\.env.example backend\.env
copy frontend\.env.example frontend\.env
```
```bash
# Git Bash / macOS / Linux
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
```

기본값이 아래 절차와 그대로 맞으므로 **값을 수정할 필요는 없다**:

```ini
# backend/.env
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/app
BACKEND_CORS_ORIGINS=http://localhost:5173

# frontend/.env
VITE_API_URL=http://localhost:8000
```

> 참고: 코드에 동일한 기본값이 이미 들어 있어([`app/core/config.py`](backend/app/core/config.py), [`src/api/client.ts`](frontend/src/api/client.ts)) `.env` 없이도 로컬에서는 동작한다. 그래도 "이 앱이 어떤 환경변수를 읽는가"가 파일로 드러나는 편이 낫기 때문에 만들어 두기를 권장한다.

#### B-4-1) 시크릿 복원 — `.env.enc` 복호화 (챗봇 기능을 쓸 때만)

위 템플릿에는 **실제 API 키가 없다.** 챗봇(M1~)을 쓰려면 `ANTHROPIC_API_KEY`가, 트레이싱(M4)을
쓰려면 `LANGFUSE_*`가 실값이어야 한다. 이 저장소는 그 값들을 **암호화해서 커밋해 둔다.**

```bash
# ① 개인키 가져오기 (비밀번호 관리자에 보관해 둔 파일)
gpg --import react-python-env-secret.asc

# ② 복호화 — backend/.env 가 만들어진다
./scripts/env-decrypt.sh          # PowerShell: .\scripts\env-decrypt.ps1
```

이미 `.env`가 있으면 덮어쓰기를 거부한다. 강제하려면 `--force` / `-Force`.

**값을 바꿨으면 다시 암호화해서 커밋한다:**
```bash
./scripts/env-encrypt.sh          # PowerShell: .\scripts\env-encrypt.ps1
git add backend/.env.enc && git commit -m "chore: 시크릿 갱신"
```

##### 이 구조가 왜 이렇게 생겼나

| 파일 | 커밋? | 정체 |
|---|---|---|
| `backend/.env` | ✘ (gitignore) | 평문 시크릿. 절대 커밋하지 않는다 |
| `backend/.env.enc` | **✔** | 암호문. 개인키 없이는 못 연다 |
| `backend/.env.pubkey.asc` | **✔** | 공개키. **공개돼도 되는 것이 공개키의 정의다** |
| `react-python-env-secret.asc` | ✘ | 개인키. 리포 밖(비밀번호 관리자)에만 존재 |

**평문 커밋은 왜 안 되나**: GitHub은 푸시할 때 내용을 스캔해 `sk-ant-…` 같은 패턴을 찾으면
**푸시 자체를 거부**한다(실제로 이 저장소에서 겪었다). 뚫더라도 git 히스토리에 영구히 남고,
GitHub이 Anthropic에 유출을 통보해 키가 자동 폐기될 수 있다. **파일명을 바꿔도 소용없다 —
스캐너는 파일명이 아니라 내용을 본다.**

**비대칭(공개키/개인키)을 쓰는 이유**: 암호화에는 공개키만 있으면 된다. 즉 CI나 팀원이
"시크릿을 추가"할 수는 있어도 **"읽을" 수는 없다.** 대칭키(암호 하나)였다면 넣는 쪽과
읽는 쪽 권한이 같아진다.

> **실무에서는 보통 `age` + [SOPS](https://github.com/getsops/sops)를 쓴다.** 여기서 gpg를
> 쓴 건 Git for Windows에 이미 들어 있어 추가 설치가 필요 없기 때문이다. SOPS의 장점은
> **값 단위 암호화**라 `git diff`에서 "어느 키가 바뀌었는지"가 보인다는 것 — 지금 방식은
> 파일 통째로라 매번 전체가 바뀐 것으로 나온다. 팀 규모가 커지면 그때 갈아탈 지점이다.

##### ★ 개인키를 백업하지 않으면 영원히 못 연다 ★

키를 잃어버리면 `.env.enc`는 **복구 불가**다. 그게 암호화의 정의다. 최초 1회 반드시:

```bash
# 개인키를 파일로 내보내 비밀번호 관리자(1Password 등)에 저장한다
gpg --armor --export-secret-keys react-python-env > react-python-env-secret.asc
```

내보낸 파일은 `.gitignore`의 `*secret*.asc` 규칙이 막아주지만, **쓰고 나면 디스크에서
지우는 편이 안전하다.** 키를 새로 만들어야 하면 새 키쌍을 만들고 `.env.pubkey.asc`를 교체한 뒤
`env-encrypt`를 다시 돌린다.

##### 함정 2개 (실제로 겪은 것)

- **PowerShell에서 `gpg`를 못 찾는다** — Git for Windows가 gpg를 같이 깔지만 PATH에는
  `cmd` 디렉터리만 넣는다. Git Bash에서는 보이고 PowerShell에서는 안 보이는 이유다.
  스크립트가 `%ProgramFiles%\Git\usr\bin\gpg.exe`를 자동으로 찾도록 해뒀다.
- **`.ps1` 파일은 UTF-8 BOM이 있어야 한다** — Windows PowerShell 5.1은 BOM이 없으면
  스크립트를 시스템 ANSI(cp949)로 읽어서, 한글 주석이 깨지고 **파싱 에러로 죽는다.**
  이 저장소의 `.ps1`은 전부 BOM이 있다.

### B-5) 백엔드 의존성 설치 — 이 단계에서 Python이 설치된다

```bash
cd backend
uv sync --frozen
```

이 한 줄이 하는 일:

1. `backend/.python-version`(= `3.14`)을 읽는다.
2. 그 버전의 Python이 없으면 **uv가 직접 내려받는다** (시스템 Python은 건드리지 않는다).
3. `backend/.venv/` 가상환경을 만든다.
4. `uv.lock`에 적힌 **정확한 버전**으로 모든 패키지를 설치한다.

`--frozen`은 "lock 파일을 갱신하지 말고 적힌 그대로 설치하라"는 뜻이다. 다른 PC에서 환경을 동일하게 재현할 때는 이 플래그를 붙이는 것이 안전하다 (CI도 동일하게 `uv sync --frozen`을 쓴다). 의존성을 새로 추가할 때만 `--frozen` 없이 `uv sync`를 쓴다.

확인:
```bash
uv run python --version      # Python 3.14.x
```

### B-6) 프론트엔드 의존성 설치

```bash
cd ../frontend
npm ci
```

`npm ci`는 `package-lock.json`을 그대로 설치한다(`npm install`과 달리 lock을 갱신하지 않는다). 초기 설치에는 이쪽이 재현성 면에서 낫다.

### B-7) DB 기동 + 스키마 생성

```bash
cd ..                      # 저장소 루트
docker compose up -d db    # PostgreSQL 컨테이너만 백그라운드로
docker compose ps          # STATUS가 healthy가 될 때까지 (수 초)
```

```bash
cd backend
uv run alembic upgrade head
```

`items` 테이블이 이때 생성된다. **경로 B에서도 이 단계는 필수다.**

### B-8) 서버 실행 — 터미널 2개

```bash
# 터미널 1 — 백엔드
cd backend
uv run uvicorn app.main:app --reload
```

```bash
# 터미널 2 — 프론트엔드
cd frontend
npm run dev
```

두 터미널 모두 서버가 떠서 대기하는 상태로 남는다(멈춘 것이 아니다). 종료는 각 터미널에서 `Ctrl+C`.

브라우저에서 http://localhost:5173 접속.

------------------------------------------------------------------------------------------------------------------------

## 4. 설치 검증 체크리스트

순서대로 확인한다. 실패하면 [6. 트러블슈팅](#6-트러블슈팅)의 해당 항목을 본다.

| # | 명령 / 확인 | 기대 결과 |
|---|---|---|
| 1 | `docker ps` | 에러 없이 목록 출력 (Docker 데몬 정상) |
| 2 | `docker compose ps` | `db` 서비스가 `healthy` |
| 3 | `curl http://localhost:8000/health` | `{"status":"ok"}` |
| 4 | 브라우저에서 http://localhost:8000/docs | Swagger 문서 화면 |
| 5 | `curl http://localhost:8000/api/v1/items` | `[]` 또는 아이템 배열 (여기서 에러면 마이그레이션 미적용) |
| 6 | 브라우저에서 http://localhost:5173 | 화면이 뜨고 콘솔에 CORS 에러가 없음 |

경로 B라면 추가로:

| # | 명령 | 기대 결과 |
|---|---|---|
| 7 | `cd backend && uv run python --version` | `Python 3.14.x` |
| 8 | `cd backend && uv run pytest -v` | 전체 통과 (DB 없이 SQLite 인메모리로 실행됨) |
| 9 | `cd backend && uv run ruff check .` | `All checks passed!` |
| 10 | `cd frontend && npm run build` | 타입 체크 + 빌드 성공 |

------------------------------------------------------------------------------------------------------------------------

## 5. Python 버전은 어떻게 정해지나

이 프로젝트에서 Python 버전에 관여하는 파일은 세 개다. 역할이 각각 다르다.

| 파일 | 값 | 역할 |
|---|---|---|
| [`backend/pyproject.toml`](backend/pyproject.toml) | `requires-python = ">=3.12"` | **요구 조건.** "이 코드는 3.12 이상이면 돈다"는 선언. 라이브러리 의존성을 해석(resolve)할 때의 하한선이다. |
| [`backend/.python-version`](backend/.python-version) | `3.14` | **실제 선택.** uv가 가상환경을 만들 때 이 버전을 쓴다. 없으면 uv가 "조건을 만족하는 아무 버전"을 골라서, 사람마다·시점마다 달라진다. |
| [`backend/Dockerfile`](backend/Dockerfile) | `python:3.14-slim` | **운영 이미지.** `.python-version`과 같은 값이어야 한다. |

핵심은 **`uv.lock`이 패키지 버전을 완벽히 고정하더라도, 그것을 실행할 인터프리터가 고정돼 있지 않으면 재현성이 반쪽**이라는 점이다. `.python-version`이 없으면 이런 일이 생긴다:

- 로컬은 3.14, 운영 이미지는 3.12 → CI가 통과시킨 환경과 실제 배포 환경이 다르다.
- 몇 달 뒤 Python 3.15가 나오는 날, 아무도 코드를 안 건드렸는데 새로 클론한 사람의 환경만 깨진다.

그래서 셋을 **3.14로 통일**해 두었다. 버전을 올릴 때는 `.python-version`과 `Dockerfile` 두 곳을 **같이** 바꿔야 한다.

### 패치 버전(3.14.6)까지 안 박는 이유

`.python-version`에 `3.14`만 적으면 uv가 3.14 계열의 최신 패치를 쓴다. 보안 패치는 자동으로 따라가면서 호환성에 영향을 주는 마이너 버전은 고정되므로, 이 정도가 실무에서 쓰는 균형점이다. 완전한 비트 단위 재현이 필요한 상황이라면 `3.14.6`처럼 패치까지 적으면 된다.

### CI는 별도 설정이 필요 없다

[`.github/workflows/ci.yml`](.github/workflows/ci.yml)의 backend job은 `backend/` 디렉터리에서 `uv sync --frozen`을 실행한다. uv가 그 위치의 `.python-version`을 자동으로 읽으므로, 이 파일 하나로 로컬·CI·운영 이미지가 모두 정렬된다.

------------------------------------------------------------------------------------------------------------------------

## 6. 트러블슈팅

### `uv : 용어가 인식되지 않습니다` / `uv: command not found`

설치 시 변경된 PATH가 **기존에 열려 있던 터미널에는 반영되지 않는다.** 터미널(또는 VS Code)을 완전히 종료했다가 다시 연다. `node`, `npm`, `docker`도 마찬가지다.

### `Cannot connect to the Docker daemon` / `error during connect`

Docker Desktop이 실행 중이 아니다. 앱을 켜고 상태가 "Running"이 될 때까지 기다린 뒤 다시 시도한다. Windows에서는 WSL2 백엔드가 초기화되는 데 시간이 좀 걸린다.

### `uv sync` 중 Python 다운로드가 실패한다

사내 프록시/방화벽 환경에서 발생할 수 있다. Python만 따로 받아보면 원인이 드러난다:

```bash
uv python install 3.14
uv python list              # 설치된 버전 확인
```

프록시가 필요하다면 `HTTPS_PROXY` 환경변수를 설정한 뒤 재시도한다.

### `uv sync --frozen`이 lock 불일치로 실패한다

`pyproject.toml`을 수정했는데 `uv.lock`을 갱신하지 않은 상태다. 의도한 변경이라면:

```bash
uv lock          # lock 재생성
uv sync          # 설치
```

`uv.lock`은 **커밋 대상**이다. 재생성했다면 함께 커밋해야 다른 사람 환경도 같이 맞춰진다.

### API 호출 시 `relation "items" does not exist`

마이그레이션을 적용하지 않았다.

```bash
# 경로 A
docker compose run --rm backend alembic upgrade head
# 경로 B
cd backend && uv run alembic upgrade head
```

### 백엔드가 DB 연결 실패로 죽는다

DB가 먼저 떠 있어야 한다. `docker compose ps`로 `db`가 `healthy`인지 확인한다. `docker compose up -d db` 직후에는 초기화에 수 초가 걸린다.

### 포트가 이미 사용 중이다 (`port is already allocated`)

5432(DB) / 8000(백엔드) / 5173(프론트) 중 하나가 다른 프로세스에 점유돼 있다. 로컬에 PostgreSQL을 따로 설치해 둔 경우 5432가 흔히 겹친다. 점유 프로세스를 찾아 종료하는 명령은 [README.md](./README.md)의 "중지 명령어" 절에 정리돼 있다.

### 브라우저 콘솔에 CORS 에러가 뜬다

프론트엔드가 실행 중인 origin이 백엔드의 허용 목록에 없다. Vite 포트를 5173에서 바꿨다면 `backend/.env`의 `BACKEND_CORS_ORIGINS`도 같이 바꾸고 백엔드를 재시작해야 한다.

### 처음부터 다시 설치하고 싶다

```bash
docker compose down -v                 # 컨테이너 + DB 볼륨 삭제
rm -rf backend/.venv                   # PowerShell: Remove-Item -Recurse -Force backend\.venv
rm -rf frontend/node_modules           # PowerShell: Remove-Item -Recurse -Force frontend\node_modules
```

이후 [B-5](#b-5-백엔드-의존성-설치--이-단계에서-python이-설치된다)부터 다시 진행한다. 두 디렉터리 모두 `.gitignore` 대상이라 지워도 소스에는 영향이 없다.

------------------------------------------------------------------------------------------------------------------------

## 7. 다음 단계

| 하고 싶은 것 | 문서 |
|---|---|
| 일상적인 실행/중지, 백그라운드 기동, Visual Studio에서 쓰기 | [README.md](./README.md) — "로컬 개발 시작하기" |
| 테스트·린트·마이그레이션 명령어, 백엔드 아키텍처 | [CLAUDE.md](./CLAUDE.md) |
| Kubernetes 로컬 배포(minikube/kind) | [CLAUDE.md](./CLAUDE.md) — "Kubernetes" |
| 클라우드 VM 실배포, CI/CD 파이프라인 | [DEPLOYMENT.md](./DEPLOYMENT.md) |
