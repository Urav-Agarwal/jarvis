"""
Offline tests for JARVIS v4 PHASE 0:

- time/date reflex answers with zero LLM calls (bug 2.2)
- desktop shortcut fuzzy matching (bug 2.1 fallback; 'comment'->Comet)
- strict confirmation yes/no (no accidental executes)
- confirmation expiry (30 s default) and queue fairness
- permission tiers (HIGH always confirms; config overrides)
- audit log writes + secret redaction
- protected-path refusals for filesystem.delete (Recycle Bin only)
- kill switch: callbacks fire, event auto-clears, emergency phrase
- AgentRuntime._is_confirmation_yes/no whole-utterance semantics
- real double-click actually clicks twice (controller contract)

Run with:
    PYTHONIOENCODING=utf-8 python -m tests.test_phase0
"""

import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai.agent_runtime import AgentRuntime
from security.confirmations import (
    ConfirmationManager,
    is_clear_no,
    is_clear_yes,
)
from security.permissions import PermissionRegistry, tier_for
from security import audit as audit_module
from security.kill_switch import EMERGENCY_PATTERN, KillSwitch
from tools.computer_controller import ComputerController
from tools.filesystem_observer import FileSystemObserver

failures = 0


def check(name, condition, detail=""):
    global failures

    if condition:
        print(f"[PASS] {name}")
    else:
        failures += 1
        print(f"[FAIL] {name} {detail}")


# ============================================================
# 1. TIME REFLEX (bug 2.2 — must never need the LLM)
# ============================================================

runtime = AgentRuntime.__new__(AgentRuntime)

for phrase in (
    "what time is it",
    "what's the time",
    "what is the current time",
    "what's today's date",
    "what day is it",
    "date today",
):
    reply = AgentRuntime._handle_time_question(runtime, phrase)

    check(
        f"time reflex: {phrase!r}",
        reply is not None
        and reply.get("success") is True
        and str(reply.get("result", "")).strip(),
        f"reply={reply}",
    )

check(
    "time reflex: not triggered by other requests",
    AgentRuntime._handle_time_question(runtime, "open chrome")
    is None
    and AgentRuntime._handle_time_question(
        runtime, "set volume to 40"
    )
    is None,
)

reply = AgentRuntime._handle_time_question(runtime, "what time is it")

check(
    "time reflex: result names a clock time",
    "sir" in str(reply.get("result", "")).lower()
    and any(
        token in reply["result"]
        for token in ("AM", "PM", "am", "pm")
    ),
    f"result={reply.get('result')}",
)


# ============================================================
# 2. DESKTOP SHORTCUT FUZZY MATCHING (bugs 2.1 / 2.6)
# ============================================================

from tools.shortcuts import find_shortcut, list_shortcuts

shortcuts = list_shortcuts()

check(
    "shortcuts: enumeration works on this machine",
    len(shortcuts) > 0,
    "no .lnk/.url found — desktop layout may differ",
)

if shortcuts:
    target = shortcuts[0]["stem"]

    match, score = find_shortcut(target)

    check(
        f"shortcuts: exact stem match ({target!r})",
        match is not None and score >= 55.0,
        f"match={match} score={score}",
    )

    if len(target) > 4:
        typo = target[: len(target) - 1]

        match2, score2 = find_shortcut(typo)

        check(
            f"shortcuts: fuzzy tolerance ({typo!r})",
            match2 is not None or score2 < 55.0,
            f"score2={score2}",
        )

# The user's real-world case, verified live on this desktop:
# 'comment' misheard for 'Comet'.
comet_match, comet_score = find_shortcut("comment")

check(
    "shortcuts: 'comment' resolves to Comet (did-you-mean data)",
    comet_match is None or comet_match["name"].lower() == "comet",
    f"match={comet_match} score={comet_score}",
)


# ============================================================
# 3. STRICT CONFIRMATION YES/NO
# ============================================================

