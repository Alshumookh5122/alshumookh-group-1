from __future__ import annotations

import hashlib
import logging
import time
from collections import defaultdict
from typing import Any

from app.audit_service import log_event, safe_details
from app.config import get_settings
from app.database import AsyncSessionLocal

logger = logging.getLogger(__name__)
settings = get_settings()

_risk_events: dict[str, list[tuple[float, int]]] = defaultdict(list)
_banned_until: dict[str, float] = {}
_challenge_until: dict[str, float] = {}
_rate_buckets: dict[str, list[float]] = defaultdict(list)
_login_failures: dict[str, list[float]] = defaultdict(list)
_login_backoff_until: dict[str, float] = {}
_login_lock_until: dict[str, float] = {}
_probe_paths: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
_security_alerts: list[dict[str, Any]] = []

UA_SCANNER_KEYWORDS = (
    "sqlmap",
    "nikto",
    "nmap",
    "masscan",
    "zgrab",
    "acunetix",
    "netsparker",
    "gobuster",
    "dirbuster",
    "ffuf",
    "wpscan",
    "whatweb",
    "httpx",
)
UA_SUSPICIOUS_KEYWORDS = (
    "headlesschrome",
    "python-requests",
    "curl/",
    "wget/",
    "go-http-client",
    "java/",
    "libwww-perl",
    "aiohttp",
    "okhttp",
    "req/v3",
)
SUSPICIOUS_PATH_PARTS = (
    "/.git",
    "/.env",
    ".env",
    "/wp-admin",
    "/wp-includes",
    "/wp-login",
    "/xmlrpc.php",
    "/phpmyadmin",
    "/adminer",
    "/cgi-bin",
    "/server-status",
    "/boaform",
    "/actuator",
    "/vendor",
    "/HNAP1",
    "/.aws",
    "/.docker",
)
SUSPICIOUS_PATH_SUFFIXES = (
    ".env",
    ".php",
)
SUSPICIOUS_PATH_EXACT = (
    "/_environment",
    "/phpinfo",
    "/info",
)
HONEYPOT_PATHS = (
    "/.env.bak",
    "/wp-admin/install.php",
    "/adminer.php",
    "/phpinfo.php",
    "/backup.zip",
)


def _now() -> float:
    return time.time()


def _prune_timestamps(values: list[float], window_seconds: int) -> list[float]:
    now = _now()
    return [value for value in values if now - value < window_seconds]


def _prune_risk(ip: str) -> None:
    window_seconds = int(settings.security_probe_window_seconds or 600)
    now = _now()
    _risk_events[ip] = [
        (ts, score)
        for ts, score in _risk_events.get(ip, [])
        if now - ts < window_seconds
    ]
    if not _risk_events[ip]:
        _risk_events.pop(ip, None)


def _append_alert(payload: dict[str, Any]) -> None:
    _security_alerts.append(payload)
    if len(_security_alerts) > 200:
        del _security_alerts[:-200]


def classify_user_agent(user_agent: str | None) -> tuple[str, int, bool]:
    text = str(user_agent or "").strip()
    if not text:
        return ("blocked", 4, True)

    lowered = text.lower()
    if any(keyword in lowered for keyword in UA_SCANNER_KEYWORDS):
        return ("scanner", 5, True)

    if any(keyword in lowered for keyword in UA_SUSPICIOUS_KEYWORDS):
        return ("suspicious", 2, False)

    if len(text) < 12:
        return ("suspicious", 2, False)

    return ("browser", 0, False)


def classify_path(path: str) -> tuple[str | None, int, bool]:
    normalized = str(path or "/").lower()
    while "//" in normalized:
        normalized = normalized.replace("//", "/")
    if normalized in HONEYPOT_PATHS:
        return ("honeypot", 8, True)
    if normalized in SUSPICIOUS_PATH_EXACT:
        return ("probe", 5, True)
    if any(normalized.endswith(suffix) for suffix in SUSPICIOUS_PATH_SUFFIXES):
        return ("probe", 5, True)
    if any(marker in normalized for marker in SUSPICIOUS_PATH_PARTS):
        return ("probe", 5, True)
    return (None, 0, False)


def record_probe(ip: str, path: str) -> None:
    _probe_paths[ip][path] += 1


