"""Scheduler wiring for agent-written alert notes: builds the agent from settings, runs the
investigations, and tears everything down so an idle scheduler holds no LLM resources."""

from __future__ import annotations

from collections.abc import Sequence

from sentinel_vantage.agent.alert_investigator import INVESTIGATION_TOOLS, AlertInvestigator
from sentinel_vantage.agent.llm import build_llm
from sentinel_vantage.agent.runner import AgentRunner
from sentinel_vantage.agent.tools import MCPToolSource
from sentinel_vantage.apps.mcp_server.dependencies import MCPResources
from sentinel_vantage.apps.mcp_server.server import build_server
from sentinel_vantage.core.config import Settings
from sentinel_vantage.domain.alerts.models import AlertEvent
from sentinel_vantage.storage.agent_repos import PostgresAgentRunRepository


async def investigate_alerts(settings: Settings, events: Sequence[AlertEvent]) -> dict[str, str]:
    llm = build_llm(settings)
    resources = MCPResources.build(settings)
    await resources.connect()
    try:
        runs = PostgresAgentRunRepository(resources.db)
        runner = AgentRunner(
            llm,
            MCPToolSource(build_server(settings, resources=resources)),
            max_steps=5,
            max_total_tokens=settings.agent_max_total_tokens,
            allowed_tools=INVESTIGATION_TOOLS,
            runs=runs,
            backend=settings.llm_backend,
        )
        investigator = AlertInvestigator(
            runner,
            runs,
            min_severity=settings.agent_alert_min_severity,
            max_per_hour=settings.agent_alert_max_per_hour,
            max_per_cycle=settings.agent_alert_max_per_cycle,
        )
        return await investigator.investigate(events)
    finally:
        await llm.aclose()
        await resources.close()
