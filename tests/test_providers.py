"""Provider contracts: normalized schemas carry provenance; interfaces are abstract."""

from __future__ import annotations

import pytest

from sentinel_vantage.core.timeutils import utcnow
from sentinel_vantage.providers.base import Bar, MarketDataProvider


def test_bar_requires_feed_provenance():
    bar = Bar(
        symbol="XYZ",
        ts=utcnow(),
        timeframe="1m",
        open=1.0,
        high=2.0,
        low=0.9,
        close=1.5,
        volume=1000,
        provider="polygon",
        feed="polygon/delayed",
    )
    assert bar.provider == "polygon"
    assert bar.feed == "polygon/delayed"


def test_market_data_provider_is_abstract():
    with pytest.raises(TypeError):
        MarketDataProvider()  # type: ignore[abstract]
