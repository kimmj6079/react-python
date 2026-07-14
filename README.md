# react-python

FastAPI + React(TypeScript/Vite) + PostgreSQL 풀스택 스터디 프로젝트. 개발 → 테스트 → Docker → Kubernetes → CI/CD까지 실무 흐름을 학습한다. 전체 아키텍처와 명령어 레퍼런스는 [CLAUDE.md](./CLAUDE.md) 참고.

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
