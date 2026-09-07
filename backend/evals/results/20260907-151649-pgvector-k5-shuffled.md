# 검색 평가 결과 — 2026-09-07 15:16

| 설정 | 값 |
|---|---|
| store | `pgvector` |
| top_k | 5 |
| 임베딩 모델 | `intfloat/multilingual-e5-large` |
| 청킹 | 고정 600자 / 오버랩 100 |
| 골든셋 | 24건 |
| ⚠ 대조군 | **순서 무작위 셔플** (하네스 검증용, 정상 결과 아님) |

## 검색 지표 (종류별)

`source` = 정답 문서에서 왔나(느슨) · `content` = 정답 대목을 실제로 가져왔나(엄격)

| 종류 | n | hit@1 (src) | hit@5 (src) | MRR (src) | hit@1 (cnt) | hit@5 (cnt) | MRR (cnt) |
|---|---|---|---|---|---|---|---|
| normal | 12 | 0.92 | 1.00 | 0.958 | 0.25 | 0.83 | 0.475 |
| keyword | 7 | 0.86 | 1.00 | 0.905 | 0.57 | 1.00 | 0.683 |
| unanswerable | 0 | — | — | — | — | — | — | 
| **전체** | 19 | 0.89 | 1.00 | 0.939 | 0.37 | 0.89 | 0.552 |

## 질문별 상세

| id | 종류 | 질문 | src 순위 | cnt 순위 | top1 |
|---|---|---|---|---|---|
| n01 | normal | 파이썬 버전은 어떻게 관리해? | 1 | 2 | SETUP.md#13 (0.1883) |
| n02 | normal | 마이그레이션은 컨테이너가 뜰 때 자동으로 실행되나? | 2 | ✗ | DEPLOYMENT.md#29 (0.1750) |
| n03 | normal | VITE_API_URL은 언제 값이 정해지나? | 1 | 3 | CLAUDE.md#18 (0.1634) |
| n04 | normal | SQLAlchemy 모델을 새로 추가하면 어디에 등록해야 하나 | 1 | 5 | CLAUDE.md#11 (0.1814) |
| n05 | normal | alembic은 DB 접속 문자열을 어디서 읽나? | 1 | ✗ | CLAUDE.md#10 (0.1935) |
| n06 | normal | 백엔드 테스트는 어떤 DB로 도나? | 1 | 1 | SETUP.md#13 (0.1774) |
| n07 | normal | 프론트엔드 개발 서버는 몇 번 포트에서 뜨나? | 1 | 1 | SETUP.md#11 (0.1725) |
| n08 | normal | 운영 VM에서 DB 백업은 어떻게 돌아가나? | 1 | 2 | DEPLOYMENT.md#20 (0.1869) |
| n09 | normal | 배포한 뒤 문제가 생기면 이전 이미지로 어떻게 되돌리나? | 1 | 3 | DEPLOYMENT.md#1 (0.1935) |
| n10 | normal | k3s를 설치할 때 기본 인그레스는 어떻게 하나? | 1 | 3 | DEPLOYMENT.md#22 (0.1651) |
| n11 | normal | 마이그레이션 Job을 다시 실행하려면 어떻게 하나? | 1 | 2 | DEPLOYMENT.md#29 (0.1675) |
| n12 | normal | uv sync는 프로젝트 자체를 어떤 방식으로 설치하나? | 1 | 1 | CLAUDE.md#20 (0.1655) |
| k01 | keyword | k8s/base/secret.yaml | 1 | 1 | DEPLOYMENT.md#26 (0.1438) |
| k02 | keyword | relation "items" does not exist | 1 | 1 | SETUP.md#18 (0.2251) |
| k03 | keyword | imagePullPolicy: IfNotPresent | 1 | 4 | DEPLOYMENT.md#13 (0.1972) |
| k04 | keyword | read:packages | 3 | 3 | CLAUDE.md#12 (0.2196) |
| k05 | keyword | nginx-proxy/conf.d | 1 | 1 | DEPLOYMENT.md#17 (0.1748) |
| k06 | keyword | uv sync --frozen | 1 | 1 | SETUP.md#9 (0.1784) |
| k07 | keyword | port is already allocated | 1 | 5 | SETUP.md#6 (0.2169) |
| u01 | unanswerable | 이 프로젝트의 Redis 캐시 만료 시간은 몇 초야? | ✗ | ✗ | CLAUDE.md#0 (0.1838) |
| u02 | unanswerable | 결제는 어떤 PG사를 연동해서 처리하나? | ✗ | ✗ | CLAUDE.md#14 (0.2130) |
| u03 | unanswerable | GraphQL 스키마는 어느 파일에 정의돼 있나? | ✗ | ✗ | DEPLOYMENT.md#26 (0.2007) |
| u04 | unanswerable | 관리자 계정의 기본 비밀번호는 뭐야? | ✗ | ✗ | DEPLOYMENT.md#2 (0.2103) |
| u05 | unanswerable | 이 서비스의 월간 활성 사용자 수는 몇 명이야? | ✗ | ✗ | CLAUDE.md#1 (0.2347) |

## unanswerable — 거리로 거를 수 있나

검색은 무조건 top_k개를 돌려준다. 문서에 없는 것을 물어도 '가장 덜 무관한' 청크가 나온다.

| 그룹 | n | top1 거리 최소 | 평균 | 최대 |
|---|---|---|---|---|
| 답할 수 있음 | 19 | 0.1438 | 0.1835 | 0.2251 |
| 답할 수 없음 | 5 | 0.1838 | 0.2085 | 0.2347 |

**두 그룹이 겹친다(간격 -0.0412)** — 단순 거리 임계값으로는 못 거른다. M10의 그라운딩을 프롬프트/생성 단계에서 해야 한다는 근거다.