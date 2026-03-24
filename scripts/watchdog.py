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
ADMIN_TELEGRAM_ID = os.environ.get("ADMIN_TELEGRAM_ID", "") or os.environ.get("ADMIN_TELEGRAM_IDS", "").split(",")[0]
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
worker_stale_since: dict[str, float] = {}  # key -> first_stale_time
worker_last_realert: dict[str, float] = {}  # key -> last_realert_time
WORKER_REALERT_INTERVAL = 1800  # re-alert every 30 min

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


def _resolve_redis_url() -> str:
    """Re-resolve Redis container IP (it changes on container recreation)."""
    import subprocess
    try:
        result = subprocess.run(
            ["docker", "inspect", "-f",
             "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
             "docker-redis-1"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return f"redis://{result.stdout.strip()}:6379/0"
    except Exception:
        pass
    return REDIS_URL


def check_worker_heartbeats() -> dict[str, bool]:
    """Check Redis TTL keys for worker heartbeats. Returns {key: alive}."""
    results: dict[str, bool] = {}
    try:
        import redis as redis_lib
    except ImportError:
        log("WARN: redis package not installed, skipping worker heartbeat checks")
        return {}

    # Re-resolve Redis IP each time (container IP may change after restart)
    redis_url = _resolve_redis_url()
    try:
        r = redis_lib.from_url(redis_url, socket_connect_timeout=5, socket_timeout=5)
        for key in WORKER_HEARTBEAT_KEYS:
            ttl = r.ttl(key)
            # ttl > 0 means key exists and hasn't expired
            # ttl == -2 means key doesn't exist
            # ttl == -1 means key exists without expiry (shouldn't happen)
            alive = ttl is not None and ttl > 0
            results[key] = alive
        r.close()
    except Exception as e:
        log(f"WARN: Redis connection failed ({redis_url}): {e}")
    return results


def failed_components(body: dict) -> list[str]:
    """Extract component names that are not 'ok'."""
    failed = []
    for key in ("redis", "db"):
        val = body.get(key, "unknown")
        if val != "ok":
            failed.append(f"{key}: {val}")
    return failed


# State for restart loop detection
container_restart_alerted: set[str] = set()
# State for OOM / high-restart detection: {container: last_alert_time}
container_oom_alerted: dict[str, float] = {}
# Known restart counts to detect increases
container_restart_counts: dict[str, int] = {}

OOM_REALERT_INTERVAL = 1800  # re-alert every 30 min if OOM persists
RESTART_COUNT_THRESHOLD = 3  # alert when restarts exceed this

MONITORED_CONTAINERS = [
    "docker-app-1",
    "docker-worker-1",
    "docker-renderer-1",
]

# --- Auto-scale memory ---
MEMORY_HIGH_THRESHOLD = 0.80  # bump when usage > 80% of limit
MEMORY_BUMP_MB = 512          # add 512MB per bump
MEMORY_MAX_MB = 3072          # absolute cap per container (3GB)
VPS_RESERVE_MB = 1024         # always keep 1GB free on host
# Track bumps to avoid spamming
memory_bumped: dict[str, float] = {}  # container -> last_bump_time
MEMORY_BUMP_COOLDOWN = 300    # min 5 min between bumps per container


def check_container_health() -> None:
    """Check if any containers are in a restart loop and alert."""
    import subprocess
    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}} {{.Status}}"],
            capture_output=True, text=True, timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        log(f"WARN: docker ps failed: {e}")
        return

    if result.returncode != 0:
        log(f"WARN: docker ps returned {result.returncode}")
        return

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    current_restarting: set[str] = set()

    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        if "Restarting" in line:
            container = line.split()[0]
            current_restarting.add(container)

            if container not in container_restart_alerted:
                # Get last 5 lines of logs for context
                try:
                    logs = subprocess.run(
                        ["docker", "logs", "--tail", "5", container],
                        capture_output=True, text=True, timeout=10,
                    )
                    log_tail = (logs.stderr or logs.stdout or "")[-200:]
                except Exception:
                    log_tail = "(could not fetch logs)"

                alert_text = (
                    f"\U0001f504 <b>{container}</b> в restart loop!\n\n"
                    f"Последние логи:\n<pre>{log_tail}</pre>\n"
                    f"Time: {now}"
                )
                send_telegram(alert_text)
                container_restart_alerted.add(container)
                log(f"Container {container}: RESTARTING — alert sent")

    # Recovery: container was restarting but is no longer
    recovered = container_restart_alerted - current_restarting
    for container in recovered:
        send_telegram(
            f"\u2705 <b>{container}</b> recovered from restart loop!\n"
            f"Time: {now}"
        )
        container_restart_alerted.discard(container)
        log(f"Container {container}: recovered from restart loop")

    # --- OOM and RestartCount detection via docker inspect ---
    _check_oom_and_restarts(now)


