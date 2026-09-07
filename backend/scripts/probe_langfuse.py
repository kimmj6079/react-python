# M4 Langfuse 실측. 트레이싱을 배선하기 전에 "설치된 패키지의 표면이 실제로 어떻게
# 생겼는가"를 확인한다. probe_qdrant.py·probe_tools.py·probe_embedding.py와 같은 논리다.
#
# ★ 이번엔 실측이 특히 필요하다 ★ Langfuse 파이썬 SDK는 v2 → v3에서 아키텍처를
# OpenTelemetry 기반으로 갈아엎으면서 **import 경로와 CallbackHandler의 생성자가
# 통째로 바뀌었다.** 인터넷에 널린 예제는 대부분 v2 기준이라 그대로 베끼면
# ImportError나 TypeError가 난다. chatbot/README.md가 M4를 계획할 때 적어둔
# `langfuse.langchain.CallbackHandler`조차 "그 경로가 맞는지"를 여기서 확인해야 한다.
#
# 실행: cd backend && uv run python scripts/probe_langfuse.py
#
# 키가 .env에 있으면 ⑤에서 실제 trace를 한 번 보내고, 없으면 ①~④만 보고한다.
# 즉 키를 넣기 "전"과 "후"에 모두 쓸모가 있다.
import sys

sys.stdout.reconfigure(encoding="utf-8")


def title(text: str) -> None:
    print()
    print("=" * 72)
    print(text)
    print("=" * 72)


def main() -> None:
    import inspect

    import langchain
    import langfuse

    from app.core.config import settings

    title("① 버전 — 이 실측의 유효기간")
    print(f"  langfuse   {langfuse.__version__}")
    print(f"  langchain  {langchain.__version__}")
    print("  ※ langfuse는 v2 → v3에서 OpenTelemetry 기반으로 갈아엎었다.")
    print("     아래 결과는 v4 기준이고, 메이저가 바뀌면 전부 다시 재야 한다.")

    title("② import 경로 — v2 예제를 베끼면 여기서 죽는다")
    try:
        from langfuse.callback import CallbackHandler as _V2  # noqa: F401

        print("  langfuse.callback (v2 경로)      : 살아있음")
    except ImportError:
        print("  langfuse.callback (v2 경로)      : ★ 없음 ★ - 옛 예제는 전부 여기서 ImportError")

    from langfuse.langchain import CallbackHandler

    print("  langfuse.langchain (v3/v4 경로)  : OK")
    print(f"  실제 클래스: {CallbackHandler.__name__} (langchain 하위호환 별칭)")

    title("③ ★ 함정: langchain-core만으로는 안 된다 ★")
    print("  langfuse/langchain/CallbackHandler.py는 `import langchain` 후")
    print("  langchain.__version__.startswith('1')로 v0/v1을 분기한다.")
    print("  실제로 쓰는 심볼은 전부 langchain_core에 있는데도 메타 패키지가 필요하다.")
    print("  → 이 저장소는 langchain-anthropic만 있었으므로 `uv add langchain`이 필요했다.")
    print("  안 넣으면 ModuleNotFoundError가 아니라 친절한 메시지로 죽는다:")
    print('    "Please install langchain to use the Langfuse langchain integration"')

    title("④ ★ 핵심: CallbackHandler는 자격증명을 안 받는다 ★")
    print(f"  CallbackHandler.__init__{inspect.signature(CallbackHandler.__init__)}")
    print()
    print("  v2에서는 CallbackHandler(public_key=..., secret_key=..., host=...)였다.")
    print("  v3/v4에서는 자격증명이 Langfuse 클라이언트로 옮겨갔고, 핸들러는")
    print("  get_client()로 전역 싱글턴을 찾아 쓴다. 즉 배선이 두 단계다:")
    print("    1) Langfuse(public_key=..., secret_key=..., host=...) 를 한 번 만든다")
    print("    2) CallbackHandler() 를 만들어 RunnableConfig의 callbacks에 넣는다")
    print()
    sig = str(inspect.signature(langfuse.Langfuse.__init__))
    for chunk in sig.strip("()").split(", "):
        if any(k in chunk for k in ("public_key", "secret_key", "host", "base_url", "environment")):
            print(f"    Langfuse(... {chunk} ...)")

    title("⑤ 키가 없을 때 — 조용히 죽는가, 시끄럽게 죽는가")
    configured = bool(settings.langfuse_public_key and settings.langfuse_secret_key)
    print(f"  settings에 키가 있는가: {configured}")
    if not configured:
        print()
        print("  키 없이 CallbackHandler()를 만들어보면:")
        CallbackHandler()
        print()
        print("  ★ 예외가 아니라 stderr 경고 한 줄이고, 핸들러는 만들어진다 ★")
        print('    ("Authentication error: ... Client will be disabled")')
        print("  즉 키를 깜빡해도 앱은 정상 동작하고 트레이스만 조용히 안 쌓인다.")
        print("  → core/tracing.py가 '키가 없으면 아예 핸들러를 안 만든다'로 가는 이유다.")
        print("    (a) 저 경고가 요청마다 로그를 더럽히지 않고")
        print("    (b) '트레이싱이 켜졌는가'가 코드에서 boolean 하나로 분명해진다")
        print()
        print("  키를 넣은 뒤 이 스크립트를 다시 돌리면 ⑥에서 실제 전송까지 확인한다:")
        print("    1) https://cloud.langfuse.com 가입 → 프로젝트 생성 → API Keys")
        print("    2) backend/.env 에 LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY 추가")
        return

    title("⑥ 실제 전송 — auth_check + 트레이스 1건")
    from app.core.tracing import get_langfuse_client

    client = get_langfuse_client()
    print(f"  host: {settings.langfuse_host}")
    print(f"  auth_check(): {client.auth_check()}")

    handler = CallbackHandler()
    from langchain_core.prompts import ChatPromptTemplate

    chain = ChatPromptTemplate.from_template("{x}") | (lambda m: m.to_string())
    out = chain.invoke(
        {"x": "probe"},
        config={
            "callbacks": [handler],
            "metadata": {"langfuse_session_id": "probe-session"},
        },
    )
    print(f"  체인 결과: {out!r}")

    # ★ flush를 안 하면 스크립트가 끝나면서 배치가 날아간다 ★ 백그라운드 스레드가
    # 주기적으로 보내는 구조라, 짧은 스크립트에서는 보내기 전에 프로세스가 죽는다.
    # 장수하는 서버(uvicorn)에서는 필요 없다 - 이건 스크립트 특유의 함정이다.
    client.flush()
    print("  flush() 완료 → Langfuse 대시보드 Traces에 'probe-session'이 보여야 한다")


if __name__ == "__main__":
    main()
