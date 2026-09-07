# M3-3b Qdrant 실측. 3-3c에서 QdrantStore를 쓰기 전에 "설치된 패키지가 실제로 무엇을
# 돌려주는가"를 눈으로 확인한다. M1-1b(AI SDK 와이어 캡처)·2c-1(도구 API)·3-1(임베딩)과
# 같은 논리다 — 문서를 암기해 타이핑하지 말고 설치된 패키지에게 직접 묻는다.
#
# 실행:
#   docker compose up -d qdrant          # 프로젝트 루트에서
#   cd backend && uv run python scripts/probe_qdrant.py
#
# ★ 임베딩 모델을 부르지 않는다 ★ 4차원 가짜 벡터를 쓴다. 알고 싶은 건 "Qdrant API가
# 어떻게 생겼나" 하나뿐이라 미지수를 그것만 남긴다 — 1b에서 가짜 LLM을 쓴 것과 같은 이유다.
# 덤으로 2.24GB 모델 로딩이 빠져서 실행이 1초 안에 끝나고, 결과가 매번 똑같다.
import sys
import uuid

import numpy as np
from qdrant_client import QdrantClient, models

sys.stdout.reconfigure(encoding="utf-8")

URL = "http://localhost:6333"
COLLECTION = "probe_docs"
DIM = 4

# 가짜 문서 3개. 벡터는 손으로 적어서 유사도를 예측 가능하게 만든다.
# 질문 벡터를 [1,0,0,0]으로 둘 것이므로, 첫 번째가 가장 가깝고 세 번째가 가장 멀다.
DOCS = [
    ("a.md", 0, "첫 번째 문서의 0번 청크", [1.0, 0.0, 0.0, 0.0]),
    ("a.md", 1, "첫 번째 문서의 1번 청크", [0.8, 0.6, 0.0, 0.0]),
    ("b.md", 0, "두 번째 문서의 0번 청크", [0.0, 1.0, 0.0, 0.0]),
]
QUERY_VECTOR = [1.0, 0.0, 0.0, 0.0]


def title(text: str) -> None:
    print()
    print("=" * 72)
    print(text)
    print("=" * 72)


def point_id(source: str, chunk_index: int) -> str:
    # ★ 이 함수가 3-3b 실측의 최대 수확이다 ★
    # Qdrant의 point id는 "부호 없는 정수 또는 UUID"만 허용한다. pgvector에서 쓰던
    # "a.md#0" 같은 자연 키를 그대로 넣으면 거부당한다(아래 ③에서 실제로 확인).
    # uuid5는 (네임스페이스, 이름) -> UUID가 항상 같은 결정론적 해시라, 같은 청크가
    # 항상 같은 id를 갖는다 = 재인입이 덮어쓰기(upsert)가 된다. uuid4를 쓰면 매번
    # 다른 id가 나와서 같은 문서를 넣을 때마다 중복이 쌓인다.
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{source}#{chunk_index}"))


def cosine(a: list[float], b: list[float]) -> float:
    va, vb = np.array(a), np.array(b)
    return float(np.dot(va, vb) / (np.linalg.norm(va) * np.linalg.norm(vb)))


