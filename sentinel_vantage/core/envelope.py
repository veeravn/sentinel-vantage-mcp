"""The result envelope — the single output convention for the whole system.

Every value that leaves a domain service or an MCP tool is wrapped with provenance:
when it was computed (``as_of``), which provider/feed it came from, which model
version produced it, and how confident we are. This is what makes outputs auditable
and keeps stale or partial data from masquerading as a normal-confidence result.

Design rule (section 11): a *low score* and a *low-confidence score* are different
things. ``confidence`` is always reported so callers — including the LLM — can tell
them apart. ``None`` means "not a scored result" (e.g. a health payload).
"""

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
