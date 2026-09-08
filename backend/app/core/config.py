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

    # 평가 하네스의 LLM-as-judge가 쓰는 모델. (M6-b)
    # ★ 채점자는 피채점자보다 약하면 안 된다 ★ 답변은 haiku가 만들지만 "이 답이 문맥에
    # 근거하는가"를 판정하려면 더 좋은 모델이 필요하다 — 약한 채점자는 잡음을 만들고,
    # 그 잡음 위에서 M7~M13의 개선을 판단하면 계측기가 없는 것만 못하다.
    # 채점은 지연이 상관없는 배치 작업이라 비싼 모델을 써도 되고(M13에서 Batches API로
    # 50% 더 절감), 골든셋이 24건뿐이라 실행당 비용도 작다.
    judge_model: str = "claude-opus-5"

    # --- RAG 저장소 설정 (M3-3c / M3-4) ---
    # ★ 어느 벡터 저장소를 쓸 것인가 ★ "pgvector" 또는 "qdrant".
    # 이 값 하나로 인입·검색·챗봇이 통째로 갈아끼워진다(app/rag/factory.py의 get_store).
    #
    # Literal이 아니라 str인 이유: 오타를 pydantic이 422처럼 조용히 잡아주는 것보다,
    # get_store()가 "pgvector|qdrant 중 하나여야 한다"고 이름을 담아 죽는 편이 낫다.
    # (Literal로 하면 앱 부팅 자체가 pydantic ValidationError로 죽는데, 메시지가
    #  Settings 전체 검증 실패로 나와서 원인 필드를 찾기가 오히려 번거롭다.)
    # ★ M8에서 기본값이 pgvector -> qdrant로 바뀌었다 ★
    # M3-4에서 "Qdrant가 값을 하기 시작하는 지점은 (c) DB 레벨 하이브리드 검색이고,
    # M8에서 이 판단을 다시 한다"고 적어뒀다. 지금이 그때이고, 데이터가 정했다:
    #   pgvector(dense-only)  MRR 0.816
    #   qdrant(hybrid)        MRR 0.860   ← keyword MRR은 0.893 -> 1.000
    # pgvector 구현은 그대로 남는다. 하이브리드가 필요 없는 환경(Postgres만 있는 서버)
    # 에서는 여전히 한 줄로 되돌릴 수 있고, 그 선택지가 있다는 것 자체가 3-3의 값이다.
    vector_store: str = "qdrant"

    # Qdrant 접속 주소. 로컬은 docker-compose의 qdrant 서비스(포트 6333),
    # 컨테이너 안에서는 docker-compose.yml이 http://qdrant:6333으로 덮어쓴다.
    qdrant_url: str = "http://localhost:6333"

    # 컬렉션 이름 = pgvector의 테이블 이름에 해당한다. 설정으로 뺀 이유:
    # M7에서 청킹 전략을 바꿀 때 docs_v1 / docs_v2로 나란히 두고 A/B 비교를 하려면
    # 이 값이 바뀔 수 있어야 한다. (pgvector에서 같은 걸 하려면 마이그레이션이 필요하다)
    qdrant_collection: str = "document_chunks"

    # ★ M8: 하이브리드 검색(dense + BM25)을 쓸 것인가 ★
    # 저장소가 HybridStore 능력을 갖고 있을 때만 의미가 있다(지금은 Qdrant만).
    # 능력이 없으면 dense-only로 조용히 내려간다 — 설정이 켜져 있다고 없는 능력을
    # 만들어내지는 않는다. M6 하네스로 dense vs hybrid를 A/B 하려고 플래그로 뒀다.
    hybrid_search: bool = True

    # ★ M8-b: 리랭킹 ★ 하이브리드가 재현율(넉넉히 뽑기)이라면 리랭킹은 정밀도(순서 바로잡기)다.
    # 채팅 모델과 별도 필드로 둔 이유: 나중에 한쪽만 바꾸고 싶어진다. 리랭킹은 짧은
    # 프롬프트 × N개라 Haiku로 충분하고, 여기에 Opus를 쓰면 품질은 거의 그대로인데
    # TTFT만 먹는다.
    anthropic_rerank_model: str = "claude-haiku-4-5"

    # ★ 측정하고 켰다 ★ 기본값을 False로 두고 M6 하네스로 먼저 확인했다:
    #   hybrid          hit@1 0.79 · hit@5 0.95 · MRR 0.860
    #   hybrid+rerank   hit@1 0.95 · hit@5 1.00 · MRR 0.974
    # hit@1이 +0.16이다. 대가를 알고 켠다 — **요청마다 Haiku를 20번 부른다.**
    #   비용: 프롬프트가 짧아 요청당 수십 원 수준(Haiku $1/$5 per MTok)
    #   지연: 리랭킹이 끝나야 생성 스트리밍이 시작된다. M1에서 스트리밍으로 얻은
    #         체감 속도를 여기서 일부 잃는다 — M13의 지연 예산에서 계측하고 회수한다.
    rerank_enabled: bool = True

    # 리랭킹에 넘길 후보 수. 하이브리드의 top-30보다 줄인 값이다 — README의 함정:
    # "리랭킹이 끝나야 생성 스트리밍이 시작되므로 사용자가 체감하는 침묵이 길어진다."
    # M1에서 스트리밍으로 얻은 체감 속도를 여기서 일부 잃고, M13에서 회수한다.
    rerank_candidates: int = 20

    # --- 관측성 (Langfuse, M4) ---
    # 트레이싱은 "있으면 좋은 것"이지 앱의 필수 경로가 아니다. 그래서 기본값이 빈
    # 문자열이고, 비어 있으면 core/tracing.py가 아예 핸들러를 안 만든다(no-op).
    # 키가 없는 CI·pytest·새로 클론한 로컬에서 앱이 그대로 뜬다.
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""

    # Cloud가 기본. self-host로 옮길 때 이 한 줄만 바꾼다(예: http://localhost:3000).
    # 데이터가 어디로 나가는지를 결정하는 값이라 코드 상수가 아니라 설정에 둔다.
    langfuse_host: str = "https://cloud.langfuse.com"

    @property
    def langfuse_enabled(self) -> bool:
        # ★ "켜졌는가"를 한 곳에서만 판단한다 ★ 이 표현이 여러 곳에 흩어지면
        # "public만 넣고 secret은 깜빡한" 반쪽 설정에서 곳곳이 다르게 행동한다.
        return bool(self.langfuse_public_key and self.langfuse_secret_key)

    @property
    def cors_origins(self) -> list[str]:
        # "a, b, c" 형태의 문자열을 ["a", "b", "c"] 리스트로 변환해서 CORSMiddleware에 넘긴다.
        return [origin.strip() for origin in self.backend_cors_origins.split(",") if origin.strip()]


# 앱 전체에서 이 인스턴스 하나를 import해서 공유한다 (싱글턴처럼 사용).
settings = Settings()
