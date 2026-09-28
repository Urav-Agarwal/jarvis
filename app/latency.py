"""
Per-stage latency tracker (v4.1 Session A2).

One request = one trace. Stages:

    wake        -> wake word handled
    stt         -> speech transcribed
    reflex      -> runtime reflexes + deterministic handlers
    llm         -> every reasoning LLM call (accumulated)
    tools       -> every tool execution (accumulated)
    compose     -> reply composition
    tts_start   -> first audio queued

Usage:
    from app.latency import begin_stage, end_stage, finish_trace

    trace = finish_trace(trace_id) writes a summary line to
    data/logs/latency.log and returns the stage->ms dict.
"""

import os
import time
from datetime import datetime

from threading import local


_LOG_PATH = os.path.join("data", "logs", "latency.log")

_THREAD = local()


def start_trace(label: str = "") -> int:
    """Open a new trace; returns the trace id (monotonic counter)."""

    traces = getattr(_THREAD, "traces", None)

    if traces is None:
        traces = {}

        _THREAD.traces = traces

    trace_id = int(time.time() * 1000) + len(traces)

    traces[trace_id] = {
        "label": label[:80],
        "t0": time.perf_counter(),
        "stages": {},
        "current": None,
        "current_start": 0.0,
    }

    return trace_id


def stage(trace_id: int, name: str):
    """Close the previous stage and open a new one."""

    traces = getattr(_THREAD, "traces", {})

    trace = traces.get(trace_id)

    if trace is None:
        return

    now = time.perf_counter()

    if trace["current"] is not None:
        elapsed = (now - trace["current_start"]) * 1000.0

        trace["stages"][trace["current"]] = (
            trace["stages"].get(trace["current"], 0.0) + elapsed
        )

    trace["current"] = name

    trace["current_start"] = now


def add_ms(trace_id: int, name: str, milliseconds: float):
    """Accumulate time into a stage from an external measurement."""

    traces = getattr(_THREAD, "traces", {})

    trace = traces.get(trace_id)

    if trace is None:
        return

    trace["stages"][name] = (
        trace["stages"].get(name, 0.0) + float(milliseconds)
    )


def finish_trace(trace_id: int) -> dict | None:
    """Close the trace, write one log line, return the stage dict."""

    traces = getattr(_THREAD, "traces", {})

    trace = traces.pop(trace_id, None)

    if trace is None:
        return None

    now = time.perf_counter()

    if trace["current"] is not None:
        elapsed = (now - trace["current_start"]) * 1000.0

        trace["stages"][trace["current"]] = (
            trace["stages"].get(trace["current"], 0.0) + elapsed
        )

    total = (now - trace["t0"]) * 1000.0

    stages_text = " ".join(
        f"{name}={value:.0f}ms"
        for name, value in trace["stages"].items()
    )

    line = (
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
        f"total={total:.0f}ms {stages_text} "
        f"label={trace['label']}"
    ).strip()

    try:
        os.makedirs(os.path.dirname(_LOG_PATH), exist_ok=True)

        with open(_LOG_PATH, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    except Exception:
        pass

    print("LATENCY:", line)

    return trace["stages"]