def add_risk_score(ip: str, score: int, *, reason: str | None = None, path: str | None = None) -> int:
    if not ip or ip == "unknown" or score <= 0:
        return 0

    _prune_risk(ip)
    _risk_events[ip].append((_now(), int(score)))
    current = risk_score(ip)
    threshold = int(settings.security_probe_threshold or 5)

    if path:
        record_probe(ip, path)

    if current >= max(3, threshold // 2):
        _challenge_until[ip] = max(_challenge_until.get(ip, 0), _now() + 300)

    if current >= threshold:
        ban_ip(ip)
        _append_alert(
            {
                "ip": ip,
                "type": "risk_threshold",
                "score": current,
                "reason": reason,
                "path": path,
                "at": _now(),
            }
        )

    return current


def risk_score(ip: str) -> int:
    _prune_risk(ip)
    return sum(score for _, score in _risk_events.get(ip, []))


def ban_ip(ip: str, seconds: int | None = None) -> None:
    if not ip or ip == "unknown":
        return
    duration = int(seconds or settings.security_ban_seconds or 900)
    _banned_until[ip] = _now() + duration
    _append_alert({"ip": ip, "type": "banned", "until": _banned_until[ip], "at": _now()})


def is_ip_banned(ip: str) -> bool:
    if not ip:
        return False
    until = _banned_until.get(ip)
    if not until:
        return False
    if until <= _now():
        _banned_until.pop(ip, None)
        return False
    return True


def ban_remaining_seconds(ip: str) -> int:
    until = _banned_until.get(ip, 0)
    return max(0, int(until - _now()))


def is_challenge_mode(ip: str) -> bool:
    if not ip:
        return False
    until = _challenge_until.get(ip)
    if not until:
        return False
    if until <= _now():
        _challenge_until.pop(ip, None)
        return False
    return True


def rate_limit_hit(bucket: str, key: str, *, limit: int, window_seconds: int) -> bool:
    bucket_key = f"{bucket}:{key}"
    values = _prune_timestamps(_rate_buckets.get(bucket_key, []), window_seconds)
    values.append(_now())
    _rate_buckets[bucket_key] = values
    return len(values) > limit


def register_failed_login(ip: str) -> dict[str, Any]:
    now = _now()
    window_seconds = int(settings.security_probe_window_seconds or 600)
    attempts = _prune_timestamps(_login_failures.get(ip, []), window_seconds)
    attempts.append(now)
    _login_failures[ip] = attempts

    count = len(attempts)
    backoff_seconds = min(300, 2 ** max(0, count - 1))
    _login_backoff_until[ip] = now + backoff_seconds

    locked = False
    if count >= 5:
        _login_lock_until[ip] = max(
            _login_lock_until.get(ip, 0),
            now + int(settings.security_ban_seconds or 900),
        )
        locked = True
        add_risk_score(ip, 5, reason="repeated_failed_login")
    else:
        add_risk_score(ip, 2, reason="failed_login")

    return {
        "failed_attempts": count,
        "backoff_seconds": backoff_seconds,
        "locked": locked,
        "captcha_ready": count >= 3,
    }


def clear_login_failures(ip: str) -> None:
    _login_failures.pop(ip, None)
    _login_backoff_until.pop(ip, None)
    _login_lock_until.pop(ip, None)


def clear_security_state(ip: str) -> None:
    _risk_events.pop(ip, None)
    _challenge_until.pop(ip, None)
    _banned_until.pop(ip, None)


def login_guard(ip: str) -> dict[str, Any]:
    now = _now()
    failed_attempts = len(_prune_timestamps(_login_failures.get(ip, []), int(settings.security_probe_window_seconds or 600)))
    backoff_until = _login_backoff_until.get(ip, 0)
    lock_until = _login_lock_until.get(ip, 0)
    return {
        "failed_attempts": failed_attempts,
        "captcha_ready": failed_attempts >= 3,
        "backoff_seconds": max(0, int(backoff_until - now)),
        "lock_seconds": max(0, int(lock_until - now)),
        "is_locked": lock_until > now,
        "is_backoff": backoff_until > now,
    }


async def log_security_event(
    event_type: str,
    details: dict[str, Any] | None = None,
    *,
    ip: str | None = None,
    path: str | None = None,
    method: str | None = None,
    user_agent: str | None = None,
    status_code: int | None = None,
    request_id: str | None = None,
    error_message: str | None = None,
) -> None:
    payload = safe_details(details or {})
    try:
        async with AsyncSessionLocal() as db:
            await log_event(
                db,
                event_type,
                payload,
                endpoint=path,
                method=method,
                ip=ip,
                user_agent=user_agent,
                status_code=status_code,
                request_id=request_id,
                error_message=error_message,
            )
    except Exception as exc:  # pragma: no cover
        logger.warning("Failed to persist security event %s: %s", event_type, exc)


def fingerprint_key(key: str | None) -> str | None:
    if not key:
        return None
    return hashlib.sha256(str(key).encode("utf-8")).hexdigest()[:16]


def runtime_security_snapshot() -> dict[str, Any]:
    now = _now()
    blocked_ips = [
        {"ip": ip, "seconds_remaining": max(0, int(until - now))}
        for ip, until in _banned_until.items()
        if until > now
    ]
    suspicious_ips = sorted(
        (
            {
                "ip": ip,
                "score": risk_score(ip),
                "challenge_mode": is_challenge_mode(ip),
                "probe_paths": dict(sorted(paths.items(), key=lambda item: item[1], reverse=True)[:5]),
                "failed_logins": len(_login_failures.get(ip, [])),
            }
            for ip, paths in _probe_paths.items()
            if risk_score(ip) > 0 or len(_login_failures.get(ip, [])) > 0
        ),
        key=lambda item: (-item["score"], -item["failed_logins"], item["ip"]),
    )[:25]

    suspicious_paths: list[dict[str, Any]] = []
    path_counts: dict[str, int] = defaultdict(int)
    for paths in _probe_paths.values():
        for path, count in paths.items():
            path_counts[path] += count
    for path, count in sorted(path_counts.items(), key=lambda item: (-item[1], item[0]))[:25]:
        suspicious_paths.append({"path": path, "count": count})

    recent_alerts = sorted(_security_alerts, key=lambda item: item.get("at", 0), reverse=True)[:20]

    return {
        "blocked_ips": blocked_ips,
        "suspicious_ips": suspicious_ips,
        "suspicious_paths": suspicious_paths,
        "recent_alerts": recent_alerts,
    }
