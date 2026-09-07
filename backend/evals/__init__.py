# 평가 하네스. (M6)
#
# ★ app/ 밖에 두는 것이 의도다 ★ 애플리케이션 코드가 아니고, ci.yml의 pytest가
# 수집하면 안 된다 — 실제 임베딩·LLM API를 부르므로 CI에서 돌면 비용·플래키·시크릿
# 문제가 생긴다(chatbot/README.md 앞머리의 CI 경고와 같은 이유).
#
# 예외는 metrics.py 하나다. API를 안 부르는 순수 함수이고, **지표 계산이 틀리면
# 그 뒤 모든 판단이 틀리므로** tests/test_metrics.py가 유닛 테스트한다.
#
# 실행 (backend/에서):
#   uv run python -m evals.run_retrieval
#   uv run python -m evals.run_retrieval --store qdrant --top-k 3