def main() -> None:
    # ★ timeout을 반드시 명시한다 ★ 기본값은 None(= 라이브러리 기본, REST는 5초지만
    # 버전에 따라 다르다)이라 "느려질 때 어떻게 되는가"가 불확실해진다. graph.py의
    # retrieve 노드는 asyncio.to_thread로 도는데, 여기서 오래 매달리면 스레드 풀이
    # 통째로 막혀서 3-2b가 이벤트 루프를 지키려고 만든 방어가 무력해진다.
    client = QdrantClient(url=URL, timeout=5)

    title("① 접속 + 버전")
    # 서버 버전과 클라이언트 버전이 크게 어긋나면 경고가 뜬다(호환성 체크가 내장).
    print(f"  컬렉션 목록: {[c.name for c in client.get_collections().collections]}")

    title("② 컬렉션 만들기 — 차원과 거리 함수를 여기서 못 박는다")
    if client.collection_exists(COLLECTION):
        client.delete_collection(COLLECTION)
    client.create_collection(
        collection_name=COLLECTION,
        vectors_config=models.VectorParams(size=DIM, distance=models.Distance.COSINE),
    )
    info = client.get_collection(COLLECTION)
    print(
        f"  vectors_config: size={info.config.params.vectors.size} "
        f"distance={info.config.params.vectors.distance}"
    )
    print(f"  points_count={info.points_count}  status={info.status}")
    print("  ※ pgvector는 vector(1024) 컬럼 타입 + 마이그레이션이 필요했지만,")
    print("     Qdrant는 런타임 API 한 번으로 만든다 = 스키마 마이그레이션이 없다.")

    title("③ point id 규칙 — 문자열 자연 키가 되는가?")
    try:
        client.upsert(
            collection_name=COLLECTION,
            points=[models.PointStruct(id="a.md#0", vector=QUERY_VECTOR, payload={})],
        )
        print("  문자열 id 허용됨 (예상 밖)")
    except Exception as exc:  # noqa: BLE001 - 실측 스크립트라 무엇이 터지든 보고 싶다
        print(f"  ★ 거부됨: {type(exc).__name__}")
        print(f"    {str(exc).splitlines()[0][:160]}")
        print("    → Qdrant의 id는 unsigned int 또는 UUID뿐이다.")
        print("      pgvector의 (source, chunk_index) 자연 키를 그대로 쓸 수 없으므로")
        print("      uuid5로 결정론적 UUID를 만들어야 재인입이 덮어쓰기가 된다.")

    title("④ upsert — 결정론적 UUID로 3개 넣기")
    points = [
        models.PointStruct(
            id=point_id(src, idx),
            vector=vec,
            # ★ payload = pgvector에서 원문·메타데이터 컬럼이 하던 일 ★
            # 벡터는 비가역이라 원문을 같이 저장해야 한다는 원칙(3-1)은 저장소가
            # 바뀌어도 그대로다. Qdrant는 스키마가 없어서 dict를 그냥 넣는다.
            payload={"source": src, "chunk_index": idx, "content": text},
        )
        for src, idx, text, vec in DOCS
    ]
    result = client.upsert(collection_name=COLLECTION, points=points)
    print(f"  반환: {type(result).__name__}  {result}")
    print(f"  count(): {client.count(COLLECTION).count}")
    print("  ※ 같은 id로 다시 넣으면 덮어쓴다 — 아래에서 확인")
    client.upsert(collection_name=COLLECTION, points=points)
    print(f"  같은 points를 한 번 더 upsert한 뒤 count(): {client.count(COLLECTION).count}")

    title("⑤ 검색 — query_points가 무엇을 돌려주는가")
    response = client.query_points(
        collection_name=COLLECTION, query=QUERY_VECTOR, limit=3, with_payload=True
    )
    print(f"  반환 타입: {type(response).__name__}  (리스트가 아니라 .points를 꺼내야 한다)")
    print(f"  .points 원소 타입: {type(response.points[0]).__name__}")
    print()
    print("  rank  score    1-score   손계산 cosine  payload")
    for rank, p in enumerate(response.points, start=1):
        src, idx = p.payload["source"], p.payload["chunk_index"]
        expected = cosine(QUERY_VECTOR, dict(((s, i), v) for s, i, _, v in DOCS)[(src, idx)])
        print(
            f"  [{rank}]   {p.score:.4f}   {1 - p.score:.4f}    {expected:.4f}        {src}#{idx}"
        )
    print()
    print("  ★ score는 '유사도'다 — 높을수록 가깝다. pgvector의 cosine_distance와 반대다.")
    print("    코사인에서 distance = 1 - score 가 정확히 성립하므로(위 열 비교),")
    print("    3-3c의 QdrantStore가 1 - score로 변환해 RetrievedChunk.distance에 맞춘다.")

    title("⑥ 필터로 세기 / 지우기 — 멱등 인입에 필요한 두 가지")
    flt = models.Filter(
        must=[models.FieldCondition(key="source", match=models.MatchValue(value="a.md"))]
    )
    print(f"  count(source='a.md') = {client.count(COLLECTION, count_filter=flt).count}")
    print("  ※ payload 인덱스를 안 만들어도 필터가 동작한다(전수 스캔). 데이터가")
    print("     커지면 create_payload_index가 필요해진다 — M12에서 다시 나온다.")

    deleted = client.delete(
        collection_name=COLLECTION, points_selector=models.FilterSelector(filter=flt)
    )
    print(f"  delete 반환: {type(deleted).__name__}  {deleted}")
    print("  ★ 삭제된 '개수'가 없다 — pgvector의 rowcount와 다른 지점이다.")
    print("    upsert_document가 '지운 개수'를 돌려주기로 한 계약(base.py)을 지키려면")
    print("    지우기 전에 count를 한 번 더 불러야 한다. 계약이 한쪽만 싸게 줄 수 있는")
    print("    값을 요구할 때 생기는 비용이고, 알고 넣은 것이다.")
    print(f"  삭제 후 전체 count = {client.count(COLLECTION).count}")

    title("⑦ 없는 컬렉션을 검색하면?")
    try:
        client.query_points(collection_name="no_such_collection", query=QUERY_VECTOR, limit=1)
    except Exception as exc:  # noqa: BLE001
        print(f"  {type(exc).__name__}: {str(exc).splitlines()[0][:140]}")
        print("  → 조용히 빈 결과가 아니라 예외다. 3-3c에서 '없으면 만든다'를")
        print("     명시적으로 해줘야 한다(pgvector는 alembic이 하던 일).")

    client.delete_collection(COLLECTION)
    print(f"\n정리 완료 — {COLLECTION} 삭제됨\n")


if __name__ == "__main__":
    main()
