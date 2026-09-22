"""Alert notification formatting and delivery backends."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx

from sentinel_vantage.apps.scheduler.notify import (
    EmailNotifier,
    WebhookNotifier,
    build_notifier,
    format_alert_message,
)
from sentinel_vantage.core.config import Settings
from sentinel_vantage.domain.alerts.models import AlertEvent


def _event(symbol, severity, **metrics):
    now = datetime(2026, 5, 1, tzinfo=UTC)
    return AlertEvent(
        event_id=f"e-{symbol}",
        rule_id="r1",
        symbol=symbol,
        as_of=now,
        severity=severity,
        fingerprint=f"r1|{symbol}",
        metrics=metrics,
        created_at=now,
    )


def test_format_alert_message():
    subject, body = format_alert_message(
        [_event("NVDA", "warning", trend_score=91.0, volume_ratio=3.0)]
    )
    assert subject == "Sentinel Vantage: 1 alert(s)"
    assert "[warning] NVDA (rule r1)" in body
    assert "trend_score=91.0" in body and "volume_ratio=3.0" in body


def test_build_notifier_selects_channel():
    assert build_notifier(Settings(notify_channel="none")) is None
    assert build_notifier(Settings(notify_channel="webhook")) is None  # url missing
    assert build_notifier(Settings(notify_channel="email")) is None  # host/to missing
    assert isinstance(
        build_notifier(Settings(notify_channel="webhook", webhook_url="https://hook")),
        WebhookNotifier,
    )
    assert isinstance(
        build_notifier(Settings(notify_channel="email", smtp_host="mail", smtp_to="me@x")),
        EmailNotifier,
    )


async def test_webhook_notifier_posts_payload():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["json"] = json.loads(request.content)
        return httpx.Response(200)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await WebhookNotifier("https://hooks.example/svc", client=client).send("subj", "line1")
    assert captured["url"] == "https://hooks.example/svc"
    assert captured["json"]["text"] == "*subj*\nline1"
    await client.aclose()


async def test_email_notifier_sends(monkeypatch):
    sent: dict = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=30):
            sent["host"] = host
            sent["port"] = port

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            sent["tls"] = True

        def login(self, user, password):
            sent["login"] = (user, password)

        def send_message(self, msg):
            sent["to"] = msg["To"]
            sent["subject"] = msg["Subject"]

    monkeypatch.setattr("sentinel_vantage.apps.scheduler.notify.smtplib.SMTP", FakeSMTP)
    settings = Settings(
        notify_channel="email",
        smtp_host="mail",
        smtp_to="me@example.com",
        smtp_from="sv@example.com",
        smtp_username="u",
        smtp_password="p",
    )
    await EmailNotifier(settings).send("subj", "body")
    assert sent["host"] == "mail"
    assert sent["to"] == "me@example.com"
    assert sent["subject"] == "subj"
    assert sent["tls"] is True
    assert sent["login"] == ("u", "p")
