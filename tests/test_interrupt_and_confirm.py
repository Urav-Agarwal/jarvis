"""
Offline tests for the interrupt / confirmation / self-lifecycle fixes:

- fuzzy confirmation yes/no (voice-friendly)
- confirmation never loops; other input cancels and is processed fresh
- stop phrases clear plans/choices/confirmations
- self shutdown / restart detection
- capability questions (teach / remember / what can you do)
- teaching flow end-to-end with a scripted fake LLM
- memory remember -> recall round trip through ToolRuntime
- TTS barge-in: stop_speaking flips speak() to interrupted

Run with:
    PYTHONIOENCODING=utf-8 python -m tests.test_interrupt_and_confirm
"""

import io
import json
import os
import sys
import tempfile
import threading
import time
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai.agent_runtime import AgentRuntime
from ai.tool_catalogue import ToolCatalogue
from ai.tool_runtime import ToolRuntime
from tools.skill_store import SkillStore
from tools.reminders import ReminderStore

failures = 0


def check(name, condition, detail=""):
    global failures

    if condition:
        print(f"[PASS] {name}")
    else:
        failures += 1
        print(f"[FAIL] {name} {detail}")


class FakeProvider:
    """
    Scripted LLM stand-in: answers with canned decisions, records every
    prompt it was given. No network calls.
    """

    def __init__(self):
        self.script = []
        self.prompts = []

    def queue(self, *responses):
        self.script.extend(responses)

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)

        if self.script:
            return self.script.pop(0)

        return json.dumps({"type": "question", "request": prompt[-200:]})


def make_runtime(provider):
    runtime = AgentRuntime(provider)
    return runtime


def stub_tool_execution(runtime):
    """
    Replace ToolRuntime.execute with a recorder so tests NEVER touch
    real system tools (a previous run executed system.shutdown for real
    and rebooted the laptop — this stub is mandatory).
    """

    calls = []

    def fake_execute(tool_name, parameters=None):
        calls.append((tool_name, parameters))

        return {
            "success": True,
            "result": {"message": f"[stub] would run {tool_name}"},
        }

    runtime.tools.execute = fake_execute

    return calls


# ============================================================
# FUZZY CONFIRMATION
# ============================================================

provider = FakeProvider()
runtime = make_runtime(provider)
tool_calls = stub_tool_execution(runtime)

# Script the routing decision for the gated request (real LLM would
# return this JSON for "Shut down my laptop").
provider.queue(
    json.dumps(
        {
            "type": "action",
            "tool": "system.shutdown",
            "parameters": {},
        }
    )
)

asked = runtime.process(
    "Shut down my laptop",
    context="",
)

check(
    "high_risk_asks_confirmation",
    asked.get("confirmation_required") is True,
    asked,
)

for phrase in [
    "yes",
    "yes sir",
    "yeah sure",
    "yep",
    "Yep, do it",
    "sure",
    "okay",
    "go ahead",
    "proceed",
]:
    runtime.confirmations.request_confirmation(
        "system.shutdown",
        {},
        "shut down your laptop",
    )

    result = runtime.process(phrase, context="")

    check(
        f"fuzzy_yes[{phrase}]",
        "cancelled" not in result.get("result", "").lower()
        and "please answer" not in result.get("result", "").lower(),
        result,
    )

runtime.confirmations.request_confirmation(
    "system.shutdown",
    {},
    "shut down your laptop",
)

denied = runtime.process("no", context="")

check(
    "fuzzy_no_cancels",
    "cancelled" in denied.get("result", "").lower(),
    denied,
)

# Non-matching input must NOT re-ask; it cancels and processes fresh.
# (v4 note: "what time is it" is now a zero-LLM reflex, so a scripted
# response would never be consumed — use a request that still reaches
# the reasoning loop.)
runtime.confirmations.request_confirmation(
    "system.shutdown",
    {},
    "shut down your laptop",
)

provider.queue(
    json.dumps(
        {"type": "question", "request": "What is the capital of France?"}
    )
)

other = runtime.process("what is the capital of france", context="")

check(
    "other_input_cancels_and_processes",
    "please answer" not in other.get("result", "").lower()
    and "cancelled" not in other.get("result", "").lower(),
    other,
)

