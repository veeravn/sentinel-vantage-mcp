"""Port for persisting feature snapshots.

Storing the feature inputs (not just the score) is what lets a past score be
reconstructed and backtested (design section 13). Kept as a Protocol so the domain
stays independent of storage.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from sentinel_vantage.domain.features.models import FeatureSet


@runtime_checkable
class FeatureRepository(Protocol):
    async def save_feature_snapshots(
        self, features: Sequence[FeatureSet], *, feature_set_version: str
    ) -> None: ...
