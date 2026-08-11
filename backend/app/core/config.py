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

    # --- 챗봇(Anthropic) 설정 ---
    # 사용할 Claude 모델. 이 문자열 하나만 바꾸면 교체된다.
    # 가격은 100만 토큰당 입력/출력 기준:
    #   claude-haiku-4-5   $1 / $5     <- 현재 선택 (M1 스트리밍 확인용으로 충분)
    #   claude-sonnet-5    $3 / $15
    #   claude-opus-5      $5 / $25
    anthropic_model: str = "claude-haiku-4-5"

    # 실제 키 값은 이 파일이 아니라 backend/.env의 ANTHROPIC_API_KEY에서 읽는다.
    # (config.py는 git에 커밋되는 파일이므로 시크릿을 절대 여기에 적으면 안 된다.)
    # 기본값을 빈 문자열로 두는 이유: 키가 없는 CI/pytest에서도 Settings()
    # 생성이 실패하지 않게 하기 위함.
    anthropic_api_key: str = ""

    @property
    def cors_origins(self) -> list[str]:
        # "a, b, c" 형태의 문자열을 ["a", "b", "c"] 리스트로 변환해서 CORSMiddleware에 넘긴다.
        return [origin.strip() for origin in self.backend_cors_origins.split(",") if origin.strip()]


# 앱 전체에서 이 인스턴스 하나를 import해서 공유한다 (싱글턴처럼 사용).
settings = Settings()
