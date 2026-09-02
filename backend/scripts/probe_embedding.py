# M3 임베딩 모델 실측. 어느 모델을 쓸지가 스키마의 vector(N) 차원을 결정하므로,
# 테이블을 만들기 전에 여기서 정한다.
#
# 실행: cd backend && uv run python scripts/probe_embedding.py
#       cd backend && uv run python scripts/probe_embedding.py intfloat/multilingual-e5-large
#
# 첫 실행은 모델 파일을 받느라 오래 걸린다(MiniLM 0.22GB / e5-large 2.24GB).
# 캐시 위치: ~/.cache/fastembed (한 번 받으면 다음부터 즉시)
import sys

import numpy as np
from fastembed import TextEmbedding

sys.stdout.reconfigure(encoding="utf-8")

DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

QUERY = "파이썬 버전 어떻게 관리해?"

# ★ 반증 케이스를 반드시 섞는다 ★
# 관련 문장이 가까운 것만 보면 "이 모델 좋네"라고 착각한다. 무관한 문장이
# 확실히 멀어야 "의미를 구분한다"고 말할 수 있다. 모델이 모든 한국어 문장을
# 뭉뚱그려 비슷하다고 보는 경우가 실제로 있다.
DOCS = [
    ("관련", "인터프리터 버전은 .python-version과 Dockerfile 두 곳에 적혀 있고 항상 같아야 한다."),
    ("관련", "uv sync는 .python-version을 참조해 가상환경을 만든다."),
    ("무관", "nginx 리버스 프록시 설정은 conf.d 디렉터리의 server 블록에 있다."),
    ("무관", "React 컴포넌트는 useChat 훅으로 SSE 스트리밍을 처리한다."),
]


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    # 코사인 유사도 = 두 벡터가 이루는 각도. 1에 가까울수록 같은 방향(비슷한 의미).
    # 길이로 나누는 이유: 문장이 길어서 벡터 크기가 커진 것과 "의미가 비슷한 것"을
    # 구분하기 위해서다. 방향만 본다.
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def main() -> None:
    model_name = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_MODEL
    print(f"모델: {model_name}\n다운로드 중이면 시간이 걸립니다...\n")

    model = TextEmbedding(model_name=model_name)

    texts = [QUERY] + [d for _, d in DOCS]

    # ① 접두어 없이 (embed)
    plain = list(model.embed(texts))
    print(f"차원: {len(plain[0])}   ← 이 숫자가 스키마의 vector(N)이 된다\n")

    print("=" * 64)
    print("① embed() — 접두어 없이")
    print("=" * 64)
    show(plain[0], plain[1:])

    # ② 질문/문서를 구분해서 (query_embed / passage_embed)
    # fastembed가 모델별 접두어를 알아서 붙여준다. 붙이는 것과 안 붙이는 것의
    # 차이가 실제로 있는지 숫자로 확인한다.
    q = list(model.query_embed([QUERY]))[0]
    p = list(model.passage_embed([d for _, d in DOCS]))

    print("=" * 64)
    print("② query_embed / passage_embed — 접두어 자동")
    print("=" * 64)
    show(q, p)


def show(query_vec: np.ndarray, doc_vecs: list[np.ndarray]) -> None:
    scored = [(cosine(query_vec, v), label, text) for v, (label, text) in zip(doc_vecs, DOCS)]
    # 점수 내림차순 = 검색 결과 순서. 관련 2개가 위에 와야 한다.
    for score, label, text in sorted(scored, reverse=True):
        print(f"  {score:.4f}  [{label}] {text[:44]}")

    best_bad = max(s for s, label, _ in scored if label == "무관")
    worst_good = min(s for s, label, _ in scored if label == "관련")
    gap = worst_good - best_bad
    verdict = "OK" if gap > 0 else "FAIL — 무관한 문장이 관련 문장보다 위에 있다"
    print(
        f"\n  관련 최저 {worst_good:.4f} - 무관 최고 {best_bad:.4f} "
        f"= 격차 {gap:+.4f}  → {verdict}\n"
    )


if __name__ == "__main__":
    main()
