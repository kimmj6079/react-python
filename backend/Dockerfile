# =====================================================================
# 백엔드(FastAPI) 프로덕션 이미지를 위한 멀티스테이지 Dockerfile.
# 1단계(builder): uv로 의존성 + 프로젝트를 가상환경(.venv)에 설치.
# 2단계(final): builder에서 .venv와 앱 코드만 복사해 최종 런타임 이미지를 만듦
#   (빌드 도구, 캐시 등은 최종 이미지에 남지 않아 이미지 크기가 작아짐).
# non-root 사용자(appuser)로 실행하며, 8000번 포트에서 uvicorn으로 서비스한다.
# =====================================================================

# 빌드용 1단계 시작: 의존성 설치를 담당하는 builder 스테이지 (베이스: python 3.14-slim)
# 버전은 backend/.python-version(3.14)과 반드시 같아야 한다 -- 로컬/CI/운영 이미지가
# 서로 다른 파이썬에서 돌면 "CI는 통과하는데 운영에서만 터지는" 상황이 생긴다.
FROM python:3.14-slim AS builder
# uv 공식 이미지에서 uv/uvx 바이너리만 가져와 패키지 매니저로 사용
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# 이후 명령어들의 작업 디렉토리를 /app으로 설정
WORKDIR /app
# 바이트코드 사전 컴파일 활성화, 하드링크 대신 복사 방식 사용(레이어 캐시 호환)
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Install deps first (cache layer independent of app code changes).
# 의존성을 먼저 설치해 앱 코드 변경과 무관한 캐시 레이어로 분리
# 의존성 정의 파일만 먼저 복사 (앱 코드보다 먼저 캐시되게 하기 위함)
COPY pyproject.toml uv.lock ./
# lock 파일 그대로 프로덕션 의존성만 설치 (프로젝트 자체 / dev 의존성은 제외)
RUN uv sync --frozen --no-install-project --no-dev

# 실제 앱 소스 코드 복사
COPY app ./app
# 프로젝트까지 포함해 editable 설치 완료 (dev 의존성은 제외)
RUN uv sync --frozen --no-dev


# 최종 런타임 이미지 2단계 시작 (builder 산출물만 가져와 이미지 용량 최소화)
# builder에서 만든 .venv를 그대로 복사해 쓰므로, 여기 베이스 이미지의 파이썬
# 마이너 버전이 builder와 다르면 venv가 깨진다 (site-packages 경로/ABI 불일치).
FROM python:3.14-slim AS final
# 컨테이너를 root가 아닌 전용 사용자(appuser)로 실행하기 위해 계정 생성
RUN useradd --create-home --uid 1000 appuser
# 작업 디렉토리 설정
WORKDIR /app

# builder 스테이지에서 만든 가상환경(.venv)만 복사
COPY --from=builder /app/.venv /app/.venv
# builder 스테이지에서 만든 앱 소스 복사
COPY --from=builder /app/app /app/app
# Alembic 설정 파일 복사 (마이그레이션 실행에 필요)
COPY alembic.ini ./
# Alembic 마이그레이션 스크립트 디렉토리 복사
COPY alembic ./alembic
# venv 안의 실행파일(uvicorn 등)을 바로 찾을 수 있도록 PATH에 추가
ENV PATH="/app/.venv/bin:$PATH"

# 이후 명령/컨테이너 실행을 non-root 사용자로 전환
USER appuser
# 컨테이너가 8000번 포트를 사용함을 문서화 (실제 포트 매핑은 아님)
EXPOSE 8000

# 헬스체크 정의: 30초 간격, 3초 타임아웃, 시작 후 5초 유예
# /health 엔드포인트 호출 실패 시 컨테이너를 unhealthy로 표시
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# 컨테이너 기본 실행 커맨드: uvicorn으로 FastAPI 앱 구동 (--reload 없는 프로덕션 모드)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
