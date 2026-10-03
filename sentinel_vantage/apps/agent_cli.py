"""Ask the agent a question: ``sv-agent "why is NVDA up?" [--allow-writes] [--max-steps N]``.
The LLM backend comes from SV_LLM_BACKEND (anthropic | openai_compat)."""

from __future__ import annotations

import argparse
import asyncio

from sentinel_vantage.agent.llm import LLMError, build_llm
from sentinel_vantage.agent.runner import AgentRunner
from sentinel_vantage.agent.tools import MCPToolSource
from sentinel_vantage.apps.mcp_server.dependencies import MCPResources
from sentinel_vantage.apps.mcp_server.server import build_server
from sentinel_vantage.core.config import get_settings
from sentinel_vantage.core.logging import configure_logging


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    resources = MCPResources.build(settings)
    await resources.connect()
    llm = build_llm(settings)
    try:
        runner = AgentRunner(
            llm,
            MCPToolSource(build_server(settings, resources=resources)),
            max_steps=args.max_steps or settings.agent_max_steps,
            max_total_tokens=settings.agent_max_total_tokens,
            allow_writes=args.allow_writes,
        )
        result = await runner.run(args.goal)
    except LLMError as exc:
        print(f"error: {exc}")
        return 1
    finally:
        await llm.aclose()
        await resources.close()

    print(result.answer)
    tools = ", ".join(t.name for t in result.tool_trace) or "none"
    print(
        f"\n[{result.stop_reason} · {result.steps} steps · tools: {tools} · "
        f"tokens {result.input_tokens}+{result.output_tokens} · {llm.model}]"
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="sv-agent")
    parser.add_argument("goal")
    parser.add_argument("--max-steps", type=int, default=0)
    parser.add_argument(
        "--allow-writes", action="store_true", help="permit create_watchlist / create_alert_rule"
    )
    args = parser.parse_args()
    configure_logging(level="WARNING")
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
