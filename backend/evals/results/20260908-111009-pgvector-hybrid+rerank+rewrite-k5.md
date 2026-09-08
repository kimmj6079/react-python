# 검색 평가 결과 — 2026-09-08 11:10

| 설정 | 값 |
|---|---|
| store | `pgvector` |
| 검색 방식 | `hybrid+rerank+rewrite` |
| top_k | 5 |
| 임베딩 모델 | `intfloat/multilingual-e5-large` |
| 청킹 | 구조 인식 · 최대 220토큰 / 오버랩 40토큰 |
| 골든셋 | 29건 |

## 검색 지표 (종류별)

`source` = 정답 문서에서 왔나(느슨) · `content` = 정답 대목을 실제로 가져왔나(엄격)

| 종류 | n | hit@1 (src) | hit@5 (src) | MRR (src) | hit@1 (cnt) | hit@5 (cnt) | MRR (cnt) |
|---|---|---|---|---|---|---|---|
| normal | 12 | 0.92 | 1.00 | 0.958 | 0.92 | 1.00 | 0.958 |
| keyword | 7 | 1.00 | 1.00 | 1.000 | 1.00 | 1.00 | 1.000 |
| unanswerable | 0 | — | — | — | — | — | — | 
| multiturn | 5 | 0.40 | 1.00 | 0.650 | 0.20 | 0.40 | 0.300 |
| **전체** | 24 | 0.83 | 1.00 | 0.906 | 0.79 | 0.88 | 0.833 |

## 질문별 상세

| id | 종류 | 질문 | src 순위 | cnt 순위 | top1 |
|---|---|---|---|---|---|
| n01 | normal | 파이썬 버전은 어떻게 관리해? | 1 | 1 | CLAUDE.md#30 (0.3333) |
| n02 | normal | 마이그레이션은 컨테이너가 뜰 때 자동으로 실행되나? | 2 | 2 | SETUP.md#7 (0.1667) |
| n03 | normal | VITE_API_URL은 언제 값이 정해지나? | 1 | 1 | CLAUDE.md#24 (0.7500) |
| n04 | normal | SQLAlchemy 모델을 새로 추가하면 어디에 등록해야 하나 | 1 | 1 | CLAUDE.md#28 (0.0000) |
| n05 | normal | alembic은 DB 접속 문자열을 어디서 읽나? | 1 | 1 | CLAUDE.md#29 (0.8000) |
| n06 | normal | 백엔드 테스트는 어떤 DB로 도나? | 1 | 1 | CLAUDE.md#16 (0.3333) |
| n07 | normal | 프론트엔드 개발 서버는 몇 번 포트에서 뜨나? | 1 | 1 | SETUP.md#42 (0.6667) |
| n08 | normal | 운영 VM에서 DB 백업은 어떻게 돌아가나? | 1 | 1 | DEPLOYMENT.md#23 (0.0000) |
| n09 | normal | 배포한 뒤 문제가 생기면 이전 이미지로 어떻게 되돌리나? | 1 | 1 | DEPLOYMENT.md#22 (0.0000) |
| n10 | normal | k3s를 설치할 때 기본 인그레스는 어떻게 하나? | 1 | 1 | DEPLOYMENT.md#40 (0.4474) |
| n11 | normal | 마이그레이션 Job을 다시 실행하려면 어떻게 하나? | 1 | 1 | CLAUDE.md#23 (0.4583) |
| n12 | normal | uv sync는 프로젝트 자체를 어떤 방식으로 설치하나? | 1 | 1 | CLAUDE.md#29 (0.4333) |
| k01 | keyword | k8s/base/secret.yaml | 1 | 1 | DEPLOYMENT.md#43 (0.0000) |
| k02 | keyword | relation "items" does not exist | 1 | 1 | SETUP.md#40 (0.0000) |
| k03 | keyword | imagePullPolicy: IfNotPresent | 1 | 1 | DEPLOYMENT.md#45 (0.2500) |
| k04 | keyword | read:packages | 1 | 1 | DEPLOYMENT.md#12 (0.3000) |
| k05 | keyword | nginx-proxy/conf.d | 1 | 1 | DEPLOYMENT.md#15 (0.8363) |
| k06 | keyword | uv sync --frozen | 1 | 1 | SETUP.md#24 (0.1667) |
| k07 | keyword | port is already allocated | 1 | 1 | SETUP.md#42 (0.0000) |
| u01 | unanswerable | 이 프로젝트의 Redis 캐시 만료 시간은 몇 초야? | ✗ | ✗ | SETUP.md#6 (0.3333) |
| u02 | unanswerable | 결제는 어떤 PG사를 연동해서 처리하나? | ✗ | ✗ | SETUP.md#14 (0.5000) |
| u03 | unanswerable | GraphQL 스키마는 어느 파일에 정의돼 있나? | ✗ | ✗ | CLAUDE.md#12 (0.8889) |
| u04 | unanswerable | 관리자 계정의 기본 비밀번호는 뭐야? | ✗ | ✗ | SETUP.md#17 (0.4375) |
| u05 | unanswerable | 이 서비스의 월간 활성 사용자 수는 몇 명이야? | ✗ | ✗ | SETUP.md#19 (0.5000) |
| m01 | multiturn | 그거 프로덕션에서는 어떻게 돼? | 1 | ✗ | CLAUDE.md#24 (0.6667) |
| m02 | multiturn | 그럼 그건 k8s에서는 어떻게 해? | 2 | ✗ | SETUP.md#33 (0.5000) |
| m03 | multiturn | 그거 CI에서도 자동으로 맞춰져? | 1 | 1 | CLAUDE.md#32 (0.4286) |
| m04 | multiturn | 그건 몇 시에 돌아? | 2 | 2 | SETUP.md#33 (0.4677) |
| m05 | multiturn | 거기서 기본 인그레스는 어떻게 했어? | 4 | ✗ | CLAUDE.md#20 (0.4091) |

## unanswerable — 거리로 거를 수 있나

검색은 무조건 top_k개를 돌려준다. 문서에 없는 것을 물어도 '가장 덜 무관한' 청크가 나온다.

| 그룹 | n | top1 거리 최소 | 평균 | 최대 |
|---|---|---|---|---|
| 답할 수 있음 | 24 | 0.0000 | 0.3506 | 0.8363 |
| 답할 수 없음 | 5 | 0.3333 | 0.5319 | 0.8889 |

**두 그룹이 겹친다(간격 -0.5029)** — 단순 거리 임계값으로는 못 거른다. M10의 그라운딩을 프롬프트/생성 단계에서 해야 한다는 근거다.