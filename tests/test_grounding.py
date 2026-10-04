"""Grounding check and the runner's one-shot revision when an answer fails it."""

from __future__ import annotations

from test_agent import FakeTools, ScriptedLLM, _call

from sentinel_vantage.agent.grounding import check_grounding
from sentinel_vantage.agent.llm import LLMResponse
from sentinel_vantage.agent.runner import AgentRunner

BRIEF = """{"data": {"as_of": "2026-10-02T04:00:00Z", "top_trending": [
 {"symbol": "TSLA", "trend_score": 89.8379, "reasons": ["ABNORMAL_VOLUME"]},
 {"symbol": "ORCL", "trend_score": 77.0144, "reasons": ["STRONG_MOMENTUM"]}]}}"""
ANALYZE = """{"data": {"result": {"score": 89.8379, "confidence": 1.0, "rank_percentile": 100.0,
 "metrics": {"return_1d_pct": 4.6539, "volume_ratio": 1.6745}}}}"""


def test_grounded_answer_passes():
    answer = (
        "As of Oct 2, 2026:\n"
        "1. **TSLA** – Trend Score 89.8 (confidence 1.0, 100th percentile): abnormal volume, "
        "up 4.7% on the day with volume 1.67x.\n"
        "2. **ORCL** – Trend Score 77.0: strong momentum."
    )
    report = check_grounding(answer, [BRIEF, ANALYZE])
    assert report.ok, report


def test_invented_number_flagged():
    report = check_grounding("TSLA scored 91.2 with +12.5% today.", [BRIEF, ANALYZE])
    assert report.ungrounded_numbers == ["91.2", "+12.5"]


def test_speculation_flagged_unless_tool_said_it():
    answer = "Abnormal volume typically signals institutional participation or capitulation."
    report = check_grounding(answer, [BRIEF])
    assert {p.lower() for p in report.speculative_phrases} == {
        "typically",
        "institutional",
        "capitulation",
    }
    assert check_grounding(answer, ["note: institutional typically capitulation"]).ok


def test_original_haiku_answer_would_have_failed():
    answer = (
        "TSLA stands out with abnormal volume, which typically signals institutional "
        "participation or capitulation moves."
    )
    assert not check_grounding(answer, [BRIEF]).ok


def test_dates_list_markers_versions_and_small_counts_ignored():
    answer = "1. Top 3 names as of 2026-10-02 under trend-v0 over the 20d window, 5 stocks."
    assert check_grounding(answer, [BRIEF]).ok


async def test_runner_asks_for_rewrite_once_then_accepts_grounded_answer():
    llm = ScriptedLLM(
        [
            _call(),
            LLMResponse("TSLA is 99.9, typically a breakout."),
            LLMResponse("TSLA: ok (no figures)."),
        ]
    )
    result = await AgentRunner(llm, FakeTools()).run("q")
    assert result.answer == "TSLA: ok (no figures)."
    assert result.grounding is not None and result.grounding.ok
    assert result.steps == 3
    feedback = llm.seen_messages[2][-1].text
    assert "grounding check" in feedback and "99.9" in feedback


async def test_runner_returns_flagged_answer_after_retries_exhausted():
    llm = ScriptedLLM([_call(), LLMResponse("It is 99.9."), LLMResponse("Still 88.8.")])
    result = await AgentRunner(llm, FakeTools()).run("q")
    assert result.stop_reason == "answered"
    assert result.grounding is not None and not result.grounding.ok
    assert result.answer == "Still 88.8."


async def test_runner_grounding_retry_disabled():
    llm = ScriptedLLM([_call(), LLMResponse("It is 99.9.")])
    result = await AgentRunner(llm, FakeTools(), grounding_retries=0).run("q")
    assert result.steps == 2 and result.grounding is not None and not result.grounding.ok
