"""Scheduled daily brief: an unattended, read-only agent run whose answer is delivered
through the configured notifier."""

from __future__ import annotations

import re

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
    "watchlist changes) with analyze_stock or explain_move. Keep it under 250 words. "
    "Start with a neutral title line like 'Daily brief - as of <date>', then one line on "
    "what the data shows, then a short line per name with its score, reason codes, and "
    "confidence. Do not characterize sectors, themes, or groups of stocks (the tools return "
    "no sector data), and do not describe what the market is 'doing' beyond the scores. "
    "Note any data that is stale or missing. Output plain text only: no markdown headings, "
    "bold, horizontal rules, or tables; use '- ' for bullets."
)

_MD_RULE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$", re.M)
_MD_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*", re.M)


def to_plain_text(text: str) -> str:
    """Strip markdown that notifier channels (webhooks, email) won't render."""
    text = _MD_RULE.sub("", text)
    text = _MD_HEADING.sub("", text)
    text = text.replace("**", "").replace("__", "")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


async def run_daily_brief(runner: AgentRunner, notifier: Notifier | None) -> AgentResult:
    result = await runner.run(BRIEF_GOAL, kind=BRIEF_KIND)
    if result.stop_reason != "answered" or not result.answer.strip():
        log.error("brief.incomplete", reason=result.stop_reason, run_id=result.run_id)
        return result
    if notifier is not None:
        await notifier.send(BRIEF_SUBJECT, to_plain_text(result.answer))
        log.info("brief.delivered", run_id=result.run_id)
    else:
        log.info("brief.generated_no_notifier", run_id=result.run_id)
    return result
