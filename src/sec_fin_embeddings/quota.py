"""Cross-process Gemini *embedding* pacing at ≤80% free tier.

Separate lock from PM generateContent (`/tmp/gemini-quota.json`).
This module uses `/tmp/gemini-embed-quota.json` by default.
"""

from __future__ import annotations

import json
import math
import os
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_PACIFIC = ZoneInfo("America/Los_Angeles")

# Documented free tier for gemini-embedding-001 (AI Studio / Google forum).
FREE_RPM = 100
FREE_RPD = 1000
FREE_TPM = 30000
DEFAULT_FRACTION = 0.8
DEFAULT_QUOTA_FILE = "/tmp/gemini-embed-quota.json"


@dataclass(frozen=True)
class EmbedLimits:
    rpm: int
    rpd: int
    tpm: int


def limits_from_env() -> EmbedLimits:
    frac = float(os.environ.get("GEMINI_EMBED_QUOTA_FRACTION", str(DEFAULT_FRACTION)))
    frac = max(0.01, min(1.0, frac))
    # Never silently exceed 0.8 unless operator explicitly sets fraction.
    rpm = int(os.environ.get("GEMINI_EMBED_RPM", math.floor(FREE_RPM * frac)))
    rpd = int(os.environ.get("GEMINI_EMBED_RPD", math.floor(FREE_RPD * frac)))
    tpm = int(os.environ.get("GEMINI_EMBED_TPM", math.floor(FREE_TPM * frac)))
    return EmbedLimits(rpm=max(1, rpm), rpd=max(1, rpd), tpm=max(1, tpm))


def _pacific_day() -> str:
    return datetime.now(_PACIFIC).strftime("%Y-%m-%d")


def _load(path: Path) -> dict:
    if not path.exists():
        return {"day": _pacific_day(), "day_count": 0, "minute_ts": [], "token_minute": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        data = {"day": _pacific_day(), "day_count": 0, "minute_ts": [], "token_minute": []}
    if data.get("day") != _pacific_day():
        data = {"day": _pacific_day(), "day_count": 0, "minute_ts": [], "token_minute": []}
    return data


def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    tmp.replace(path)


def acquire_embed_turn(
    *,
    estimated_tokens: int = 512,
    path: str | None = None,
    limits: EmbedLimits | None = None,
) -> None:
    """Block until one embed request slot is available; raise when daily cap hit."""
    limits = limits or limits_from_env()
    quota_path = Path(path or os.environ.get("GEMINI_EMBED_QUOTA_FILE", DEFAULT_QUOTA_FILE))
    lock_path = quota_path.with_suffix(".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    while True:
        sleep_for = 0.0
        with open(lock_path, "a", encoding="utf-8") as lock_f:
            try:
                import fcntl

                fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX)
            except ImportError:
                pass
            data = _load(quota_path)
            if int(data.get("day_count", 0)) >= limits.rpd:
                try:
                    import fcntl

                    fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)
                except ImportError:
                    pass
                raise RuntimeError(
                    f"embed daily budget exhausted ({limits.rpd} RPD at "
                    f"{int(float(os.environ.get('GEMINI_EMBED_QUOTA_FRACTION', '0.8')) * 100)}% "
                    "of free tier); resets midnight Pacific"
                )
            now = time.time()
            minute: deque[float] = deque(data.get("minute_ts") or [])
            while minute and now - minute[0] >= 60.0:
                minute.popleft()
            tok_events: deque[tuple[float, int]] = deque(
                (float(t), int(n)) for t, n in (data.get("token_minute") or [])
            )
            while tok_events and now - tok_events[0][0] >= 60.0:
                tok_events.popleft()
            tokens_in_window = sum(n for _, n in tok_events)

            min_gap = 60.0 / max(1, limits.rpm)
            if len(minute) >= limits.rpm:
                sleep_for = 60.0 - (now - minute[0]) + 0.05
            elif tokens_in_window + estimated_tokens > limits.tpm:
                sleep_for = 60.0 - (now - tok_events[0][0]) + 0.05 if tok_events else 1.0
            elif minute:
                sleep_for = max(0.0, min_gap - (now - minute[-1]))

            if sleep_for <= 0:
                minute.append(now)
                tok_events.append((now, max(1, estimated_tokens)))
                data["minute_ts"] = list(minute)[-limits.rpm :]
                data["token_minute"] = [[t, n] for t, n in list(tok_events)[-200:]]
                data["day_count"] = int(data.get("day_count", 0)) + 1
                data["day"] = _pacific_day()
                _save(quota_path, data)
                try:
                    import fcntl

                    fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)
                except ImportError:
                    pass
                return
            try:
                import fcntl

                fcntl.flock(lock_f.fileno(), fcntl.LOCK_UN)
            except ImportError:
                pass
        time.sleep(sleep_for)


def snapshot(path: str | None = None) -> dict:
    quota_path = Path(path or os.environ.get("GEMINI_EMBED_QUOTA_FILE", DEFAULT_QUOTA_FILE))
    data = _load(quota_path)
    lim = limits_from_env()
    return {
        "day": data.get("day"),
        "calls_today": int(data.get("day_count", 0)),
        "rpd_cap": lim.rpd,
        "rpm_cap": lim.rpm,
        "tpm_cap": lim.tpm,
        "remaining_rpd": max(0, lim.rpd - int(data.get("day_count", 0))),
        "quota_file": str(quota_path),
    }
