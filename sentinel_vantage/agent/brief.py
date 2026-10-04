"""Scheduled daily brief: an unattended, read-only agent run whose answer is delivered
through the configured notifier."""

from __future__ import annotations

from sentinel_vantage.agent.runner import AgentResult, AgentRunner
from sentinel_vantage.apps.scheduler.notify import Notifier
from sentinel_vantage.core.logging import get_logger

log = get_logger("brief")

BRIEF_KIND = "daily_brief"
BRIEF_SUBJECT = "Sentinel Vantage: daily brief"
BRIEF_TOOLS = frozenset(
    {
        "get_market_brief",
        "scan_trending_stocks",
        "find_research_candidates",
        "list_alert_events",
        "get_watchlist_changes",
        "analyze_stock",
        "explain_move",
    }
)
BRIEF_GOAL = (
    "Write today's market brief for a US-equities research desk. Start with get_market_brief, "
    "then investigate the one or two most notable names (top trend movers, new alerts, "
    "watchlist changes) with analyze_stock or explain_move. Keep it under 250 words: a "
    "one-line market summary, then a short bullet per name with its score, reason codes, "
    "and confidence. Note any data that is stale or missing."
)


async def run_daily_brief(runner: AgentRunner, notifier: Notifier | None) -> AgentResult:
    result = await runner.run(BRIEF_GOAL, kind=BRIEF_KIND)
    if result.stop_reason != "answered" or not result.answer.strip():
        log.error("brief.incomplete", reason=result.stop_reason, run_id=result.run_id)
        return result
    if notifier is not None:
        await notifier.send(BRIEF_SUBJECT, result.answer)
        log.info("brief.delivered", run_id=result.run_id)
    else:
        log.info("brief.generated_no_notifier", run_id=result.run_id)
    return result
