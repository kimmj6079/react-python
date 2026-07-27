# 앱 전역 설정을 한 곳에서 관리하는 파일.
# pydantic-settings는 여기 정의된 각 필드를 "같은 이름의 대문자 환경변수"에서 자동으로 읽어온다.
# 예: DATABASE_URL 환경변수가 있으면 database_url 필드가 그 값으로 덮어써진다.
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # 환경변수가 없으면 backend/.env 파일에서 값을 읽는다.
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    project_name: str = "react-python study API"
    api_v1_prefix: str = "/api/v1"

    # 기본값은 로컬 docker-compose의 Postgres 접속 정보.
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/app"

    # Comma-separated list of allowed origins for local dev CORS.
    backend_cors_origins: str = "http://localhost:5173"

    @property
    def cors_origins(self) -> list[str]:
        # "a, b, c" 형태의 문자열을 ["a", "b", "c"] 리스트로 변환해서 CORSMiddleware에 넘긴다.
        return [origin.strip() for origin in self.backend_cors_origins.split(",") if origin.strip()]


# 앱 전체에서 이 인스턴스 하나를 import해서 공유한다 (싱글턴처럼 사용).
settings = Settings()
