"""Port (Protocol) for persisting feature snapshots, so a past score can be reconstructed
and backtested from its inputs."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from sentinel_vantage.domain.features.models import FeatureSet


@runtime_checkable
class FeatureRepository(Protocol):
    async def save_feature_snapshots(
        self, features: Sequence[FeatureSet], *, feature_set_version: str
    ) -> None: ...
