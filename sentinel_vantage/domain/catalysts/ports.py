"""Ports the catalyst service depends on."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol, runtime_checkable

from sentinel_vantage.domain.catalysts.models import Event


@runtime_checkable
class EventRepository(Protocol):
    async def save_events(self, events: Sequence[Event]) -> None: ...

    async def get_events(self, symbol: str, *, start: datetime, end: datetime) -> list[Event]: ...
