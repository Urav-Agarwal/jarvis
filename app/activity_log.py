"""
JSONL activity log for JARVIS (context 70).

Records timestamped pipeline events — requests, routed capabilities,
plans, tool executions, failures, recoveries — to data/activity.jsonl.
Safe to call from any thread; never raises.
"""

import json
import os
import threading
import time
from pathlib import Path

_LOCK = threading.Lock()

_PATH = Path("data") / "activity.jsonl"


def log_event(kind: str, **fields):
    """Append one event to the activity log."""

    record = {
        "ts": time.time(),
        "kind": kind,
        **fields,
    }

    try:
        _PATH.parent.mkdir(parents=True, exist_ok=True)

        with _LOCK:
            with open(_PATH, "a", encoding="utf-8") as file:
                file.write(
                    json.dumps(record, ensure_ascii=False) + "\n"
                )

    except OSError:
        pass


def recent_events(limit: int = 20) -> list:
    """Return the most recent log records (oldest first)."""

    try:
        with open(_PATH, "r", encoding="utf-8") as file:
            lines = file.readlines()

        records = []

        for line in lines[-limit:]:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue

        return records

    except OSError:
        return []
