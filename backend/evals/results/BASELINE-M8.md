# M8 하이브리드 검색 (2026-09-08)

M7 최종 상태는 [`BASELINE-M7.md`](./BASELINE-M7.md). 이 문서는 **dense + BM25 하이브리드**의
before/after다.

---

## 1. 결과 — README의 예상이 정확히 맞았다

README M8의 예상: *"`keyword` 종류에서 hybrid가 크게 오르고 `normal`에서는 비슷"*

| 종류 | n | | hit@1 | hit@5 | MRR |
|---|---|---|---|---|---|
| normal | 12 | dense | 0.67 | 0.92 | 0.771 |
| normal | 12 | **hybrid** | 0.67 | 0.92 | **0.778** |
| **keyword** | 7 | dense | 0.86 | 1.00 | 0.893 |
| **keyword** | 7 | **hybrid** | **1.00** | 1.00 | **1.000** |
| 전체 | 19 | dense | 0.74 | 0.95 | 0.816 |
| 전체 | 19 | **hybrid** | **0.79** | 0.95 | **0.860** |

**`keyword` MRR이 1.000이다 — 7건 전부 1위.** `normal`은 0.771 → 0.778로 사실상 제자리.
**정확히 예상한 모양이고, 그래서 하이브리드가 제대로 붙었다고 말할 수 있다.**

M6 골든셋에 `keyword` 종류를 일부러 섞어둔 값이 여기서 회수된다. 그 7건이 없었다면
전체 MRR 0.816 → 0.860(+0.044)만 보이고 "왜 올랐는지"는 알 수 없었을 것이다.

### `k04`가 5위 → ✗ → 4위 → **1위**로 끝났다

`read:packages`는 M6 베이스라인에서 5위였고, M7에서 ✗까지 갔다가 병합으로 4위,
하이브리드로 **1위**가 됐다. dense가 "권한 이야기 비슷한 문단"을 가져오는 동안
BM25는 `read:packages`라는 **철자 그대로**를 찾는다 — 서로의 약점을 정확히 메운다.

---

## 2. ★ 하네스가 프로덕션 경로를 우회하고 있었다 ★

하이브리드를 다 붙이고 평가를 돌렸는데 **숫자가 소수점까지 똑같이 나왔다.**
원인은 `run_retrieval.py`가 이랬기 때문이다:

```python
chunks = store.search(embed_query(case.question), top_k)   # ← 잘못
```

`retriever.retrieve()`를 건너뛰고 store를 직접 부르고 있었다. 그러면 하이브리드 분기도
임베딩 짝 규칙도 전부 우회된다. **평가 하네스가 프로덕션 경로를 우회하면 개선을 측정할
수 없다** — 더 나쁘게는, "개선이 효과 없다"는 **틀린 결론**을 낸다.

`judge.py`는 처음부터 프로덕션 그래프(`app/graph.py`)를 그대로 돌리도록 만들었는데,
검색 층에서만 그 원칙을 어기고 있었다. 지금은 `retrieve()`를 부른다.

> M6에서 "하네스 자체를 검증하라"며 `--shuffle` 대조군을 만들었다. 그 검증은 **지표
> 계산**이 맞는지를 봤지, **하네스가 올바른 코드를 부르는지**는 못 봤다. 계측기의
> 검증에도 사각지대가 있다.

---

## 3. 설계 — `HybridStore`를 별도 프로토콜로 둔 이유

```python
class HybridStore(Protocol):
    def search_hybrid(self, query_vector, query_sparse, top_k, candidates): ...
```

`VectorStore`에 필수 메서드로 넣지 않았다. 하이브리드는 **모든 저장소가 할 수 있는 일이
아니기 때문**이다 — Qdrant는 한 컬렉션에 named vector로 dense/sparse를 두고 서버가
RRF로 융합해주지만, pgvector에는 그 개념이 없다(`tsvector` + `ts_rank`는 BM25가 아니라
다른 메커니즘이라 "같은 것을 구현했다"고 말할 수 없다).

필수로 넣었다면 pgvector가 `NotImplementedError`를 던지는 **"구현했지만 못 하는"** 상태가
된다. 별도 프로토콜이면 호출자가 `isinstance(store, HybridStore)`로 **능력을 물어보고
분기한다** — 없는 능력을 있는 척하지 않는다.

```
QdrantStore   VectorStore: True   HybridStore: True
PgVectorStore VectorStore: True   HybridStore: False
```

그래서 `vector_store=pgvector`로 되돌리면 하이브리드가 **조용히 dense로 내려간다.**
설정이 켜져 있다고 없는 능력을 만들어내지는 않는다.

---

## 4. 실측한 함정 4가지

1. **이름 없는 벡터는 named로 못 바꾼다.** 3-3c의 컬렉션은 이름 없는 dense 하나였는데,
   prefetch의 `using=`이 이름을 요구한다. `update_collection(sparse_vectors_config=)`로
   sparse를 **추가**하는 것은 되지만(실측), 기존 dense를 named로 바꾸는 것은 안 되므로
   **컬렉션 재생성 + 재인입**이 필요했다. README가 "먼저 확인하라"던 지점이 정확히 이것이다.
2. **`modifier=Modifier.IDF`가 없으면 조용히 망가진다.** fastembed의 BM25는 **원시 TF만**
   주고 IDF 가중은 Qdrant가 컬렉션 전체 통계로 계산한다. 이 한 줄을 빼면 에러 없이
   "흔한 단어일수록 중요"가 되어 순위가 무너진다.
3. **BM25도 query/passage가 비대칭이다.** `embed()`(문서, TF를 셈)와 `query_embed()`(질의,
   등장 여부만)가 다르다. e5의 `"passage: "`/`"query: "` 접두어와 같은 성질이고,
   짝을 어기면 여기서도 **에러 없이 품질만** 떨어진다.
4. **하이브리드의 `distance`는 코사인 거리가 아니다.** RRF 점수(순위의 역수 합, 보통
   0~0.03)를 `1 - score`로 뒤집은 값이라 1 근처에 몰린다. **정렬에는 쓸 수 있어도
   절대값 비교(임계값)에는 못 쓴다** — M6 하네스의 unanswerable 거리 분석이
   하이브리드에서 의미가 달라지는 이유다.

---

## 5. 저장소 기본값이 pgvector → qdrant로 바뀌었다

M3-4에 이렇게 적어뒀다:

> Qdrant가 값을 하기 시작하는 지점은 (a) 수백만 벡터 이상, (b) payload 필터가 무거워질 때,
> (c) **DB 레벨 하이브리드 검색**이다. → **M8에서 이 판단을 다시 한다.**

지금이 그때이고, **데이터가 정했다**: `pgvector(dense) 0.816` vs `qdrant(hybrid) 0.860`.

pgvector 구현은 그대로 남는다. 하이브리드가 필요 없는 환경(Postgres만 있는 서버)에서는
`VECTOR_STORE=pgvector` 한 줄로 되돌아가고, **그 선택지가 있다는 것 자체가 M3-3의 값이다.**

---

## 6. 다음 — 리랭킹

하이브리드는 **재현율** 담당이었다(top-30을 넉넉히 뽑아 융합). 다음은 **정밀도** —
Claude Haiku로 후보 순서를 바로잡는다.

예상: `hit@1`은 오르고 `hit@5`는 거의 안 바뀐다(정밀도 담당이므로). 다만 지금
`keyword`가 이미 MRR 1.000이라 **올릴 여지가 `normal`에만 있다**는 점이 M6 시작 때와
다른 조건이다.
