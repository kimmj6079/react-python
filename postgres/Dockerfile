# 공식 postgres 16 alpine 이미지를 베이스로 사용
# ★ M3: pgvector 확장이 미리 설치된 공식 이미지로 교체 ★
# postgres:16-alpine + apk로 직접 빌드하는 방법도 있지만(이미지가 작다),
# 컴파일 도구 설치 + 버전 호환 확인이 따라붙는다. 확장 하나를 위해
# 빌드 스크립트를 유지보수할 이유가 없어서 공식 이미지를 쓴다.
# 주의: 이 이미지는 alpine이 아니라 debian 기반이라 용량이 커진다(로컬 개발이라 감수).
FROM pgvector/pgvector:pg16

# 헬스체크 정의: 5초 간격, 3초 타임아웃, 10회 재시도
# pg_isready로 postgres 서버 접속 가능 여부 확인 (docker-compose의 service_healthy 조건이 이 결과를 사용)
HEALTHCHECK --interval=5s --timeout=3s --retries=10 \
    CMD pg_isready -U postgres

# 단독으로 이미지를 빌드할 때 예시 커맨드
# docker build -t react-python-db .
# 단독으로 컨테이너를 실행할 때 예시 커맨드 (docker-compose 없이 테스트용)
# docker run -d --name react-python-db -p 5432:5432 -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=app -v db-data:/var/lib/postgresql/data react-python-db
