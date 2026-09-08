# 검색 평가 결과 — 2026-09-08 14:51

| 설정 | 값 |
|---|---|
| store | `qdrant` |
| 검색 방식 | `hybrid+gate` |
| top_k | 5 |
| 임베딩 모델 | `intfloat/multilingual-e5-large` |
| 청킹 | 구조 인식 · 최대 220토큰 / 오버랩 40토큰 |
| 골든셋 | 29건 |

## 검색 지표 (종류별)

`source` = 정답 문서에서 왔나(느슨) · `content` = 정답 대목을 실제로 가져왔나(엄격)

| 종류 | n | hit@1 (src) | hit@5 (src) | MRR (src) | hit@1 (cnt) | hit@5 (cnt) | MRR (cnt) |
|---|---|---|---|---|---|---|---|
| normal | 12 | 0.83 | 1.00 | 0.917 | 0.67 | 0.92 | 0.771 |
| keyword | 7 | 0.86 | 0.86 | 0.857 | 0.86 | 0.86 | 0.857 |
| unanswerable | 0 | — | — | — | — | — | — | 
| multiturn | 5 | 0.60 | 0.60 | 0.600 | 0.20 | 0.20 | 0.200 |
| **전체** | 24 | 0.79 | 0.88 | 0.833 | 0.62 | 0.75 | 0.677 |

## 질문별 상세

| id | 종류 | 질문 | src 순위 | cnt 순위 | top1 |
|---|---|---|---|---|---|
| n01 | normal | 파이썬 버전은 어떻게 관리해? | 1 | 2 | CLAUDE.md#20 (0.1667) |
| n02 | normal | 마이그레이션은 컨테이너가 뜰 때 자동으로 실행되나? | 2 | 2 | SETUP.md#7 (0.1667) |
| n03 | normal | VITE_API_URL은 언제 값이 정해지나? | 2 | 4 | SETUP.md#14 (0.5000) |
| n04 | normal | SQLAlchemy 모델을 새로 추가하면 어디에 등록해야 하나 | 1 | 1 | CLAUDE.md#28 (0.0000) |
| n05 | normal | alembic은 DB 접속 문자열을 어디서 읽나? | 1 | ✗ | CLAUDE.md#16 (0.4565) |
| n06 | normal | 백엔드 테스트는 어떤 DB로 도나? | 1 | 1 | CLAUDE.md#16 (0.3333) |
| n07 | normal | 프론트엔드 개발 서버는 몇 번 포트에서 뜨나? | 1 | 1 | SETUP.md#27 (0.4091) |
| n08 | normal | 운영 VM에서 DB 백업은 어떻게 돌아가나? | 1 | 1 | DEPLOYMENT.md#23 (0.0000) |
| n09 | normal | 배포한 뒤 문제가 생기면 이전 이미지로 어떻게 되돌리나? | 1 | 1 | DEPLOYMENT.md#22 (0.0000) |
| n10 | normal | k3s를 설치할 때 기본 인그레스는 어떻게 하나? | 1 | 1 | DEPLOYMENT.md#40 (0.4474) |
| n11 | normal | 마이그레이션 Job을 다시 실행하려면 어떻게 하나? | 1 | 1 | CLAUDE.md#23 (0.4583) |
| n12 | normal | uv sync는 프로젝트 자체를 어떤 방식으로 설치하나? | 1 | 1 | CLAUDE.md#29 (0.4333) |
| k01 | keyword | k8s/base/secret.yaml | 1 | 1 | DEPLOYMENT.md#43 (0.0000) |
| k02 | keyword | relation "items" does not exist | 1 | 1 | SETUP.md#40 (0.0000) |
| k03 | keyword | imagePullPolicy: IfNotPresent | 1 | 1 | DEPLOYMENT.md#6 (0.2500) |
| k04 | keyword | read:packages | ✗ | ✗ | - |
| k05 | keyword | nginx-proxy/conf.d | 1 | 1 | DEPLOYMENT.md#30 (0.3333) |
| k06 | keyword | uv sync --frozen | 1 | 1 | SETUP.md#24 (0.1667) |
| k07 | keyword | port is already allocated | 1 | 1 | SETUP.md#42 (0.0000) |
| u01 | unanswerable | 이 프로젝트의 Redis 캐시 만료 시간은 몇 초야? | ✗ | ✗ | SETUP.md#6 (0.3333) |
| u02 | unanswerable | 결제는 어떤 PG사를 연동해서 처리하나? | ✗ | ✗ | - |
| u03 | unanswerable | GraphQL 스키마는 어느 파일에 정의돼 있나? | ✗ | ✗ | - |
| u04 | unanswerable | 관리자 계정의 기본 비밀번호는 뭐야? | ✗ | ✗ | - |
| u05 | unanswerable | 이 서비스의 월간 활성 사용자 수는 몇 명이야? | ✗ | ✗ | - |
| m01 | multiturn | 그거 프로덕션에서는 어떻게 돼? | 1 | ✗ | CLAUDE.md#8 (0.3000) |
| m02 | multiturn | 그럼 그건 k8s에서는 어떻게 해? | 1 | ✗ | CLAUDE.md#11 (0.5000) |
| m03 | multiturn | 그거 CI에서도 자동으로 맞춰져? | 1 | 1 | CLAUDE.md#32 (0.4286) |
| m04 | multiturn | 그건 몇 시에 돌아? | ✗ | ✗ | - |
| m05 | multiturn | 거기서 기본 인그레스는 어떻게 했어? | ✗ | ✗ | - |

## unanswerable — 거리로 거를 수 있나

검색은 무조건 top_k개를 돌려준다. 문서에 없는 것을 물어도 '가장 덜 무관한' 청크가 나온다.

### 검색이 돌려준 거리

| 그룹 | n | top1 거리 최소 | 평균 | 최대 |
|---|---|---|---|---|
| 답할 수 있음 | 21 | 0.0000 | 0.2548 | 0.5000 |
| 답할 수 없음 | 1 | 0.3333 | 0.3333 | 0.3333 |

**겹친다(간격 -0.1667)** — 이 값 하나로는 못 거른다. 겹치는 폭이 좁으면 오거절을 감수하고 임계값을 쓸 수 있고, 넓으면 이 값 자체가 관련성을 담고 있지 않다는 뜻이다.

### dense 코사인 거리

| 그룹 | n | top1 거리 최소 | 평균 | 최대 |
|---|---|---|---|---|
| 답할 수 있음 | 24 | 0.1070 | 0.1551 | 0.2109 |
| 답할 수 없음 | 5 | 0.1748 | 0.2006 | 0.2257 |

**겹친다(간격 -0.0361)** — 이 값 하나로는 못 거른다. 겹치는 폭이 좁으면 오거절을 감수하고 임계값을 쓸 수 있고, 넓으면 이 값 자체가 관련성을 담고 있지 않다는 뜻이다.

> ★ 두 표를 비교하는 것이 요점이다 ★ 하이브리드가 돌려주는 거리는 RRF 융합 점수(=순위)라 관련성을 담고 있지 않다. 그라운딩 임계값은 반드시 dense 거리로 걸어야 한다 — M10의 게이트가 검색과 별개로 dense를 한 번 더 보는 이유다.