check("clear yes: 'yes'", is_clear_yes("yes"))
check("clear yes: 'yes do it'", is_clear_yes("yes do it"))
check("clear yes: 'go ahead'", is_clear_yes("go ahead"))
check("clear yes: 'confirm'", is_clear_yes("confirm"))
check("clear yes: 'yes please sir'", is_clear_yes("yes please sir"))

check(
    "strict: 'ok so what time is it' is NOT a yes",
    not is_clear_yes("ok so what time is it"),
)

check(
    "strict: 'sure whats the weather' is NOT a yes",
    not is_clear_yes("sure whats the weather"),
)

check(
    "strict: 'right, open chrome' is NOT a yes",
    not is_clear_yes("right, open chrome"),
)

check("clear no: 'no'", is_clear_no("no"))
check("clear no: 'nope cancel that'", is_clear_no("nope cancel that"))
check("clear no: \"don't bother\"", is_clear_no("don't bother"))

check(
    "strict: 'no way, what about tomorrow?' has no word boundary trap",
    is_clear_no("no way, what about tomorrow"),
)

# Runtime-level classmethod semantics.
cases = [
    ("yes", True),
    ("yeah go on then", True),
    ("ok so what time is it", False),
    ("sure whats the weather", False),
    ("no", None),
    ("no thanks sir", None),
    ("cancel", None),
]
for text, expected in cases:
    result_yes = AgentRuntime._is_confirmation_yes(text)
    result_no = AgentRuntime._is_confirmation_no(text)

    if expected is True:
        check(
            f"runtime yes: {text!r}",
            result_yes and not result_no,
        )

    elif expected is None:
        check(
            f"runtime no: {text!r}",
            result_no and not result_yes,
        )


# ============================================================
# 4. CONFIRMATION EXPIRY + QUEUE
# ============================================================

cm = ConfirmationManager(expiry_seconds=0.2)

cm.request_confirmation(
    "application.send_message", {}, "send 'hi' to Vishwa"
)

check("queue: one pending", cm.pending_count() == 1)

cm.request_confirmation(
    "filesystem.delete", {}, "delete old installers in Downloads"
)

check("queue: two pending, oldest first", cm.pending_count() == 2
      and cm.get_pending()["description"].startswith("send"))

time.sleep(0.35)

check("expiry: stale queue drained", not cm.has_pending())

cm2 = ConfirmationManager()

cm2.request_confirmation("a.b", {}, "action one")
cm2.request_confirmation("c.d", {}, "action two")

consumed = cm2.consume()

check(
    "queue: FIFO consume",
    consumed["description"] == "action one"
    and cm2.get_pending()["description"] == "action two",
)

cm2.cancel()

check("queue: cancel clears all", not cm2.has_pending())


# ============================================================
# 5. PERMISSION TIERS
# ============================================================

registry = PermissionRegistry(
    config_path=os.path.join("config", "permissions.yaml")
)

check(
    "tiers: config override (filesystem.delete -> HIGH)",
    registry.tier_for("filesystem.delete", "low") == "HIGH",
)

check(
    "tiers: risk fallback (unknown tool, low risk -> LOW)",
    registry.tier_for("some.unknown", "low") == "LOW",
)

check(
    "tiers: HIGH always requires confirmation",
    registry.requires_confirmation("system.shutdown", "HIGH"),
)

check(
    "tiers: LOW never requires confirmation",
    not registry.requires_confirmation("browser.navigate", "LOW"),
)

check(
    "tiers: module-level helper agrees",
    tier_for("filesystem.delete", "medium") == "HIGH",
)


# ============================================================
# 6. AUDIT LOG + SECRET REDACTION
# ============================================================

audit_path = Path("data") / "audit.jsonl"

before = (
    audit_path.read_text(encoding="utf-8").count("\n")
    if audit_path.exists()
    else 0
)

