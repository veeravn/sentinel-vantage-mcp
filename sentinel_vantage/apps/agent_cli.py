"""Ask the agent a question: ``sv-agent "why is NVDA up?" [--allow-writes] [--max-steps N]``,
or run the daily brief now: ``sv-agent --brief [--send]``. The LLM backend comes from
SV_LLM_BACKEND (anthropic | openai_compat). Every run is logged to the agent_run table."""

from __future__ import annotations

import argparse
import asyncio

from sentinel_vantage.agent.brief import BRIEF_TOOLS, run_daily_brief
from sentinel_vantage.agent.llm import LLMError, build_llm
from sentinel_vantage.agent.runner import AgentRunner
from sentinel_vantage.agent.tools import MCPToolSource
from sentinel_vantage.apps.mcp_server.dependencies import MCPResources
from sentinel_vantage.apps.mcp_server.server import build_server
from sentinel_vantage.apps.scheduler.notify import build_notifier
from sentinel_vantage.core.config import get_settings
from sentinel_vantage.core.logging import configure_logging
from sentinel_vantage.storage.agent_repos import PostgresAgentRunRepository


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
            allow_writes=args.allow_writes and not args.brief,
            allowed_tools=BRIEF_TOOLS if args.brief else None,
            runs=PostgresAgentRunRepository(resources.db),
            backend=settings.llm_backend,
        )
        if args.brief:
            result = await run_daily_brief(runner, build_notifier(settings) if args.send else None)
        else:
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
    parser.add_argument("goal", nargs="?", default="")
    parser.add_argument("--max-steps", type=int, default=0)
    parser.add_argument(
        "--allow-writes", action="store_true", help="permit create_watchlist / create_alert_rule"
    )
    parser.add_argument("--brief", action="store_true", help="run the daily brief now")
    parser.add_argument("--send", action="store_true", help="with --brief, deliver via notifier")
    args = parser.parse_args()
    if not args.brief and not args.goal:
        parser.error("provide a goal, or use --brief")
    configure_logging(level="WARNING")
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
