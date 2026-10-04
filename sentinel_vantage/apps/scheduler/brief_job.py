"""Scheduler job wiring for the daily brief: builds the agent from settings, runs it, and
tears everything down so an idle scheduler holds no LLM or MCP resources."""

from __future__ import annotations

from sentinel_vantage.agent.brief import BRIEF_TOOLS, run_daily_brief
from sentinel_vantage.agent.llm import build_llm
from sentinel_vantage.agent.runner import AgentResult, AgentRunner
from sentinel_vantage.agent.tools import MCPToolSource
from sentinel_vantage.apps.mcp_server.dependencies import MCPResources
from sentinel_vantage.apps.mcp_server.server import build_server
from sentinel_vantage.apps.scheduler.notify import Notifier
from sentinel_vantage.core.config import Settings
from sentinel_vantage.storage.agent_repos import PostgresAgentRunRepository


async def run_brief_job(settings: Settings, notifier: Notifier | None) -> AgentResult:
    resources = MCPResources.build(settings)
    await resources.connect()
    llm = build_llm(settings)
    try:
        runner = AgentRunner(
            llm,
            MCPToolSource(build_server(settings, resources=resources)),
            max_steps=settings.agent_max_steps,
            max_total_tokens=settings.agent_max_total_tokens,
            allowed_tools=BRIEF_TOOLS,
            runs=PostgresAgentRunRepository(resources.db),
            backend=settings.llm_backend,
        )
        return await run_daily_brief(runner, notifier)
    finally:
        await llm.aclose()
        await resources.close()
