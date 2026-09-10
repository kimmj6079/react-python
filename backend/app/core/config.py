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

    # ★ M13-b: 리랭킹 스킵 조건 ★ 후보가 이 수보다 적으면 리랭킹을 아예 안 부른다.
    # 기본 6 = "top_k(5)보다 많을 때만 순서를 바로잡는다".
    #
    # 근거: 후보가 5개 이하면 리랭킹을 해도 **어차피 전부 프롬프트에 들어간다.**
    # 바뀌는 것은 순서뿐인데, 그 대가로 LLM을 5번 부르고 사용자는 그만큼 더 기다린다.
    # **가장 싼 최적화는 하지 않는 것이다.**
    #
    # ★ 대가를 알고 켠다 ★ 순서가 아무 의미도 없는 것은 아니다. 프롬프트 앞쪽 문맥이
    # 더 많이 반영되고(lost in the middle), 인용 카드도 그 순서로 그려진다. 즉 이 스킵은
    # **지연을 사고 품질을 조금 판다.** 얼마나 파는지는 M6로 재야 하는데 크레딧이 없어
    # 아직 못 쟀다 — 그래서 값을 코드가 아니라 설정에 둔다(0으로 두면 스킵이 꺼진다).
    #
    # 지금 말뭉치(138청크)에서는 하이브리드가 거의 항상 20개를 채우므로 **이 조건은
    # 사실상 발동하지 않는다.** 발동하는 때는 (a) 테넌트 필터가 좁을 때 (b) 말뭉치가
    # 작을 때 (c) 게이트를 통과했지만 후보가 적을 때다. 로그로 발동 여부를 남긴다.
    rerank_min_candidates: int = 6

    # ★ M13-b: 단계별 지연을 응답에 실을 것인가 ★
    # 켜면 SSE finish 프레임의 messageMetadata에 `timings`가 함께 나간다(M13-a에서
    # traceId를 실으려고 만든 자리에 그대로 얹힌다). 브라우저 DevTools에서 바로 보인다.
    #
    # ★ 실무라면 끈다 ★ 내부 구조(어떤 단계가 있는지)와 성능 특성을 클라이언트에 그대로
    # 노출하는 값이다. 공격자에게는 "어디가 느린지" = "어디를 때리면 되는지"의 힌트고,
    # 일반 사용자에게는 아무 의미가 없다. 학습 중에는 눈으로 보는 값이 크므로 기본 True로
    # 두되, 이 주석을 근거로 배포 전에 끈다.
    timings_in_response: bool = True

    # 리랭킹에 넘길 후보 수. 하이브리드의 top-30보다 줄인 값이다 — README의 함정:
    # "리랭킹이 끝나야 생성 스트리밍이 시작되므로 사용자가 체감하는 침묵이 길어진다."
    # M1에서 스트리밍으로 얻은 체감 속도를 여기서 일부 잃고, M13에서 회수한다.
    rerank_candidates: int = 20

    # ★ M9: 대화형 질의 재작성 ★ 재작성·멀티쿼리도 Haiku면 충분하다. 여기에 Opus를
    # 쓰면 품질은 거의 그대로인데 TTFT만 먹는다 — 이 단계는 사용자가 기다리는
    # 경로의 맨 앞에 있어서 지연이 그대로 체감된다.
    anthropic_rewrite_model: str = "claude-haiku-4-5"

    # 히스토리가 있을 때만 재작성한다(rewrite.py의 조건부 실행). 이 플래그는
    # "기능 자체를 끄는" 스위치이고, M6 하네스로 before/after를 재려고 뒀다.
    query_rewrite_enabled: bool = True

    # --- 그라운딩 (M10) ---
    # ★ 임계값은 dense 코사인 거리에만 걸 수 있다 ★ 하이브리드(RRF)가 돌려주는
    # 점수는 **순위에서 나온 값이라 유사도가 아니다.** 실측(BASELINE-M10.md):
    # 답할 수 있는 질문의 하이브리드 거리가 0.0000~0.5000, 답할 수 없는 질문이
    # 0.3000~0.5000으로 완전히 겹쳐서 어디를 잘라도 의미가 없다. 반면 dense 거리는
    # 답 가능 0.107~0.209 / 불가능 0.175~0.226으로 거의 갈린다.
    grounding_enabled: bool = True

    # 0.18: 스윕 표(BASELINE-M10.md)에서 고른 값이다.
    #
    # ★ 수치상 최적값을 일부러 안 골랐다 ★ 0.174로 하면 답할 수 없는 질문 5/5를
    # 다 거절하면서 오거절은 1건뿐이라 표에서 가장 좋아 보인다. 하지만 그 값은
    # 표본 두 개(0.1725와 0.1748) 사이 **폭 0.0023짜리 창**에 있다 — 문서가
    # 한 줄만 바뀌어도 뒤집히는 자리다. 24건짜리 골든셋에 소수점 셋째 자리를
    # 맞추는 것은 튜닝이 아니라 과적합이다.
    #
    # 0.175~0.190은 결과가 (거절 4/5, 오거절 1/19)로 **평평한 고원**이다. 그
    # 한가운데를 고르면 말뭉치가 조금 흔들려도 동작이 안 바뀐다. 0.170으로 내리면
    # 거절이 5/5가 되지만 오거절이 15.8%로 뛴다(n01·n05가 벼랑 끝에 있다).
    #
    # ★ 이 숫자는 이 말뭉치·이 임베딩 모델의 것이다 ★ 문서를 갈아엎거나
    # embedding.py의 MODEL_NAME을 바꾸면 거리 분포 자체가 달라져 반드시 다시 재야
    # 한다. 그래서 코드가 아니라 설정에 둔다 — 실무에서도 이런 상수는 배포 후
    # 로그로 분포를 지켜보며 조정하는 값이지, 한 번 정하고 끝나는 값이 아니다.
    grounding_max_distance: float = 0.18

    # --- 임베딩 캐시 (M13-c) ---
    # ★ 인입 경로에만 걸린다 ★ 질의 임베딩은 일부러 캐시하지 않는다 —
    # 이유 두 개는 app/rag/embedding_cache.py 머리 주석 참고(핵심: 계측 대상 경로에
    # 캐시를 넣으면 measure_latency.py가 거짓말을 하기 시작한다).
    #
    # 끄는 스위치를 남겨둔 이유: 캐시가 의심스러울 때 "캐시 없이도 같은 결과인가"를
    # 한 줄로 확인할 수 있어야 한다. 캐시 버그는 "틀린 벡터를 빠르게 돌려주는" 모양이라
    # 검색 품질만 조용히 무너진다 — 껐다 켜서 비교하는 것이 유일한 진단법이다.
    embedding_cache_enabled: bool = True

    # 상대 경로면 backend/ 기준으로 푼다(embedding_cache.py의 BACKEND_DIR).
    # .gitignore에 들어 있고, 지워도 아무것도 잃지 않는다 — 다시 계산될 뿐이다.
    embedding_cache_path: str = ".cache/embeddings.sqlite3"

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
