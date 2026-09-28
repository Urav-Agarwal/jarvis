"""
Append-only audit log: data/audit.jsonl.

One JSON object per line:
    {"ts": iso, "utterance": str|None, "tool": str, "params": {...},
     "tier": str, "decision": "auto|confirmed|denied|expired",
     "result": str, "elapsed_ms": int}

Secrets never enter the log: parameter keys that look sensitive are
redacted before serialization and values are truncated. The file is
opened in append mode per write so a crash never loses the log.
"""

import json
import os
import re
import threading
import time
from datetime import datetime


_LOCK = threading.Lock()

_SECRET_KEY = re.compile(
    r"key|token|secret|password|passphrase|credential|authorization",
    re.IGNORECASE,
)

_MAX_VALUE_LEN = 200

_MAX_LOG_BYTES = 5_000_000  # rotate at ~5 MB


def _sanitize_params(params) -> dict:
    if not isinstance(params, dict):
        return {}

    clean = {}

    for key, value in params.items():
        key = str(key)

        if _SECRET_KEY.search(key):
            clean[key] = "[REDACTED]"

            continue

        text = value if isinstance(value, str) else json.dumps(
            value, default=str
        )

        text = str(text)

        if len(text) > _MAX_VALUE_LEN:
            text = text[: _MAX_VALUE_LEN - 3] + "..."

        clean[key] = text

    return clean


def log_action(
    tool_name: str,
    params=None,
    tier: str = "",
    decision: str = "auto",
    result=None,
    utterance: str | None = None,
    elapsed_ms: int | None = None,
):
    """Append one entry. Never raises — auditing must not break tools."""

    entry = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "utterance": (utterance or "")[:200] or None,
        "tool": tool_name,
        "params": _sanitize_params(params),
        "tier": tier,
        "decision": decision,
        "result": str(result)[:200] if result is not None else "",
    }

    if elapsed_ms is not None:
        entry["elapsed_ms"] = int(elapsed_ms)

    with _LOCK:
        try:
            path = os.path.join("data", "audit.jsonl")

            os.makedirs("data", exist_ok=True)

            try:
                if os.path.exists(path) and os.path.getsize(
                    path
                ) > _MAX_LOG_BYTES:
                    os.replace(path, path + ".1")

            except OSError:
                pass

            with open(path, "a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(entry, ensure_ascii=False) + "\n"
                )

        except Exception:
            pass


def read_today(max_lines: int = 400):
    """
    Entries from today, oldest first — powers "what did you do
    today, sir?".
    """

    today = datetime.now().strftime("%Y-%m-%d")

    entries = []

    try:
        with open(
            os.path.join("data", "audit.jsonl"),
            "r",
            encoding="utf-8",
        ) as handle:
            for line in handle:
                line = line.strip()

                if not line:
                    continue

                try:
                    entry = json.loads(line)

                except json.JSONDecodeError:
                    continue

                if str(entry.get("ts", "")).startswith(today):
                    entries.append(entry)

    except FileNotFoundError:
        return []

    except Exception:
        return entries

    return entries[-max_lines:]


def summarize_today() -> str:
    """Spoken summary for 'what did you do today?'."""

    entries = read_today()

    if not entries:
        return (
            "I haven't done anything on this computer today, sir."
        )

    counts = {}

    for entry in entries:
        tool = str(entry.get("tool") or "unknown")

        counts[tool] = counts.get(tool, 0) + 1

    top = sorted(counts.items(), key=lambda kv: -kv[1])

    parts = [
        f"{count} x {name.replace('.', ' ')}"
        for name, count in top[:5]
    ]

    confirmed = sum(
        1 for e in entries if e.get("decision") == "confirmed"
    )

    summary = (
        f"{len(entries)} actions today, sir: "
        + ", ".join(parts)
        + "."
    )

    if confirmed:
        summary += f" {confirmed} needed your confirmation."

    return summary
