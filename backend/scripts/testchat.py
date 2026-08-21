import json
import sys
import time

import httpx

URL = "http://localhost:8000/api/v1/chat"
DEFAULT_MESSAGE = "한국어로 짧게 자기소개 해줘"
DATA_PREFIX = "data: "


def main() -> None:
    args = sys.argv[1:]
    raw = "--raw" in args

    if raw:
        args.remove("--raw")
    message = args[0] if args else DEFAULT_MESSAGE

    print(f"POST {URL}")
    print(f"  message: {message}")
    print(f"  mode   : {'raw' if raw else 'parsed'}\n")

    started = time.perf_counter()
    print(started)

    # httpx.post()가 아니라 httpx.stream()을 써야 한다. post()는 본문을 전부 받은 뒤
    # 리턴하므로 서버가 스트리밍이든 아니든 결과가 똑같이 보인다.
    # timeout: httpx 기본 read timeout은 5초라, 첫 토큰이 늦으면 ReadTimeout이 난다.
    with httpx.stream(
        "POST",
        URL,
        json={"message": message},  # json=을 쓰면 UTF-8 인코딩과 Content-Type을 httpx가 처리한다
        timeout=httpx.Timeout(60.0),
    ) as response:
        # 헤더부터 확인. content-type이 text/event-stream이 아니면 스트리밍이 아니다.
        print(f"HTTP {response.status_code}")
        for name in ("content-type", "transfer-encoding", "cache-control", "x-accel-buffering"):
            if name in response.headers:
                print(f"  {name}: {response.headers[name]}")
        print()

        if response.status_code != 200:
            # 스트리밍 응답은 본문을 아직 읽지 않은 상태다. 에러 내용을 보려면 직접 read()해야 한다.
            print(response.read().decode("utf-8", errors="replace"))
            return

        chunks = 0
        first_at = None

        # iter_lines()는 개행이 제거된 문자열을 준다. SSE의 이벤트 구분자인 빈 줄은
        # 빈 문자열("")로 그대로 넘어온다.
        for line in response.iter_lines():
            elapsed_ms = (time.perf_counter() - started) * 1000

            if raw:
                # 파싱하지 않고 그대로 출력. 1b에서 캡처한 AI SDK 바이트와 비교할 때 이 모드를 쓴다.
                print(f"[{elapsed_ms:8.1f}ms] {line!r}")
                continue

            if not line:  # 이벤트 구분용 빈 줄
                continue

            if not line.startswith(DATA_PREFIX):
                print(f"\n[?] 예상치 못한 줄: {line!r}")
                continue

            data = line.removeprefix(DATA_PREFIX)

            # [DONE]은 JSON이 아니라 종료 센티넬이다. json.loads보다 먼저 걸러내야 한다.
            if data == "[DONE]":
                print(f"\n\n[{elapsed_ms:.1f}ms] [DONE] — 텍스트 청크 {chunks}개")
                break

            text = json.loads(data)["text"]
            chunks += 1
            if first_at is None:
                first_at = elapsed_ms
                print(f"(첫 토큰까지 {first_at:.1f}ms)\n")

            # flush=True가 없으면 파이썬이 stdout을 버퍼링해서 마지막에 한꺼번에 출력된다.
            # 서버는 정상인데 스트리밍이 안 되는 것처럼 보이는 대표적 오진 원인.
            print(text, end="", flush=True)


if __name__ == "__main__":
    main()
