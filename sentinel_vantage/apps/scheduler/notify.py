"""Alert delivery: format fired alerts and send them by email (SMTP) or a Slack-compatible
webhook. Selected by SV_NOTIFY_CHANNEL; disabled by default."""

from __future__ import annotations

import asyncio
import smtplib
from collections.abc import Sequence
from email.message import EmailMessage
from typing import Protocol

import httpx

from sentinel_vantage.core.config import Settings
from sentinel_vantage.core.logging import get_logger
from sentinel_vantage.domain.alerts.models import AlertEvent

log = get_logger("notify")


def format_alert_message(events: Sequence[AlertEvent]) -> tuple[str, str]:
    subject = f"Sentinel Vantage: {len(events)} alert(s)"
    lines = []
    for e in events:
        metrics = ", ".join(f"{k}={v}" for k, v in sorted(e.metrics.items()))
        line = f"[{e.severity}] {e.symbol} (rule {e.rule_id})"
        lines.append(f"{line} {metrics}".rstrip())
    return subject, "\n".join(lines)


class Notifier(Protocol):
    async def send(self, subject: str, body: str) -> None: ...


class EmailNotifier:
    def __init__(self, settings: Settings) -> None:
        self._s = settings

    async def send(self, subject: str, body: str) -> None:
        await asyncio.to_thread(self._send_sync, subject, body)

    def _send_sync(self, subject: str, body: str) -> None:
        s = self._s
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = s.smtp_from
        msg["To"] = s.smtp_to
        msg.set_content(body)
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=30) as smtp:
            if s.smtp_starttls:
                smtp.starttls()
            if s.smtp_username:
                smtp.login(s.smtp_username, s.smtp_password)
            smtp.send_message(msg)


class WebhookNotifier:
    def __init__(self, url: str, *, client: httpx.AsyncClient | None = None) -> None:
        self._url = url
        self._client = client

    async def send(self, subject: str, body: str) -> None:
        payload = {"text": f"*{subject}*\n{body}"}
        if self._client is not None:
            (await self._client.post(self._url, json=payload)).raise_for_status()
            return
        async with httpx.AsyncClient(timeout=15.0) as client:
            (await client.post(self._url, json=payload)).raise_for_status()


def build_notifier(settings: Settings) -> Notifier | None:
    channel = settings.notify_channel
    if channel == "email" and settings.smtp_host and settings.smtp_to:
        return EmailNotifier(settings)
    if channel == "webhook" and settings.webhook_url:
        return WebhookNotifier(settings.webhook_url)
    if channel != "none":
        log.warning("notify.misconfigured", channel=channel)
    return None
