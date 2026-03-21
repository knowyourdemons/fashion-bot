#!/usr/bin/env python3
"""
Health check watchdog for Fashion Bot.

Checks the /health endpoint and worker heartbeats, sends Telegram alerts
when services are down and recovery notifications when they come back.

Environment variables:
    TELEGRAM_BOT_TOKEN   — Telegram bot token (required)
    ADMIN_TELEGRAM_ID    — Telegram chat ID for alerts (required)
    HEALTH_URL           — Health endpoint URL (default: http://localhost:8000/health)
    REDIS_URL            — Redis URL for worker heartbeat checks (default: redis://localhost:6379/0)
    CHECK_INTERVAL       — Seconds between checks (default: 30)
    FAILURE_THRESHOLD    — Consecutive failures before alert (default: 2)
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from urllib.error import URLError
from urllib.request import Request, urlopen

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ADMIN_TELEGRAM_ID = os.environ.get("ADMIN_TELEGRAM_ID", "")
HEALTH_URL = os.environ.get("HEALTH_URL", "http://localhost:8000/health")
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
CHECK_INTERVAL = int(os.environ.get("CHECK_INTERVAL", "30"))
FAILURE_THRESHOLD = int(os.environ.get("FAILURE_THRESHOLD", "2"))

WORKER_HEARTBEAT_KEYS = [
    "worker:heartbeat:fast_worker",
    "worker:heartbeat:slow_worker",
]
WORKER_HEARTBEAT_MAX_AGE = 120  # seconds

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

consecutive_failures: int = 0
alert_sent: bool = False
worker_alert_sent: dict[str, bool] = {k: False for k in WORKER_HEARTBEAT_KEYS}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def send_telegram(text: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not ADMIN_TELEGRAM_ID:
        log(f"WARN: Telegram not configured, would send: {text}")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = json.dumps({
        "chat_id": ADMIN_TELEGRAM_ID,
        "text": text,
        "parse_mode": "HTML",
    }).encode()
    req = Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=10) as resp:
            if resp.status != 200:
                log(f"WARN: Telegram API returned {resp.status}")
    except Exception as e:
        log(f"ERROR: Failed to send Telegram alert: {e}")


def check_health() -> tuple[int, dict]:
    """Returns (status_code, body_dict). On connection error returns (0, {})."""
    req = Request(HEALTH_URL, headers={"Accept": "application/json"})
    try:
        with urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read())
            return resp.status, body
    except URLError as e:
        return 0, {"error": str(e)}
    except Exception as e:
        return 0, {"error": str(e)}


def check_worker_heartbeats() -> dict[str, bool]:
    """Check Redis TTL keys for worker heartbeats. Returns {key: alive}."""
    results: dict[str, bool] = {}
    try:
        import redis as redis_lib
    except ImportError:
        log("WARN: redis package not installed, skipping worker heartbeat checks")
        return {}

    try:
        r = redis_lib.from_url(REDIS_URL, socket_connect_timeout=5, socket_timeout=5)
        for key in WORKER_HEARTBEAT_KEYS:
            ttl = r.ttl(key)
            # ttl > 0 means key exists and hasn't expired
            # ttl == -2 means key doesn't exist
            # ttl == -1 means key exists without expiry (shouldn't happen)
            alive = ttl is not None and ttl > 0
            results[key] = alive
        r.close()
    except Exception as e:
        log(f"WARN: Redis connection failed: {e}")
    return results


def failed_components(body: dict) -> list[str]:
    """Extract component names that are not 'ok'."""
    failed = []
    for key in ("redis", "db"):
        val = body.get(key, "unknown")
        if val != "ok":
            failed.append(f"{key}: {val}")
    return failed


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def run() -> None:
    global consecutive_failures, alert_sent, worker_alert_sent

    if not TELEGRAM_BOT_TOKEN:
        log("WARN: TELEGRAM_BOT_TOKEN not set, alerts will only go to stdout")
    if not ADMIN_TELEGRAM_ID:
        log("WARN: ADMIN_TELEGRAM_ID not set, alerts will only go to stdout")

    log(f"Watchdog started. URL={HEALTH_URL} interval={CHECK_INTERVAL}s threshold={FAILURE_THRESHOLD}")

    while True:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        # --- App health ---
        status, body = check_health()
        if status == 200 and body.get("status") == "ok":
            log(f"OK: status={status} body={body}")
            if alert_sent:
                send_telegram(
                    f"\u2705 Fashion Bot recovered!\n"
                    f"Status: healthy\n"
                    f"Time: {now}"
                )
                alert_sent = False
            consecutive_failures = 0
        else:
            consecutive_failures += 1
            components = failed_components(body)
            component_str = ", ".join(components) if components else "unreachable"
            log(f"FAIL #{consecutive_failures}: status={status} components={component_str}")

            if consecutive_failures >= FAILURE_THRESHOLD and not alert_sent:
                send_telegram(
                    f"\u26a0\ufe0f Fashion Bot health check failed!\n"
                    f"Status: {status or 'unreachable'}\n"
                    f"Component: {component_str}\n"
                    f"Time: {now}"
                )
                alert_sent = True

        # --- Worker heartbeats ---
        heartbeats = check_worker_heartbeats()
        for key, alive in heartbeats.items():
            short_name = key.split(":")[-1]
            if alive:
                if worker_alert_sent.get(key, False):
                    send_telegram(
                        f"\u2705 Worker <b>{short_name}</b> recovered!\n"
                        f"Time: {now}"
                    )
                    worker_alert_sent[key] = False
                log(f"Worker {short_name}: alive")
            else:
                log(f"Worker {short_name}: STALE (heartbeat missing or expired)")
                if not worker_alert_sent.get(key, False):
                    send_telegram(
                        f"\u26a0\ufe0f Worker <b>{short_name}</b> appears stuck!\n"
                        f"Heartbeat not updated within {WORKER_HEARTBEAT_MAX_AGE}s\n"
                        f"Time: {now}"
                    )
                    worker_alert_sent[key] = True

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        log("Watchdog stopped.")
        sys.exit(0)
