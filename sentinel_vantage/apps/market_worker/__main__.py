"""Entrypoint: run the always-on market worker."""

from __future__ import annotations

import asyncio

from sentinel_vantage.apps.market_worker.worker import _run
from sentinel_vantage.core.config import get_settings
from sentinel_vantage.core.logging import configure_logging


def main() -> None:
    settings = get_settings()
    configure_logging(json=settings.environment == "production")
    asyncio.run(_run(settings))


if __name__ == "__main__":
    main()
