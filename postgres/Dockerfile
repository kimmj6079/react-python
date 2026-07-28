# =====================================================================
# 로컬 개발용 PostgreSQL 이미지를 위한 Dockerfile.
# 공식 postgres:16-alpine 이미지에 헬스체크만 추가한 얇은 래퍼.
# docker-compose.yml의 db 서비스가 이 디렉토리를 빌드 컨텍스트로 사용한다.
# =====================================================================

# 공식 postgres 16 alpine 이미지를 베이스로 사용
FROM postgres:16-alpine

# 헬스체크 정의: 5초 간격, 3초 타임아웃, 10회 재시도
# pg_isready로 postgres 서버 접속 가능 여부 확인 (docker-compose의 service_healthy 조건이 이 결과를 사용)
HEALTHCHECK --interval=5s --timeout=3s --retries=10 \
    CMD pg_isready -U postgres

# 단독으로 이미지를 빌드할 때 예시 커맨드
# docker build -t react-python-db .
# 단독으로 컨테이너를 실행할 때 예시 커맨드 (docker-compose 없이 테스트용)
# docker run -d --name react-python-db -p 5432:5432 -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=app -v db-data:/var/lib/postgresql/data react-python-db
