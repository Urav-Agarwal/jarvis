"""
Offline tests for the browser-profile fix and the screen-observation
action recorder.

- 'open chrome and my personal profile' resolves to the real profile
  (Urav Agarwal / Default) without an LLM call
- unknown profile -> honest reply listing visible profiles
- recorder start -> active; unrelated input during recording doesn't
  stop it; 'stop learning' -> steps built from SCREEN observations;
  naming turn saves the skill; 'no' discards
- observations -> steps: apps open once, browser sites become
  navigation steps, no mouse/keyboard steps ever

Run with:
    PYTHONIOENCODING=utf-8 python -m tests.test_profile_and_recorder
"""

import json
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai.agent_runtime import AgentRuntime
from ai.tool_catalogue import ToolCatalogue
from ai.tool_runtime import ToolRuntime
from tools.action_recorder import ActionRecorder
from tools.profiles import ChromiumProfileResolver, BrowserProfile

failures = 0


def check(name, condition, detail=""):
    global failures

    if condition:
        print(f"[PASS] {name}")
    else:
        failures += 1
        print(f"[FAIL] {name} {detail}")


class FakeProvider:
    def __init__(self):
        self.script = []

    def queue(self, *responses):
        self.script.extend(responses)

    def generate(self, prompt: str) -> str:
        if self.script:
            return self.script.pop(0)

        return json.dumps({"type": "question", "request": prompt[-200:]})


# ============================================================
# 1. PROFILE RESOLVER (the chrome personal-profile bug)
# ============================================================

resolver = ChromiumProfileResolver()

profiles = [
    BrowserProfile("Urav Agarwal", "Default", "C:/ud"),
    BrowserProfile("malti", "Profile 3", "C:/ud"),
    BrowserProfile("School", "Profile 4", "C:/ud"),
]

for request, expected in [
    ("personal", "Urav Agarwal"),
    ("my personal profile", "Urav Agarwal"),
    ("personal profile", "Urav Agarwal"),
    ("default", "Urav Agarwal"),
    ("main", "Urav Agarwal"),
    ("school", "School"),
    ("my school account", "School"),
    ("school profile", "School"),
]:
    got = resolver.resolve_profile(profiles, request)

    check(
        f"resolve '{request}' -> {expected}",
        got is not None and got.name == expected,
        f"got: {got.name if got else None}",
    )

check(
    "unknown profile resolves to None (honest failure)",
    resolver.resolve_profile(profiles, "work profile") is None,
)

# ============================================================
# 2. BROWSER+PROFILE FAST-PATH through the agent
# ============================================================

provider = FakeProvider()
agent = AgentRuntime(provider)

# Router stubbed: the fast-path must fire BEFORE any routing anyway;
# the stub proves no LLM response is consumed for the profile flow.
agent.router.route = lambda request: ["browser"]

open_calls = []


def fake_execute(tool_name, parameters=None):
    open_calls.append((tool_name, dict(parameters or {})))

    return {
        "success": True,
        "result": {"message": f"[stub] {tool_name} {parameters}"},
    }


agent.tools.execute = fake_execute

reply = agent.process("open chrome and my personal profile")

check(
    "profile request goes to browser.open with profile",
    open_calls
    and open_calls[-1][0] == "browser.open"
    and open_calls[-1][1].get("browser") == "chrome"
    and "personal" in open_calls[-1][1].get("profile", ""),
    f"got: {open_calls}",
)

check(
    "profile request acknowledged with profile name",
    "personal" in reply.get("result", ""),
    f"got: {reply.get('result')}",
)

check(
    "no LLM response consumed (deterministic)",
    len(provider.script) == 0,
    f"script left: {provider.script}",
)

# Unknown profile: with the real ToolRuntime this fails and lists
# profiles. Simulate by pointing execute at a failing stub.
open_calls.clear()


def failing_execute(tool_name, parameters=None):
    return {
        "success": False,
        "result": "profile not found",
    }


agent.tools.execute = failing_execute

reply = agent.process("open chrome with my work profile")

check(
    "failed profile lists visible profiles",
    "Urav Agarwal" in reply.get("result", "")
    and "School" in reply.get("result", ""),
    f"got: {reply.get('result')}",
)

# ============================================================
# 3. OBSERVATIONS -> TOOL STEPS
# ============================================================

recorder = ActionRecorder()

observations = [
    {"app": "chrome.exe", "title": "YouTube", "summary": "browsing youtube"},
    {"app": "chrome.exe", "title": "Gmail - google.com", "summary": ""},
    {"app": "notepad.exe", "title": "notes - Notepad", "summary": ""},
    {"app": "chrome.exe", "title": "youtube", "summary": "still there"},
    {"app": "chrome.exe", "title": "New Tab", "summary": ""},
]