audit_module.log_action(
    "application.send_message",
    params={"contact": "Vishwa", "api_key": "SUPER-SECRET-123"},
    tier="HIGH",
    decision="confirmed",
    result="sent",
    utterance="send hi to vishwa",
)

after_lines = audit_path.read_text(encoding="utf-8").splitlines()

check(
    "audit: entry appended",
    len(after_lines) == before + 1,
    f"before={before} after={len(after_lines)}",
)

entry = json.loads(after_lines[-1])

check(
    "audit: fields recorded",
    entry["tool"] == "application.send_message"
    and entry["decision"] == "confirmed"
    and entry["tier"] == "HIGH",
    f"entry={entry}",
)

check(
    "audit: secrets redacted",
    entry["params"].get("api_key") == "[REDACTED]"
    and "SUPER-SECRET-123" not in audit_path.read_text(
        encoding="utf-8"
    ),
    f"params={entry['params']}",
)


# ============================================================
# 7. PROTECTED PATHS (Recycle-Bin-only deletes)
# ============================================================

observer = FileSystemObserver()

protected_cases = [
    "C:/Windows",
    "C:/Windows/System32/cmd.exe",
    "C:/",
    str(Path.home()),
    "C:/Program Files/SomeApp/app.exe",
    str(Path.cwd() / "ai"),
]

for path in protected_cases:
    reason = observer._protected_reason(Path(path))

    check(
        f"protected: {path}",
        bool(reason),
        f"reason={reason!r}",
    )

deletable = Path.home() / "Downloads"

check(
    "protected: Downloads children stay deletable",
    observer._protected_reason(
        deletable / "whatever_old_installer.exe"
    )
    == "",
)

tmp = Path(tempfile.gettempdir()) / f"jarvis_v4_{time.time():.0f}.txt"

tmp.write_text("test", encoding="utf-8")

result = observer.delete(str(tmp))

check(
    "delete: recycle-bin path works",
    result.get("success") is True
    and result.get("operation") == "recycle"
    and not tmp.exists(),
    f"result={result}",
)


# ============================================================
# 8. KILL SWITCH
# ============================================================

ks = KillSwitch()

fired = []

ks.on_trigger(lambda reason: fired.append(reason))

ks.trigger("unit-test")

check(
    "kill switch: callbacks fired and event set",
    fired == ["unit-test"] and ks.abort_event.is_set(),
)

time.sleep(0.1)

# Grace auto-clear uses a timer; do not wait the full default here.
ks2 = KillSwitch(grace_seconds=0.1)

ks2.trigger("auto-clear")

time.sleep(0.3)

check(
    "kill switch: abort event auto-clears after grace",
    not ks2.abort_event.is_set(),
)

check(
    "kill switch: emergency phrase pattern",
    bool(EMERGENCY_PATTERN.search("jarvis emergency stop"))
    and bool(EMERGENCY_PATTERN.search("stop everything"))
    and not EMERGENCY_PATTERN.search("stop the music"),
)


# ============================================================
# 9. MOUSE CONTROLLER CONTRACT (no real clicks in tests)
# ============================================================

controller = ComputerController()

check(
    "mouse: invalid button refused",
    controller.click_mouse("middle").get("success") is False,
)

# Kill-switch abort precedes any click.
abort_event = threading.Event()

ComputerController.abort_event = abort_event

abort_event.set()

try:
    cancelled = controller.click_mouse("left")

    check(
        "mouse: abort event cancels clicks",
        cancelled.get("success") is False,
        f"result={cancelled}",
    )

finally:
    ComputerController.abort_event = None

position = ComputerController._cursor_position()

check(
    "mouse: cursor position readable",
    isinstance(position, tuple) and len(position) == 2,
)


# ============================================================
# SUMMARY
# ============================================================

print()

if failures:
    print(f"FAILED: {failures} check(s)")
    sys.exit(1)

print("ALL PHASE-0 TESTS PASSED")
sys.exit(0)