check(
    "pending_cleared_after_other_input",
    runtime.confirmations.has_pending() is False,
)

# ============================================================
# STOP / CANCEL
# ============================================================

runtime._remaining_plan = [("system.cpu", {})]
runtime._last_choices = [{"name": "x", "path": "C:/x"}]
runtime.confirmations.request_confirmation("system.lock", {}, "lock your laptop")

stopped = runtime.process("stop", context="")

check(
    "stop_clears_everything",
    runtime._remaining_plan == []
    and runtime._last_choices == []
    and runtime.confirmations.has_pending() is False
    and (
        "stopped" in stopped.get("result", "").lower()
        or "cancelled" in stopped.get("result", "").lower()
    ),
    (stopped, runtime._remaining_plan, runtime._last_choices),
)

# "stop" with NOTHING pending must also succeed gracefully.
plain_stop = runtime.process("stop", context="")

check(
    "plain_stop_ok",
    "stopped" in plain_stop.get("result", "").lower(),
    plain_stop,
)

# ============================================================
# LAPTOP SHUTDOWN STILL ROUTES THROUGH THE GATE
# ============================================================

provider.queue(
    json.dumps(
        {
            "type": "action",
            "tool": "system.shutdown",
            "parameters": {},
        }
    )
)

gated = runtime.process("shut down my laptop", context="")

check(
    "laptop_shutdown_still_gated",
    gated.get("confirmation_required") is True
    and runtime.confirmations.has_pending() is True,
    gated,
)

runtime.confirmations.cancel()

# Confirming a gated action routes through ToolRuntime exactly once
# and reports the stubbed result (no real system tool ever ran).
runtime.confirmations.request_confirmation(
    "system.shutdown",
    {},
    "shut down your laptop",
)

confirmed = runtime.process("yes", context="")

check(
    "confirm_executes_via_tool_runtime",
    tool_calls and tool_calls[-1][0] == "system.shutdown"
    and "would run system.shutdown" in confirmed.get("result", ""),
    (confirmed, tool_calls),
)

# ============================================================
# SELF COMMANDS
# ============================================================

check(
    "self_shutdown_detected",
    runtime.process("Jarvis, shutdown yourself", context="").get(
        "self_shutdown"
    )
    is True,
)

check(
    "self_restart_detected",
    runtime.process("restart yourself", context="").get("self_restart")
    is True,
)

check(
    "self_restart_creative",
    runtime.process("hey jarvis, reboot yourself now", context="").get(
        "self_restart"
    )
    is True,
)

# ============================================================
# CAPABILITY QUESTIONS (deterministic, no LLM)
# ============================================================

for phrase, marker in [
    ("How do I teach you new tasks?", "whenever I say"),
    ("Will you remember if I tell you to remember something?", "remember that"),
    ("What can you do?", "screenshot"),
]:
    answer = runtime.process(phrase, context="")

    check(
        f"capability_answer[{phrase[:22]}]",
        marker.lower() in answer.get("result", "").lower(),
        answer,
    )

# ============================================================
# TEACHING FLOW + SKILL TRIGGER (scripted fake LLM)
# ============================================================

skill_path = os.path.join(tempfile.gettempdir(), "jarvis_it_skills.json")
teach_runtime = make_runtime(FakeProvider())
stub_tool_execution(teach_runtime)
teach_runtime.tools.skills = SkillStore(
    path=skill_path,
    tool_validator=ToolCatalogue().get_tool,
)

teach_runtime.provider.queue(
    json.dumps(
        {
            "type": "plan",
            "description": "study setup",
            "actions": [
                {
                    "tool": "application.open",
                    "parameters": {"application": "Notepad"},
                    "description": "open notepad",
                    "depends_on": [],
                }
            ],
        }
    )
)

taught = teach_runtime.process(
    "Whenever I say study setup, open Notepad",
    context="",
)

check(
    "teaching_asks_for_name",
    taught.get("success") is True
    and "what should i call this" in taught.get("result", "").lower(),
    taught,
)

named = teach_runtime.process("call it study setup", context="")

