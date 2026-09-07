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

    # --- RAG 저장소 설정 (M3-3c / M3-4) ---
    # ★ 어느 벡터 저장소를 쓸 것인가 ★ "pgvector" 또는 "qdrant".
    # 이 값 하나로 인입·검색·챗봇이 통째로 갈아끼워진다(app/rag/factory.py의 get_store).
    #
    # Literal이 아니라 str인 이유: 오타를 pydantic이 422처럼 조용히 잡아주는 것보다,
    # get_store()가 "pgvector|qdrant 중 하나여야 한다"고 이름을 담아 죽는 편이 낫다.
    # (Literal로 하면 앱 부팅 자체가 pydantic ValidationError로 죽는데, 메시지가
    #  Settings 전체 검증 실패로 나와서 원인 필드를 찾기가 오히려 번거롭다.)
    vector_store: str = "pgvector"

    # Qdrant 접속 주소. 로컬은 docker-compose의 qdrant 서비스(포트 6333),
    # 컨테이너 안에서는 docker-compose.yml이 http://qdrant:6333으로 덮어쓴다.
    qdrant_url: str = "http://localhost:6333"

    # 컬렉션 이름 = pgvector의 테이블 이름에 해당한다. 설정으로 뺀 이유:
    # M7에서 청킹 전략을 바꿀 때 docs_v1 / docs_v2로 나란히 두고 A/B 비교를 하려면
    # 이 값이 바뀔 수 있어야 한다. (pgvector에서 같은 걸 하려면 마이그레이션이 필요하다)
    qdrant_collection: str = "document_chunks"

    @property
    def cors_origins(self) -> list[str]:
        # "a, b, c" 형태의 문자열을 ["a", "b", "c"] 리스트로 변환해서 CORSMiddleware에 넘긴다.
        return [origin.strip() for origin in self.backend_cors_origins.split(",") if origin.strip()]


# 앱 전체에서 이 인스턴스 하나를 import해서 공유한다 (싱글턴처럼 사용).
settings = Settings()
