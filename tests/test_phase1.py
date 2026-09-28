"""
Offline tests for JARVIS v4 PHASE 1 (session + voice engine):

- ConversationSession state machine: activate, substates, task
  tracking, busy blocks sleep, idle timeout, explicit dismissal
- hold logic: should_hold stays True across many "exchanges"
- the session survives silence mid-conversation (no 4-exchange cap)
- wait_for_wake_word chime path + refractory debounce (fake detector)
- listen_and_process keeps the session alive across silence rounds
  and ends it on go_to_sleep (fake mic + fake TTS)
- budgeted step loop: BrainV3 max_steps comes from config, > 4 steps
  actually execute

Run with:
    PYTHONIOENCODING=utf-8 python -m tests.test_phase1
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from assistant.session import ConversationSession, SessionState

failures = 0


def check(name, condition, detail=""):
    global failures

    if condition:
        print(f"[PASS] {name}")
    else:
        failures += 1
        print(f"[FAIL] {name} {detail}")


# ============================================================
# 1. STATE MACHINE BASICS
# ============================================================

session = ConversationSession(idle_timeout_seconds=60)

check(
    "session: starts DORMANT",
    session.state == SessionState.DORMANT,
)

session.activate()

check(
    "session: wake activates",
    session.state == SessionState.ACTIVE
    and not session.should_sleep(),
)

session.set_substate("THINKING")

check(
    "session: substate tracked",
    session.state == SessionState.THINKING,
)

session.set_substate("ACTIVE")

check(
    "session: returns to ACTIVE",
    session.state == SessionState.ACTIVE,
)

# Task tracking blocks sleep forever.
session.begin_task()

session._last_activity -= 9999  # force the idle clock far past

check(
    "session: running task blocks idle sleep",
    not session.should_sleep(),
)

session.end_task()

# Completing a task touches the clock (correct: the user just got a
# result); force the idle window to elapse again.
session._last_activity -= 9999

check(
    "session: idle timeout sleeps after task done",
    session.should_sleep(),
)

# Explicit dismissal ends immediately regardless of pending work.
session.activate()

session.begin_task()

session.end("dismissed")

check(
    "session: dismissal ends even mid-task",
    session.state == SessionState.DORMANT
    and session.end_reason() == "dismissed",
)

# Busy check blocks sleep.
busy = {"flag": True}

session2 = ConversationSession(
    idle_timeout_seconds=60,
    busy_check=lambda: busy["flag"],
)

session2.activate()

session2._last_activity -= 9999

check(
    "session: busy_check blocks sleep",
    not session2.should_sleep(),
)

busy["flag"] = False

check(
    "session: unbusy + idle -> sleep",
    session2.should_sleep(),
)

# should_hold survives many rounds; no exchange counter exists.
session3 = ConversationSession(idle_timeout_seconds=300)

session3.activate()

for _ in range(50):
    session3.touch()

    if not session3.should_hold():
        break

check(
    "session: 50 exchanges without a cap",
    session3.should_hold(),
)

session3.end("dismissed")

check(
    "session: hold ends on dismissal",
    not session3.should_hold(),
)


# ============================================================
# 2. ORCHESTRATOR INTEGRATION (fake audio + fake TTS)
# ============================================================

from assistant.orchestrator import Orchestrator

orch = Orchestrator.__new__(Orchestrator)

# Minimal attributes listen_and_process/wait_for_wake_word touch.
orch.interrupt_requested = False
orch.pending_wake_interrupt = False
orch.pending_self_command = None
orch._session_end_requested = False
orch._processing_done = True
orch.filming_mode = False
orch.speaking = False
orch.has_greeted = True
orch.restart_acknowledged = False
orch._last_activity = time.time()
orch.wake_chime = True
orch._wake_refractory = 1.2
orch._last_wake_handled = 0.0
orch.wake_cooldown = 0.0

from security.kill_switch import KillSwitch

orch.kill_switch = KillSwitch()

from threading import Event

orch.thinking_abort = Event()


class _Busy:
    has_pending = lambda self: False
    cancel = lambda self: None


class _Recorder:
    is_active = lambda self: False
    cancel = lambda self: None


class _Agent:
    confirmations = _Busy()
    recorder = _Recorder()
    last_tool_receipt = None


orch.agent = _Agent()


class _Session(ConversationSession):
    pass


orch.session = ConversationSession(idle_timeout_seconds=60)

spoken = []

orch.on_jarvis_message = None
orch.on_user_message = None
orch.speak = lambda text: spoken.append(text)
orch._speak_until_done = lambda text: spoken.append(text)
orch._play_chime = lambda: spoken.append("[chime]")
orch.interrupt_speech = lambda: None
orch._emit_state = lambda state: None
orch._proactive_note = lambda: ""
orch.clean_for_speech = lambda text: text
orch._remember_turn = lambda user, reply: None
orch._judge_answer = lambda q, a: a
orch._say_session_farewell = lambda: (
    spoken.append("[farewell]"),
    orch.session.end("idle"),
)

# --- Exchange flow: utterance -> reply -> session survives silence.

turns = ["open notepad", "what time is it", "thanks"]

replies = ["Done.", "It's noon, sir.", "go_to_sleep"]

results = [
    {"success": True, "result": "Done."},
    {"success": True, "result": "It's noon, sir."},
    {
        "success": True,
        "result": "Goodbye, sir.",
        "go_to_sleep": True,
    },
]

state = {"index": 0}


def fake_process(text):
    index = state["index"]

    state["index"] += 1

    if results[index].get("go_to_sleep"):
        orch._session_end_requested = True

    return results[index]["result"]


orch.process = fake_process

# listen(): first call returns an utterance, then two SILENCE rounds
# (the old code would have ended the session after 4 exchanges or 6
# seconds — the session must hold), then the goodbye turn.
listen_results = ["open notepad", "", "", "what time is it", "thanks"]

state2 = {"index": 0}


def fake_listen():
    index = state2["index"]

    state2["index"] += 1

    if index < len(listen_results):
        return listen_results[index]

    return ""


orch.listen = fake_listen

_followup_calls = {"n": 0}


def fake_followup(start_timeout=6):
    _followup_calls["n"] += 1

    index = state2["index"]

    state2["index"] += 1

    if index < len(listen_results):
        return listen_results[index]

    return ""


orch._listen_followup = fake_followup

final = orch.listen_and_process()

check(
    "session: multi-exchange conversation holds through silence",
    _followup_calls["n"] >= 1,
    f"followups={_followup_calls['n']}",
)

check(
    "session: go_to_sleep ends the session cleanly",
    orch.session.state == SessionState.DORMANT
    and orch.session.end_reason() == "dismissed",
    f"state={orch.session.state}",
)

check(
    "session: replies spoken for every turn",
    len(spoken) >= 2,
    f"spoken={spoken}",
)

# --- Idle timeout with nothing pending -> farewell + DORMANT.

orch2 = Orchestrator.__new__(Orchestrator)

orch2.interrupt_requested = False
orch2.pending_wake_interrupt = False
orch2.pending_self_command = None
orch2._session_end_requested = False
orch2._processing_done = True
orch2.filming_mode = False
orch2.speaking = False
orch2.has_greeted = True
orch2.wake_chime = False
orch2.on_jarvis_message = None
orch2.on_user_message = None
orch2.kill_switch = KillSwitch()
orch2.thinking_abort = Event()
orch2.agent = _Agent()
orch2.session = ConversationSession(idle_timeout_seconds=60)
orch2.speak = lambda text: None
orch2._speak_until_done = lambda text: spoken.append(text)
orch2._play_chime = lambda: None
orch2.interrupt_speech = lambda: None
orch2._emit_state = lambda state: None
orch2._proactive_note = lambda: ""
orch2.clean_for_speech = lambda text: text
orch2._remember_turn = lambda user, reply: None
orch2._judge_answer = lambda q, a: a

orch2.listen = lambda: ""  # silence right away

farewell_spoken = []

orch2._say_session_farewell = lambda: (
    farewell_spoken.append(1),
    orch2.session.end("idle"),
)

orch2.listen_and_process()

check(
    "session: first-listen silence ends politely (no farewell)",
    not farewell_spoken,
)

# Long-idle silence: the idle clock must elapse DURING the mic call
# (activate/set_substate refresh it at every loop boundary — correct,
# since real interaction just happened). Simulate a mic that waited
# far past the timeout.
def silent_and_aged():
    orch2.session._last_activity -= 999

    return ""

orch2.listen = silent_and_aged

orch2.listen_and_process()

check(
    "session: idle timeout triggers farewell and DORMANT",
    bool(farewell_spoken)
    and orch2.session.state == SessionState.DORMANT,
    f"state={orch2.session.state}",
)


# ============================================================
# 3. WAKE PATH: chime + refractory (fake detector)
# ============================================================

orch3 = Orchestrator.__new__(Orchestrator)

orch3.pending_wake_interrupt = False
orch3.on_jarvis_message = None
orch3.on_user_message = None
orch3.wake_chime = True
orch3.wake_cooldown = 0.0
orch3.filming_mode = False
orch3.has_greeted = True
orch3.restart_acknowledged = False
orch3._last_activity = time.time()
orch3._last_wake_handled = 0.0
orch3._wake_refractory = 1.2
orch3.speaking = False
orch3.kill_switch = KillSwitch()
orch3.thinking_abort = Event()
orch3.agent = _Agent()
orch3.session = ConversationSession(idle_timeout_seconds=60)

chimes = []

orch3._play_chime = lambda: chimes.append(1)
orch3._speak_until_done = lambda text: spoken.append(text)
orch3._wakeup_greeting = lambda: None
orch3.interrupt_speech = lambda: None
orch3._emit_state = lambda state: None


class _FakeDetector:
    def __init__(self, fire=True):
        self.fire = fire
        self.last_transcript = ""

    def listen(self, cooldown=0.0):
        return self.fire


orch3.wake_word = _FakeDetector(fire=True)

woke = orch3.wait_for_wake_word(cooldown=0)

check(
    "wake: chime instead of spoken ack on re-wake",
    woke is True and len(chimes) == 1,
    f"chimes={chimes}",
)

# Refractory: an immediate second trigger is swallowed as an echo.
woke2 = orch3.wait_for_wake_word(cooldown=0)

check(
    "wake: refractory swallows echo re-trigger",
    woke2 is False and len(chimes) == 1,
    f"woke2={woke2} chimes={chimes}",
)

# After the refractory window a real second wake fires again.
orch3._last_wake_handled -= 5

woke3 = orch3.wait_for_wake_word(cooldown=0)

check(
    "wake: second real wake handled",
    woke3 is True and len(chimes) == 2,
    f"woke3={woke3} chimes={chimes}",
)

# Session was activated by the wake.
check(
    "wake: session active after wake",
    orch3.session.state
    in {SessionState.ACTIVE, SessionState.LISTENING},
    f"state={orch3.session.state}",
)


# ============================================================
# 4. BUDGETED STEP LOOP (config max_reasoning_steps)
# ============================================================

import json

from ai.agent_runtime import AgentRuntime


class FakeProvider:
    def __init__(self, decisions):
        self.decisions = list(decisions)

    def generate(self, prompt):
        if self.decisions:
            return self.decisions.pop(0)

        return json.dumps({"type": "speak", "speech": "done"})


# Six chained steps with "then": true, then a closing speak.
decisions = []

for i in range(6):
    decisions.append(
        json.dumps(
            {
                "type": "action",
                "tool": "system.cpu",
                "parameters": {},
                "then": True,
            }
        )
    )

decisions.append(
    json.dumps(
        {
            "type": "speak",
            "speech": "All six checks finished, sir.",
        }
    )
)

runtime = AgentRuntime(FakeProvider(decisions))

executed = []


def fake_execute(tool_name, parameters=None):
    executed.append(tool_name)

    return {
        "success": True,
        "result": {"message": f"cpu {len(executed)}%"},
    }


runtime.tools.execute = fake_execute

result = runtime.process("run six diagnostics", context="")

check(
    "budget: 6-step task fits in one request (v3 cap was 4)",
    len(executed) == 6
    and "six checks" in str(result.get("result", "")).lower(),
    f"executed={len(executed)} result={result}",
)

check(
    "budget: loop budget respects config value",
    runtime.brain_loop.max_steps >= 6,
    f"max_steps={runtime.brain_loop.max_steps}",
)


# ============================================================
# SUMMARY
# ============================================================

print()

if failures:
    print(f"FAILED: {failures} check(s)")
    sys.exit(1)

print("ALL PHASE-1 TESTS PASSED")
sys.exit(0)