check(
    "teaching_saves_skill",
    named.get("success") is True and "saved" in named.get("result", "").lower(),
    named,
)

check(
    "taught_trigger_fires",
    teach_runtime.tools.skills.find_by_trigger("study setup") is not None,
)

check(
    "taught_trigger_fires_fuzzy",
    teach_runtime.tools.skills.find_by_trigger(
        "get my study setup ready"
    ) is not None,
)

# ============================================================
# MEMORY ROUND TRIP THROUGH RUNTIME
# ============================================================

mem_runtime = make_runtime(FakeProvider())
mem_calls = stub_tool_execution(mem_runtime)

# Real tools for memory only — recall must read the real store so we
# can verify the fact actually comes back out.
real_execute = ToolRuntime().execute

def selective_execute(tool_name, parameters=None):
    mem_calls.append((tool_name, parameters))

    if tool_name.startswith("memory."):
        return real_execute(tool_name, parameters)

    return {
        "success": True,
        "result": {"message": f"[stub] would run {tool_name}"},
    }

mem_runtime.tools.execute = selective_execute

# Script the routing decisions the real LLM would produce.
mem_runtime.provider.queue(
    json.dumps(
        {
            "type": "action",
            "tool": "memory.remember",
            "parameters": {
                "information": "my physics exam is on October 5",
            },
        }
    )
)

remembered = mem_runtime.process(
    "Remember that my physics exam is on October 5",
    context="",
)

mem_runtime.provider.queue(
    json.dumps(
        {
            "type": "action",
            "tool": "memory.recall",
            "parameters": {"query": "physics exam"},
        }
    )
)

recalled = mem_runtime.process(
    "What do you remember about my physics exam?",
    context="",
)

used_tools = [name for name, _params in mem_calls]

check(
    "memory_remember_routed",
    "memory.remember" in used_tools
    and "october 5" in json.dumps(mem_calls[0][1]).lower(),
    mem_calls,
)

check(
    "memory_recall_routed",
    used_tools[-1:] == ["memory.recall"],
    mem_calls,
)

check(
    "memory_recall_spoken",
    "october 5" in recalled.get("result", "").lower(),
    recalled,
)

# ============================================================
# TTS BARGE-IN MECHANISM
# ============================================================

from audio.text_to_speech import TextToSpeech

tts = TextToSpeech.__new__(TextToSpeech)

# __init__ is bypassed by __new__, so the attributes it normally
# sets must be provided here (False = exercise the local piper path).
tts.use_elevenlabs = False
tts._piper_voice = None
tts._http = None

import threading as _threading

tts.stop_event = _threading.Event()

def fake_synthesize(text):
    for i in range(50):
        if tts.stop_event.is_set():
            return

        time.sleep(0.01)

        class FakeChunk:
            audio_int16_bytes = b"\x00\x00"

        yield FakeChunk()

class FakeVoice:
    config = type("Cfg", (), {"sample_rate": 16000})()

    def synthesize(self, text):
        return fake_synthesize(text)

tts.voice = FakeVoice()

import audio.text_to_speech as tts_module


class FakeStream:
    def __init__(self, *a, **k):
        pass

    def start(self):
        pass

    def write(self, data):
        time.sleep(0.02)

    def stop(self):
        pass

    def close(self):
        pass


original_output_stream = tts_module.sd.OutputStream
tts_module.sd.OutputStream = FakeStream

spoken_result = {}

def delayed_stop():
    time.sleep(0.15)
    tts.stop_speaking()

stopper = threading.Thread(target=delayed_stop)
stopper.start()

spoken_result["finished"] = tts.speak("a long sentence that should be cut off")

stopper.join()
tts_module.sd.OutputStream = original_output_stream

check(
    "tts_barge_in_interrupts",
    spoken_result["finished"] is False,
    spoken_result,
)

check(
    "tts_stop_event_cleared_after_speak",
    tts.stop_event.is_set() is False,
)

# ============================================================
# SUMMARY
# ============================================================

print()

if failures:
    print(f"FAILED: {failures}")
    raise SystemExit(1)

print("ALL INTERRUPT/CONFIRM TESTS PASSED")
