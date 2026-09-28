"""
Round-3 behavior tests: sleep phrase, news routing, STT filler
cleanup, messaging catalogue sync. No network, no audio, no GUI.

Run:
    PYTHONIOENCODING=utf-8 python -m tests.test_round3
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai.agent_runtime import AgentRuntime
from ai.tool_runtime import ToolRuntime
from ai.tool_catalogue import ToolCatalogue
from audio.speech_to_text import SpeechToText
from router.capability_router_v2 import CapabilityRouter

failures = 0


def check(name, condition, detail=""):
    global failures

    if condition:
        print(f"[PASS] {name}")
    else:
        failures += 1
        print(f"[FAIL] {name} {detail}")


class FakeProvider:
    def queue(self, *responses):
        self.script = list(responses)

    def generate(self, prompt):
        return getattr(self, "script", ["{}"]).pop(0)


def stub(runtime):
    runtime.tools.execute = lambda tool, params=None: {
        "success": True,
        "result": {"message": f"[stub] {tool}"},
    }


# ============================================================
# SLEEP / GOODBYE
# ============================================================

runtime = AgentRuntime(FakeProvider())
stub(runtime)

sleep_cases = [
    "thank you, I don't need you anymore",
    "thanks that's all",
    "goodbye jarvis",
    "go to sleep now",
    "good night",
]

for phrase in sleep_cases:
    result = runtime.process(phrase, context="")

    check(
        f"sleep_phrase[{phrase[:24]}]",
        result.get("go_to_sleep") is True
        and "Hey JARVIS" in result.get("result", ""),
        result,
    )

# Normal thanks must NOT trigger sleep.
normal = runtime.process("thank you", context="")

check(
    "plain_thanks_no_sleep",
    normal.get("go_to_sleep") is not True,
    normal,
)

# ============================================================
# NEWS ROUTING (deterministic web)
# ============================================================

router = CapabilityRouter(FakeProvider())

for phrase in [
    "what are the updates on ChatGPT",
    "any news on the ISRO launch",
    "what is the latest version of Python",
    "give me the latest news",
]:
    caps = router.route(phrase)

    check(
        f"news_route[{phrase[:26]}]",
        caps == ["web"],
        caps,
    )

# Non-news requests must not be hijacked.
check(
    "news_no_false_positive",
    router.route("open my notes") != ["web"],
)

# ============================================================
# STT FILLER CLEANUP
# ============================================================

check(
    "stt_filler_removed",
    SpeechToText._clean("um so open uh whatsapp") == "so open whatsapp",
    SpeechToText._clean("um so open uh whatsapp"),
)

check(
    "stt_fragment_rejected",
    SpeechToText._clean("mm") == "",
)

check(
    "stt_real_phrase_kept",
    SpeechToText._clean("hey jarvis what time is it")
    == "hey jarvis what time is it",
)

# ============================================================
# CATALOGUE SYNC (new messaging + tabs tools)
# ============================================================

advertised = {tool.name for tool in ToolCatalogue().get_tools()}
implemented = set(ToolRuntime()._handlers)

check(
    "catalogue_runtime_sync_round3",
    advertised == implemented,
    f"missing={sorted(advertised - implemented)} extra={sorted(implemented - advertised)}",
)

check(
    "send_message_tool_gated",
    next(
        t for t in ToolCatalogue().get_tools()
        if t.name == "application.send_message"
    ).confirmation_required
    is True,
)

check(
    "close_tabs_tool_exists",
    "browser.close_tabs" in advertised,
)

# ============================================================
# SUMMARY
# ============================================================

print()

if failures:
    print(f"FAILED: {failures}")
    raise SystemExit(1)

print("ALL ROUND-3 TESTS PASSED")
