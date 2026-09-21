"""The result envelope: every value leaving a service or MCP tool is wrapped with
provenance (as_of, provider/feed, model version, confidence). ``confidence`` is always
reported so a low score and a low-confidence score are distinguishable; ``None`` means
not a scored result."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from .timeutils import utcnow


class Provenance(BaseModel):
    """Where an output came from and how much to trust it."""

    as_of: datetime = Field(description="UTC instant the result was computed for.")
    provider: str = Field(description="Data-source provider, e.g. 'polygon'.")
    feed: str = Field(description="Feed provenance, e.g. 'polygon/delayed'.")
    model_version: str = Field(description="Version of the model that produced the result.")
    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="0-1 data-confidence; None for non-scored payloads.",
    )


class Envelope(BaseModel):
    """Provenance + payload. This is the shape MCP tools and services return."""

    provenance: Provenance
    data: Any


def make_envelope(
    *,
    data: Any,
    provider: str,
    feed: str,
    model_version: str,
    confidence: float | None = None,
    as_of: datetime | None = None,
) -> Envelope:
    return Envelope(
        provenance=Provenance(
            as_of=as_of or utcnow(),
            provider=provider,
            feed=feed,
            model_version=model_version,
            confidence=confidence,
        ),
        data=data,
    )
