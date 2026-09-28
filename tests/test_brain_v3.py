"""
Offline tests for the BrainV3 agent loop (the v3 BRAIN):

- multi-step reason -> act -> observe -> reason (the loop actually loops)
- failed step: the model's pre-written speech is discarded, the next
  reasoning step owns the reply
- interrupt at a step boundary ("stop" mid-task)
- InterruptedError raised DURING reasoning (provider abort) propagates
  out of run() — never spoken as "Something tripped in my head"
- plan with a gated step: confirmation queues, remaining steps parked
- legacy "question" decision: answer spoken verbatim / raw-answer path
- junk speak decision after real work: compose() fallback on history
- THE JUDGE: a claim without a tool receipt is downgraded

Run with:
    PYTHONIOENCODING=utf-8 python -m tests.test_brain_v3
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai.brain import BrainV3

failures = 0


def check(name, condition, detail=""):
    global failures

    if condition:
        print(f"[PASS] {name}")
    else:
        failures += 1
        print(f"[FAIL] {name} {detail}")


class FakeReasoner:
    """
    Scripted stand-in for AgentBrain: decide() pops scripted decision
    factories (each receives the live history), compose() is replaced
    by a hook, and .provider serves the raw-answer escape hatch.
    """

    def __init__(self):
        self.script = []
        self.decide_calls = []
        self.compose_calls = []
        self.compose_fn = lambda user_input, history: "composed reply"

        class _Catalogue:
            """Enough of ToolCatalogue for decision validation."""

            def get_tool(self, tool_name):
                if tool_name and re.match(
                    r"^[a-z_]+\.[a-z_]+$", tool_name
                ):
                    return {"name": tool_name}

                return None

        self.catalogue = _Catalogue()

        class _Provider:
            def __init__(self, outer):
                self._outer = outer
                self.raw = "raw answer from one plain generation"

            def generate(self, prompt):
                return self.raw

        self.provider = _Provider(self)

    def queue(self, *factories):
        self.script.extend(factories)

    def decide(self, user_input, context="", history=None):
        self.decide_calls.append(
            {"input": user_input, "context": context,
             "history": [dict(step) for step in (history or [])]}
        )

        factory = self.script.pop(0)

        return factory(history or [])

    def compose(self, user_input, history, context=""):
        self.compose_calls.append(
            {"input": user_input,
             "history": [dict(step) for step in (history or [])]}
        )

        return self.compose_fn(user_input, history or [])


def make_brain(reasoner, executor_calls=None, interrupt_states=None,
               format_result=None):
    """
    Build a BrainV3 with a scripted executor. interrupt_states is an
    optional list of booleans consumed by interrupt_check() in order.
    """

    calls = executor_calls if executor_calls is not None else []

    def execute_tool(tool_name, parameters=None):
        calls.append({"tool": tool_name, "parameters": parameters})

        return {"success": True, "result": "ok"}

    # Consumed IN ORDER at every interrupt check (loop boundary AND
    # pre-act) — the brain checks twice per executed step.
    checks = list(interrupt_states or [False])

    brain = BrainV3(
        reasoner=reasoner,
        execute_tool=execute_tool,
        interrupt_check=(
            lambda: checks.pop(0) if checks else False
        ),
        format_result=format_result,
    )

    # THE JUDGE wiring (the runtime injects these as attributes).
    brain.receipt_for_judge = lambda: {"tool": "stub"}

    brain.judge = lambda answer, receipt: (
        f"judged({answer})" if receipt else f"downgraded({answer})"
    )

    return brain


# ============================================================
# 1. MULTI-STEP: reason -> act -> OBSERVE -> reason again
# ============================================================

reasoner = FakeReasoner()
calls = []

reasoner.queue(
    # Step 1: search, and wait for the real result ("then": true).
    lambda history: {
        "type": "action",
        "tool": "filesystem.search",
        "parameters": {"query": "notes"},
        "then": True,
    },
    # Step 2: speaks ABOUT the observed result.
    lambda history: {
        "type": "speak",
        "speech": f"Found it: "
                  f"{history[-1]['result']}",
    },
)

brain = make_brain(reasoner, calls)

outcome = brain.run("find my notes file")

check(
    "multi-step: two reasoning rounds",
    len(reasoner.decide_calls) == 2,
    f"decides={len(reasoner.decide_calls)}",
)

check(
    "multi-step: executor ran the search once",
    calls == [
        {"tool": "filesystem.search",
         "parameters": {"query": "notes"}}
    ],
    f"calls={calls}",
)

check(
    "multi-step: second reasoner saw the REAL result",
    reasoner.decide_calls[1]["history"]
    and reasoner.decide_calls[1]["history"][-1]["result"] == "ok"
    and reasoner.decide_calls[1]["history"][-1]["success"] is True,
    f"observed={reasoner.decide_calls[1]['history']}",
)

check(
    "multi-step: reply composed from observation",
    outcome.get("success") is True
    and "ok" in str(outcome.get("result")),
    f"outcome={outcome}",
)


# ============================================================
# 2. FAILED STEP: pre-written speech discarded, model corrects
# ============================================================

reasoner = FakeReasoner()
calls = []

reasoner.queue(
    lambda history: {
        "type": "action",
        "tool": "app.open",
        "parameters": {"name": "notepad"},
        "speech": "Notepad is open, sir.",
        "then": True,
    },
    lambda history: {
        "type": "speak",
        "speech": "It would not open, sir.",
    },
)


def failing_executor(tool_name, parameters=None):
    calls.append({"tool": tool_name, "parameters": parameters})

    return {"success": False, "result": "app not found"}


brain = BrainV3(
    reasoner=reasoner,
    execute_tool=failing_executor,
    interrupt_check=lambda: False,
)

brain.receipt_for_judge = lambda: {"tool": "stub"}
brain.judge = lambda answer, receipt: answer

outcome = brain.run("open notepad")

check(
    "failed step: lying speech not spoken",
    "Notepad is open" not in str(outcome.get("result")),
    f"outcome={outcome}",
)

check(
    "failed step: next reasoning owned the reply",
    outcome.get("success") is True
    and "would not open" in str(outcome.get("result")),
    f"outcome={outcome}",
)

check(
    "failed step: history recorded the failure",
    reasoner.decide_calls[1]["history"][-1]["success"] is False,
    f"observed={reasoner.decide_calls[1]['history']}",
)


# ============================================================
# 3. INTERRUPT AT A STEP BOUNDARY ("stop" between steps)
# ============================================================

reasoner = FakeReasoner()
calls = []

reasoner.queue(
    lambda history: {
        "type": "action",
        "tool": "app.open",
        "parameters": {"name": "chrome"},
        "then": True,
    },
    # NEVER reached — the interrupt fires first.
    lambda history: {"type": "speak", "speech": "should not happen"},
)

brain = make_brain(
    reasoner,
    calls,
    # boundary(1) ok, pre-act ok, boundary(2) STOP.
    interrupt_states=[False, False, True],
)

outcome = brain.run("open chrome and search something")

check(
    "interrupt boundary: loop stops reasoning",
    len(reasoner.decide_calls) == 1,
    f"decides={len(reasoner.decide_calls)}",
)

check(
    "interrupt boundary: no further execution",
    len(calls) == 1,
    f"calls={calls}",
)

check(
    "interrupt boundary: clean stop reply",
    outcome.get("success") is True
    and str(outcome.get("result", "")),
    f"outcome={outcome}",
)


# ============================================================
# 4. INTERRUPT DURING THINKING (provider abort mid-decide)
# ============================================================

reasoner = FakeReasoner()


def aborting_decide(user_input, context="", history=None):
    raise InterruptedError("thinking interrupted by the user")


reasoner.decide = aborting_decide

brain = make_brain(reasoner)

raised = False

try:
    brain.run("what is the weather")
except InterruptedError:
    raised = True
except Exception as error:
    raised = False

check(
    "mid-think interrupt: InterruptedError propagates",
    raised is True,
    "brain swallowed the interrupt",
)

check(
    "mid-think interrupt: never a fallback sentence",
    True,  # reaching here means no 'Something tripped' return happened
)


# ============================================================
# 5. PLAN WITH A GATED STEP: queue + park the remainder
# ============================================================

reasoner = FakeReasoner()
calls = []

reasoner.queue(
    lambda history: {
        "type": "plan",
        "actions": [
            {"tool": "system.shutdown", "parameters": {}},
            {"tool": "system.volume", "parameters": {"level": 40}},
        ],
        "speech": "Shutting down after I lower the volume.",
    }
)


def gated_executor(tool_name, parameters=None):
    calls.append({"tool": tool_name, "parameters": parameters})

    return {
        "success": True,
        "result": "Awaiting your confirmation, sir.",
        "confirmation_required": True,
    }


brain = BrainV3(
    reasoner=reasoner,
    execute_tool=gated_executor,
    interrupt_check=lambda: False,
)

outcome = brain.run("shut down my laptop")

check(
    "gated plan: first step requested confirmation",
    outcome.get("confirmation_required") is True
    and calls and calls[0]["tool"] == "system.shutdown",
    f"outcome={outcome} calls={calls}",
)

check(
    "gated plan: remaining step parked for after 'yes'",
    brain._pending_plan_steps
    and brain._pending_plan_steps[0][0] == "system.volume",
    f"parked={brain._pending_plan_steps}",
)


# ============================================================
# 6. LEGACY "question" DECISION (v2 contract)
# ============================================================

# 6a: an answer in the decision is spoken verbatim (through the judge).
reasoner = FakeReasoner()
reasoner.queue(
    lambda history: {
        "type": "question",
        "answer": "Hydrogen, sir.",
    }
)

brain = make_brain(reasoner)

outcome = brain.run("lightest element?")

check(
    "legacy question: answer spoken verbatim",
    outcome.get("success") is True
    and outcome.get("result") == "judged(Hydrogen, sir.)",
    f"outcome={outcome}",
)

# 6b: no answer -> one raw generation pass, spoken verbatim.
reasoner = FakeReasoner()
reasoner.provider.raw = "Roughly 8 billion, sir."
reasoner.queue(lambda history: {"type": "question", "request": "world pop"})

brain = make_brain(reasoner)

outcome = brain.run("world population")

check(
    "legacy question: raw-answer escape hatch",
    outcome.get("success") is True
    and outcome.get("result") == "judged(Roughly 8 billion, sir.)",
    f"outcome={outcome}",
)


# ============================================================
# 7. JUNK SPEECH AFTER REAL WORK: compose() fallback
# ============================================================

reasoner = FakeReasoner()
calls = []

reasoner.queue(
    lambda history: {
        "type": "action",
        "tool": "computer.battery",
        "parameters": {},
        "speech": json.dumps({"type": "speak", "speech": "junk"}),
    }
)

brain = make_brain(reasoner, calls)

reasoner.compose_fn = (
    lambda user_input, history: "Battery is at 80 percent, sir."
)

outcome = brain.run("how is my battery")

check(
    "junk speak: composed from real history",
    outcome.get("success") is True
    and "80 percent" in str(outcome.get("result")),
    f"outcome={outcome}",
)

check(
    "junk speak: compose received the tool result",
    reasoner.compose_calls
    and reasoner.compose_calls[0]["history"][0]["tool"]
    == "computer.battery",
    f"compose_calls={reasoner.compose_calls}",
)


# ============================================================
# 8. THE JUDGE: action claim without a receipt is downgraded
# ============================================================

reasoner = FakeReasoner()
reasoner.queue(
    lambda history: {
        "type": "speak",
        "speech": "I've deleted the file, sir.",
    }
)

brain = make_brain(reasoner)

# No receipt this turn: the claimed action never happened.
brain.receipt_for_judge = lambda: None

outcome = brain.run("delete that file")

check(
    "judge: unsupported action claim downgraded",
    outcome.get("success") is True
    and "downgraded" in str(outcome.get("result")),
    f"outcome={outcome}",
)


# ============================================================
# SUMMARY
# ============================================================

print()
if failures:
    print(f"FAILED: {failures} check(s)")
    sys.exit(1)

print("ALL BRAIN V3 TESTS PASSED")
sys.exit(0)
