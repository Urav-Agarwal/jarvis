"""
A2 ENDURANCE SIMULATION: ~8 minutes of alternating speech and
silence. JARVIS must NEVER drop to wake-word mode before the idle
timeout (5 min of CONTINUOUS silence with nothing pending). Every
silence round within the session loops back to the mic (A2 rule).

Simulated timeline (accelerated: fake mic + clock aging):
- 12 exchanges, each followed by 40 s of silence.
- The farewell must fire exactly once, AFTER the 12 exchanges, from
  the final 310 s silent stretch (longer than the 300 s idle limit).
- A pending confirmation must block the idle sleep forever.

Run with:
    PYTHONIOENCODING=utf-8 python -m tests.test_session_endurance
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from threading import Event

import numpy as np

from assistant.orchestrator import Orchestrator
from assistant.session import ConversationSession, SessionState
from security.kill_switch import KillSwitch

failures = 0


def check(name, condition, detail=""):
    global failures

    if condition:
        print(f"[PASS] {name}")
    else:
        failures += 1
        print(f"[FAIL] {name} {detail}")


def wire(orch, idle_timeout=300.0):
    """Give a bare Orchestrator every attribute listen_and_process uses."""

    orch.interrupt_requested = False
    orch.pending_wake_interrupt = False
    orch.pending_self_command = None
    orch._session_end_requested = False
    orch._processing_done = True
    orch.filming_mode = False
    orch.speaking = False
    orch.has_greeted = True
    orch.wake_chime = False
    orch.on_jarvis_message = None
    orch.on_user_message = None
    orch.kill_switch = KillSwitch()
    orch.thinking_abort = Event()

    # Silent mic + empty transcripts for the interrupt-watcher thread.
    class _FakeMic:
        def record_until_silence(self, **kwargs):
            time.sleep(0.02)

            return np.array([], dtype="float32")

    class _FakeSTT:
        def transcribe(self, audio):
            return ""

    orch.microphone = _FakeMic()
    orch.speech_to_text = _FakeSTT()

    class _Confirmations:
        def has_pending(self):
            return False

        def cancel(self):
            pass

    class _Recorder:
        def is_active(self):
            return False

        def cancel(self):
            pass

    orch.agent = type(
        "A",
        (),
        {
            "confirmations": _Confirmations(),
            "recorder": _Recorder(),
            "last_tool_receipt": None,
        },
    )()

    # The busy_check closure inside __init__ is not available on a
    # bare instance; build the session with the SAME busy logic the
    # real orchestrator wires (confirmations, drafts, speech...).
    def _busy():
        return (
            orch.agent.confirmations.has_pending()
            or getattr(orch.agent, "_pending_send", None) is not None
            or getattr(orch.agent, "_pending_draft", None) is not None
            or getattr(orch.agent, "_teaching_pending_save", None)
            is not None
            or getattr(orch.agent, "_recorder_pending_save", None)
            is not None
            or orch.speaking
        )

    orch.session = ConversationSession(
        idle_timeout_seconds=idle_timeout,
        busy_check=_busy,
    )

    orch.speak = lambda text: spoken.append(("speak", text))
    orch._speak_until_done = lambda text: spoken.append(("tts", text))
    orch._play_chime = lambda: spoken.append(("chime", ""))
    orch.interrupt_speech = lambda: None
    orch._emit_state = lambda state: states.append(state)
    orch._proactive_note = lambda: ""
    orch.clean_for_speech = lambda text: text
    orch._remember_turn = lambda user, reply: history.append(
        (user, reply)
    )
    orch._judge_answer = lambda q, a: a

    spoken = []
    states = []
    history = []

    return orch, spoken, states, history


# ============================================================
# SCENARIO 1: 12 exchanges with 40 s silence between
# ============================================================

orch = Orchestrator.__new__(Orchestrator)

spoken, states, history = [], [], []

wire(orch)

EXCHANGES = 12

SILENCE_AFTER_EACH = 40.0

# Mic script: utterance, silence, utterance, silence, ...
events = []

for index in range(EXCHANGES):
    events.append(f"command {index}")
    events.append("silence")

# After the script: 310 s of nothing (past the 300 s idle limit).
events.append("long_silence")
events.append("long_silence")

mic_state = {"index": 0}


def fake_mic(**kwargs):
    index = mic_state["index"]

    mic_state["index"] += 1

    if index >= len(events):
        return ""

    event = events[index]

    if event == "silence":
        # 40 s of room silence: age the idle clock, return nothing.
        orch.session._last_activity -= SILENCE_AFTER_EACH

        return ""

    if event == "long_silence":
        orch.session._last_activity -= 310

        return ""

    return event


orch.listen = fake_mic
orch._listen_followup = fake_mic

processed = []

orch.process = lambda text: (
    processed.append(text),
    f"Reply {text}, sir.",
)[1]

farewells = []

orch._say_session_farewell = lambda: (
    farewells.append(1),
    orch.session.end("idle"),
)

start = time.time()

orch.listen_and_process()

elapsed = time.time() - start

check(
    "endurance: all 12 exchanges processed (silence loops, never sleeps)",
    len(processed) == EXCHANGES,
    f"processed={len(processed)}: {processed[:3]}",
)

check(
    "endurance: farewell only AFTER all exchanges (from the long tail)",
    len(farewells) == 1 and len(processed) == EXCHANGES,
    f"farewells={len(farewells)} processed={len(processed)}",
)

check(
    "endurance: runs fast (simulated, not real-time)",
    elapsed < 20,
    f"{elapsed:.1f}s",
)

# ============================================================
# SCENARIO 2: long silence with nothing pending -> one farewell
# ============================================================

orch2 = Orchestrator.__new__(Orchestrator)

spoken2, states2, history2 = [], [], []

wire(orch2)

mic2 = {"index": 0}


def silence_only(**kwargs):
    mic2["index"] += 1

    orch2.session._last_activity -= 310

    return ""


orch2.listen = silence_only
orch2._listen_followup = silence_only

farewells2 = []

orch2._say_session_farewell = lambda: (
    farewells2.append(1),
    orch2.session.end("idle"),
)

orch2.listen_and_process()

check(
    "endurance: 310 s silence (nothing pending) -> exactly one farewell",
    len(farewells2) == 1,
    f"farewells={farewells2}",
)

check(
    "endurance: session DORMANT after the idle farewell",
    orch2.session.state == SessionState.DORMANT,
    f"state={orch2.session.state}",
)

# ============================================================
# SCENARIO 3: pending confirmation blocks idle sleep forever
# ============================================================

orch3 = Orchestrator.__new__(Orchestrator)

spoken3, states3, history3 = [], [], []

wire(orch3)

# Force the busy path: a confirmation is pending.


class _PendingConfirmations:
    def has_pending(self):
        return True

    def cancel(self):
        pass


orch3.agent = type(
    "A3",
    (),
    {
        "confirmations": _PendingConfirmations(),
        "recorder": type(
            "R", (), {"is_active": lambda s: False, "cancel": lambda s: None}
        )(),
        "last_tool_receipt": None,
    },
)()

# Rebuild the session so busy_check sees the pending confirmation.
def _busy3():
    return orch3.agent.confirmations.has_pending() or orch3.speaking


orch3.session = ConversationSession(
    idle_timeout_seconds=300,
    busy_check=_busy3,
)

orch3.session.activate()

mic3 = {"n": 0}


def silence_aged(**kwargs):
    mic3["n"] += 1

    if mic3["n"] > 200:  # safety: never loop forever in the test
        raise RuntimeError("test loop did not end")

    orch3.session._last_activity -= 60

    return ""


orch3.listen = silence_aged
orch3._listen_followup = silence_aged

farewells3 = []

orch3._say_session_farewell = lambda: farewells3.append(1)

# Run a bounded number of rounds by ending via KeyboardInterrupt-like
# control: simulate 200 silent rounds then assert the session lived.
try:
    orch3.listen_and_process()

except RuntimeError as error:
    pass  # expected: the loop genuinely never ended (that's the point)

check(
    "endurance: pending confirmation blocks idle sleep (200+ rounds)",
    not farewells3
    and orch3.session.state != SessionState.DORMANT,
    f"farewells={farewells3} state={orch3.session.state}",
)

print()

if failures:
    print(f"FAILED: {failures} check(s)")
    sys.exit(1)

print("ALL ENDURANCE TESTS PASSED")
sys.exit(0)
