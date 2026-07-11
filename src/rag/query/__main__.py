from __future__ import annotations

import argparse
import asyncio
import sys

from query.wiring import build_mock


async def _run(
    tenant_id: str,
    text: str,
    service_kind: str = "mock",
    verbose: bool = False,
    bypass_cache: bool = False,
) -> int:
    if service_kind == "production":
        from query.wiring import build_production

        service = build_production()
    else:
        service = build_mock()
    answer = await service.query(tenant_id, text, bypass_cache=bypass_cache)
    print(answer.text)
    intent = answer.intent.intent.value if answer.intent else "?"
    source = answer.intent.source if answer.intent else "?"
    tier = answer.tier.value if answer.tier else "-"
    flags = []
    if answer.cached:
        flags.append("cached")
    if answer.degraded_level:
        flags.append(f"degraded={answer.degraded_level}")
    print(
        f"\n[intent={intent} source={source} tier={tier}"
        + (" " + " ".join(flags) if flags else "")
        + "]"
    )
    if answer.trace is not None:
        t = answer.trace
        print(f"[request_id={t.request_id}]")
        print(f"[hops={t.hop_latency_ms}]")
        print(f"[doc_ids={t.retrieved_doc_ids}]")
        if verbose:
            print(f"\n===== 检索结果 ({len(t.contexts)} chunks) =====")
            for i, chunk in enumerate(t.contexts):
                print(f"--- chunk[{i}] ---\n{chunk}")
            print("\n===== 发送给 LLM 的 Prompt =====")
            print(t.prompt if t.prompt else "(无：本次未调用 LLM，可能命中缓存或触发降级)")
    return 0


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        prog="query",
        description="Run one user query end-to-end (mock by default; --service production for live infra).",
    )
    parser.add_argument("text", help="the user query text")
    parser.add_argument("--tenant", default="t1", help="tenant id (default: t1)")
    parser.add_argument(
        "--service",
        choices=["mock", "production"],
        default="mock",
        help="which QueryService to run (default: mock; production wires live infra)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="also print retrieved chunk contents and the exact prompt sent to the LLM",
    )
    parser.add_argument(
        "--bypass-cache",
        action="store_true",
        help="skip the semantic cache so the full retrieve+generate path always runs",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(args.tenant, args.text, args.service, args.verbose, args.bypass_cache)))


if __name__ == "__main__":
    main()
