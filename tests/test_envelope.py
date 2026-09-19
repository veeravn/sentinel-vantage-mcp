"""The output envelope is the system's core convention — lock its shape."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from sentinel_vantage.core.envelope import make_envelope


def test_envelope_carries_full_provenance():
    env = make_envelope(
        data={"symbol": "XYZ", "trend_score": 91.4},
        provider="polygon",
        feed="polygon/delayed",
        model_version="trend-v0",
        confidence=0.94,
    )
    p = env.provenance
    assert p.provider == "polygon"
    assert p.feed == "polygon/delayed"
    assert p.model_version == "trend-v0"
    assert p.confidence == 0.94
    assert p.as_of.tzinfo is not None  # always timezone-aware
    assert env.data["symbol"] == "XYZ"


def test_confidence_is_optional_for_non_scored_payloads():
    env = make_envelope(
        data={"ok": True},
        provider="polygon",
        feed="polygon/delayed",
        model_version="n/a",
    )
    assert env.provenance.confidence is None


@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_confidence_is_bounded_zero_to_one(bad):
    with pytest.raises(ValidationError):
        make_envelope(
            data={},
            provider="polygon",
            feed="polygon/delayed",
            model_version="trend-v0",
            confidence=bad,
        )


def test_json_mode_serializes_timestamp():
    env = make_envelope(data={}, provider="polygon", feed="polygon/delayed", model_version="n/a")
    dumped = env.model_dump(mode="json")
    assert "provenance" in dumped and "as_of" in dumped["provenance"]
    assert isinstance(dumped["provenance"]["as_of"], str)