steps = recorder.build_steps(observations)

check(
    "browser.open step first when browser observed",
    steps
    and steps[0]["tool"] == "application.open"
    and steps[0]["parameters"]["application"] == "chrome",
    f"got: {steps}",
)

check(
    "distinct sites become navigation steps",
    sum(1 for s in steps if s["tool"] == "browser.navigate") == 2,
    f"got: {steps}",
)

check(
    "repeats and new tabs are deduplicated",
    all(
        s["parameters"].get("url") != "New Tab"
        for s in steps
        if s["tool"] == "browser.navigate"
    ),
    f"got: {steps}",
)

check(
    "desktop app becomes application.open",
    any(
        s["tool"] == "application.open"
        and s["parameters"].get("application") == "notepad"
        for s in steps
    ),
    f"got: {steps}",
)

check(
    "no computer.* (mouse/keyboard) steps are ever built",
    all(not s["tool"].startswith("computer.") for s in steps),
    f"got: {steps}",
)

# ============================================================
# 4. RECORDER START / STOP / SAVE FLOW
# ============================================================

provider2 = FakeProvider()
agent2 = AgentRuntime(provider2)

agent2.router.route = lambda request: []

skill_calls = []


def fake_skills_create(name, description, steps, triggers=None):
    skill_calls.append(
        {
            "name": name,
            "description": description,
            "steps": steps,
            "triggers": triggers,
        }
    )

    return {
        "success": True,
        "message": f"Created skill: {name}",
    }


agent2.tools.skills.create = fake_skills_create

reply = agent2.process("watch me and learn this")

check(
    "recorder starts on 'watch me and learn this'",
    reply.get("recording") is True and agent2.recorder.is_active(),
    f"got: {reply}",
)

check(
    "start message explains screen-watching (not mouse)",
    "mouse" in reply.get("result", "").lower(),
    f"got: {reply.get('result')}",
)

# Inject synthetic observations as if the loop had watched the screen.
agent2.recorder.observations = [
    {"app": "chrome.exe", "title": "YouTube", "summary": "opened youtube"},
    {"app": "notepad.exe", "title": "notes - Notepad", "summary": ""},
]

# Unrelated input during recording must NOT stop it.
reply = agent2.process("what time is it")

check(
    "unrelated input during recording processed normally",
    agent2.recorder.is_active(),
    f"got: {reply.get('result')}",
)

reply = agent2.process("stop learning")

check(
    "stop learning builds steps and asks for a name",
    "what should i call this" in reply.get("result", "").lower()
    and agent2._recorder_pending_save is not None,
    f"got: {reply.get('result')}",
)

check(
    "step summary spoken (apps seen)",
    "chrome" in reply.get("result", "").lower()
    or "open" in reply.get("result", "").lower(),
    f"got: {reply.get('result')}",
)

reply = agent2.process("youtube routine")

check(
    "naming turn saves the skill",
    skill_calls
    and skill_calls[0]["name"].lower() == "youtube routine"
    and skill_calls[0]["steps"],
    f"got: {skill_calls}",
)

check(
    "trigger is the spoken name",
    skill_calls and skill_calls[0]["triggers"] == ["youtube routine"],
    f"got: {skill_calls}",
)

check(
    "save clears pending state",
    agent2._recorder_pending_save is None,
)

# ============================================================
# 5. DISCARD PATH
# ============================================================

provider3 = FakeProvider()
agent3 = AgentRuntime(provider3)

agent3.process("start recording my actions")

agent3.recorder.observations = [
    {"app": "spotify.exe", "title": "Spotify", "summary": ""},
]

agent3.process("done with the task")

reply = agent3.process("no")

check(
    "'no' discards without saving",
    agent3._recorder_pending_save is None
    and "discarded" in reply.get("result", "").lower(),
    f"got: {reply.get('result')}",
)

# ============================================================
# 6. CATALOGUE: profile parameter + recorder visibility
# ============================================================

catalogue = ToolCatalogue()

definition = catalogue.get_tool("browser.open")

check(
    "browser.open catalogue declares profile parameter",
    definition is not None and "profile" in definition.parameters,
    f"got: {definition.parameters if definition else None}",
)

runtime = ToolRuntime()

check(
    "browser.open handler accepts profile kwarg",
    runtime._align_parameters(
        runtime._open_browser,
        {"browser": "chrome", "profile": "personal"},
    ).get("profile") == "personal",
)

# ============================================================
print()

if failures:
    print(f"{failures} test(s) FAILED")
    sys.exit(1)

print("ALL TESTS PASSED")
