"""CatalystService — detect a notable move and correlate it with nearby events.

Implements the ``explain_move`` use case: find the largest recent price move, describe
it (magnitude, direction, abnormal volume), then attach ranked catalyst evidence from
stored events. It labels a causal confidence but never asserts causation.
"""

from __future__ import annotations

import statistics
from datetime import datetime, timedelta

from sentinel_vantage.core.logging import get_logger
from sentinel_vantage.domain.catalysts.correlator import correlate
from sentinel_vantage.domain.catalysts.models import CatalystEvidence, ExplainMove, MoveSummary
from sentinel_vantage.domain.catalysts.ports import EventRepository
from sentinel_vantage.domain.trend.ports import BarRepository

log = get_logger("catalyst_service")

_STRENGTH_RANK = {"weak": 1, "moderate": 2, "strong": 3}


def _detect_move(bars, lookback: int):
    """Return (move_ts, return_pct, volume_ratio, direction) for the largest-magnitude
    1-day move within the last ``lookback`` bars, or None."""
    if len(bars) < 2:
        return None
    b = sorted(bars, key=lambda x: x.ts)
    closes = [x.close for x in b]
    vols = [x.volume for x in b]
    # Daily returns aligned to index i (move on day i).
    best = None  # (abs_ret, i)
    start = max(1, len(b) - lookback)
    for i in range(start, len(b)):
        if closes[i - 1] == 0:
            continue
        ret = closes[i] / closes[i - 1] - 1.0
        if best is None or abs(ret) > best[0]:
            best = (abs(ret), i, ret)
    if best is None:
        return None
    _, i, ret = best
    baseline = [v for v in vols[max(0, i - 20) : i] if v > 0]
    vol_ratio = (vols[i] / statistics.median(baseline)) if baseline else None
    return b[i].ts, ret, vol_ratio, ("up" if ret >= 0 else "down")


class CatalystService:
    def __init__(self, bars: BarRepository, events: EventRepository) -> None:
        self.bars = bars
        self.events = events

    async def explain_move(
        self,
        symbol: str,
        *,
        as_of: datetime,
        lookback_days: int = 20,
        window_days: float = 5.0,
    ) -> ExplainMove:
        histories = await self.bars.get_daily_history(
            [symbol], as_of, lookback_days=lookback_days + 30
        )
        bars = histories.get(symbol, [])
        detected = _detect_move(bars, lookback_days)
        if detected is None:
            return ExplainMove(symbol=symbol, as_of=as_of)

        move_ts, ret, vol_ratio, direction = detected
        move = MoveSummary(
            symbol=symbol,
            move_date=move_ts,
            return_pct=round(ret * 100, 4),
            volume_ratio=round(vol_ratio, 4) if vol_ratio is not None else None,
            direction=direction,
        )

        events = await self.events.get_events(
            symbol,
            start=move_ts - timedelta(days=window_days + 1),
            end=move_ts + timedelta(days=1),
        )
        catalysts: list[CatalystEvidence] = correlate(
            symbol, move_ts, events, window_days=window_days
        )
        causal = "none"
        if catalysts:
            best = max(_STRENGTH_RANK[c.evidence_strength] for c in catalysts)
            causal = {1: "weak", 2: "moderate", 3: "strong"}[best]

        log.info(
            "catalyst.explain_move", symbol=symbol, move=move.return_pct, catalysts=len(catalysts)
        )
        return ExplainMove(
            symbol=symbol, as_of=as_of, move=move, catalysts=catalysts, causal_confidence=causal
        )