def _check_oom_and_restarts(now: str) -> None:
    """Check docker inspect for OomKilled flag and high RestartCount."""
    import subprocess

    for container in MONITORED_CONTAINERS:
        try:
            result = subprocess.run(
                [
                    "docker", "inspect",
                    "--format",
                    "{{.State.OOMKilled}} {{.RestartCount}} {{.HostConfig.Memory}}",
                    container,
                ],
                capture_output=True, text=True, timeout=10,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            continue

        if result.returncode != 0:
            continue

        parts = result.stdout.strip().split()
        if len(parts) < 3:
            continue

        oom_killed = parts[0].lower() == "true"
        try:
            restart_count = int(parts[1])
        except ValueError:
            restart_count = 0
        try:
            mem_limit_bytes = int(parts[2])
            mem_limit_mb = mem_limit_bytes // (1024 * 1024)
        except ValueError:
            mem_limit_mb = 0

        prev_count = container_restart_counts.get(container, 0)
        container_restart_counts[container] = restart_count

        current_time = time.time()
        last_alert = container_oom_alerted.get(container, 0)
        should_alert = current_time - last_alert > OOM_REALERT_INTERVAL

        # Detect OOM kill
        if oom_killed and should_alert:
            alert_text = (
                f"\U0001f4a5 <b>{container}</b> OOM Killed!\n"
                f"Memory limit: {mem_limit_mb}MB\n"
                f"Restarts: {restart_count}\n"
                f"Time: {now}\n\n"
                f"Нужно увеличить memory limit в docker-compose.yml"
            )
            send_telegram(alert_text)
            container_oom_alerted[container] = current_time
            log(f"Container {container}: OOM KILLED — alert sent (restarts={restart_count})")

        # Detect restart count spike (new restarts since last check)
        elif restart_count > prev_count and restart_count > RESTART_COUNT_THRESHOLD and should_alert:
            delta = restart_count - prev_count
            alert_text = (
                f"\U0001f504 <b>{container}</b> перезапустился {delta}x за последний цикл!\n"
                f"Всего рестартов: {restart_count}\n"
                f"Memory limit: {mem_limit_mb}MB\n"
                f"Time: {now}"
            )
            send_telegram(alert_text)
            container_oom_alerted[container] = current_time
            log(f"Container {container}: restart spike +{delta} (total={restart_count})")

        # Recovery: OOM was alerted before, now cleared
        elif not oom_killed and container in container_oom_alerted and restart_count == prev_count:
            if last_alert > 0:
                send_telegram(
                    f"\u2705 <b>{container}</b> стабилен, OOM больше нет.\n"
                    f"Time: {now}"
                )
                del container_oom_alerted[container]
                log(f"Container {container}: OOM recovered")


def _auto_scale_memory(now: str) -> None:
    """Bump container memory limit when usage exceeds threshold.
    Uses `docker stats` for usage and `docker update --memory` to resize live."""
    import subprocess

    # Check host free memory first
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    host_avail_mb = int(line.split()[1]) // 1024
                    break
            else:
                return
    except Exception:
        return

    if host_avail_mb < VPS_RESERVE_MB:
        log(f"auto_scale: host only {host_avail_mb}MB free, skipping (reserve={VPS_RESERVE_MB}MB)")
        return

    current_time = time.time()

    for container in MONITORED_CONTAINERS:
        # Cooldown check
        if current_time - memory_bumped.get(container, 0) < MEMORY_BUMP_COOLDOWN:
            continue

        try:
            # Get current usage and limit from docker stats
            result = subprocess.run(
                ["docker", "stats", "--no-stream", "--format",
                 "{{.MemUsage}}", container],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0 or not result.stdout.strip():
                continue

            # Parse "117.9MiB / 1.5GiB" format
            usage_str = result.stdout.strip()
            parts = usage_str.split("/")
            if len(parts) != 2:
                continue

            usage_mb = _parse_mem(parts[0].strip())
            limit_mb = _parse_mem(parts[1].strip())

            if limit_mb <= 0:
                continue

            ratio = usage_mb / limit_mb
            if ratio < MEMORY_HIGH_THRESHOLD:
                continue

            # Check caps
            new_limit_mb = int(limit_mb + MEMORY_BUMP_MB)
            if new_limit_mb > MEMORY_MAX_MB:
                log(f"auto_scale: {container} at {ratio:.0%} but already at cap ({int(limit_mb)}MB/{MEMORY_MAX_MB}MB)")
                continue

            if new_limit_mb > host_avail_mb - VPS_RESERVE_MB:
                log(f"auto_scale: {container} needs +{MEMORY_BUMP_MB}MB but host only has {host_avail_mb}MB free")
                continue

            # Bump memory
            bump_result = subprocess.run(
                ["docker", "update", f"--memory={new_limit_mb}m",
                 f"--memory-swap={new_limit_mb}m", container],
                capture_output=True, text=True, timeout=10,
            )

            if bump_result.returncode == 0:
                memory_bumped[container] = current_time
                msg = (
                    f"\U0001f4c8 <b>{container}</b> auto-scaled memory\n"
                    f"{int(limit_mb)}MB → {new_limit_mb}MB (usage was {int(usage_mb)}MB, {ratio:.0%})\n"
                    f"Host free: {host_avail_mb}MB\n"
                    f"Time: {now}"
                )
                send_telegram(msg)
                log(f"auto_scale: {container} bumped {int(limit_mb)}→{new_limit_mb}MB (was {ratio:.0%})")
            else:
                log(f"auto_scale: docker update failed for {container}: {bump_result.stderr.strip()}")

        except Exception as e:
            log(f"auto_scale: error checking {container}: {e}")


def _parse_mem(s: str) -> float:
    """Parse Docker memory string like '117.9MiB' or '1.5GiB' to MB."""
    s = s.strip()
    try:
        if s.endswith("GiB"):
            return float(s[:-3]) * 1024
        elif s.endswith("MiB"):
            return float(s[:-3])
        elif s.endswith("KiB"):
            return float(s[:-3]) / 1024
        elif s.endswith("B"):
            return float(s[:-1]) / (1024 * 1024)
    except ValueError:
        pass
    return 0


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

        # --- Container restart loop + OOM detection ---
        check_container_health()

        # --- Auto-scale memory if approaching limit ---
        _auto_scale_memory(now)

        # --- Worker heartbeats ---
        heartbeats = check_worker_heartbeats()
        current_time = time.time()
        for key, alive in heartbeats.items():
            short_name = key.split(":")[-1]
            if alive:
                if worker_alert_sent.get(key, False):
                    stale_dur = current_time - worker_stale_since.get(key, current_time)
                    send_telegram(
                        f"\u2705 Worker <b>{short_name}</b> recovered!\n"
                        f"Was stale for {int(stale_dur)}s\n"
                        f"Time: {now}"
                    )
                    worker_alert_sent[key] = False
                worker_stale_since.pop(key, None)
                worker_last_realert.pop(key, None)
                log(f"Worker {short_name}: alive")
            else:
                log(f"Worker {short_name}: STALE (heartbeat missing or expired)")
                if key not in worker_stale_since:
                    worker_stale_since[key] = current_time
                if not worker_alert_sent.get(key, False):
                    send_telegram(
                        f"\u26a0\ufe0f Worker <b>{short_name}</b> appears stuck!\n"
                        f"Heartbeat not updated within {WORKER_HEARTBEAT_MAX_AGE}s\n"
                        f"Time: {now}"
                    )
                    worker_alert_sent[key] = True
                    worker_last_realert[key] = current_time
                # Re-alert every 30 min if still stale
                elif current_time - worker_last_realert.get(key, 0) > WORKER_REALERT_INTERVAL:
                    stale_dur = current_time - worker_stale_since.get(key, current_time)
                    send_telegram(
                        f"\u26a0\ufe0f Worker <b>{short_name}</b> всё ещё не отвечает!\n"
                        f"Stale уже {int(stale_dur // 60)} мин\n"
                        f"Time: {now}"
                    )
                    worker_last_realert[key] = current_time

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        log("Watchdog stopped.")
        sys.exit(0)
