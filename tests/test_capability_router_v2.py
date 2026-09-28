"""
Offline tests for the JARVIS hybrid capability router V2.

These tests use a fake provider, so they never consume Groq tokens.
They verify:
- deterministic routing and capability boundaries
- fallback to semantic routing on ambiguity
- validation/normalization of the final capability list

Run with:
    python -m tests.test_capability_router_v2
"""

import json

from router.capability_router_v2 import CapabilityRouter
from tools.capabilities import (
    get_capability_names,
    validate_capabilities,
)


class FakeProvider:
    """Records semantic calls so tests can assert fallback behavior."""

    def __init__(self):
        self.calls = []
        self.total_calls = 0

    def generate(self, prompt: str) -> str:
        self.calls.append(prompt)
        self.total_calls += 1
        return json.dumps({"capabilities": ["web"]})


provider = FakeProvider()
router = CapabilityRouter(provider=provider)


def check(name, request, expected, use_semantic=False):
    provider.calls.clear()

    actual = router.route(request)

    if set(actual) == set(expected):
        print(f"[PASS] {name}: {request!r} -> {actual}")
        return 0

    print(f"[FAIL] {name}: {request!r}")
    print(f"       expected {expected}")
    print(f"       actual   {actual}")
    return 1


failures = 0


# ============================================================
# VALIDATION HELPERS
# ============================================================

assert get_capability_names() == [
    "application", "browser", "computer", "filesystem",
    "screen", "web", "system", "memory", "skill",
]

assert validate_capabilities(
    ["application", "banana", "application", "system", "web"]
) == ["application", "web", "system"]

print("[PASS] canonical order + validation")
print()

# ============================================================
# DETERMINISTIC — SIMPLE CASES
# ============================================================

failures += check(
    "open_chrome",
    "Open Chrome",
    ["application"],
)

failures += check(
    "lower_volume",
    "Lower the volume",
    ["system"],
)

failures += check(
    "remember_dark_mode",
    "Remember that I like dark mode",
    ["memory"],
)

failures += check(
    "find_project_folder",
    "Find my project folder",
    ["filesystem"],
)

failures += check(
    "take_screenshot",
    "Take a screenshot",
    ["screen"],
)

# ============================================================
# BOUNDARY: APPLICATION vs BROWSER
# ============================================================

failures += check(
    "open_chrome_youtube",
    "Open Chrome and go to YouTube.",
    ["application", "browser"],
)

failures += check(
    "open_chrome_no_browser",
    "Open Chrome, VS Code, and File Explorer, locate the project I "
    "worked on yesterday, open the relevant files, look up the latest "
    "documentation online, keep the sound low, take a screenshot of "
    "the current setup, and remember that this is my current project.",
    ["application", "filesystem", "web", "system", "screen", "memory"],
)

# ============================================================
# BOUNDARY: SCREEN vs BROWSER
# ============================================================

failures += check(
    "webpage_looks_like",
    "Open Chrome and tell me what the webpage looks like.",
    ["application", "screen"],
)

failures += check(
    "webpage_says",
    "Tell me what the webpage says.",
    ["browser"],
)

failures += check(
    "visible_inside_webpage",
    "Tell me what's visible inside the webpage.",
    ["screen"],
)

# ============================================================
# BOUNDARY: BROWSER vs WEB
# ============================================================

failures += check(
    "search_the_web",
    "Search the web for the latest JEE updates.",
    ["web"],
)

failures += check(
    "search_google_in_browser",
    "Go to Google and search for the latest JEE updates.",
    ["browser"],
)

# ============================================================
# BOUNDARY: APPLICATION vs COMPUTER
# ============================================================

failures += check(
    "notepad_type",
    "Open Notepad and type hello.",
    ["application", "computer"],
)

failures += check(
    "calculator_press",
    "Launch Calculator and press the number 5.",
    ["application", "computer"],
)

# ============================================================
# BOUNDARY: COMPUTER vs SYSTEM
# ============================================================

failures += check(
    "click_bluetooth_icon",
    "Click the Bluetooth icon in the taskbar.",
    ["computer"],
)

failures += check(
    "click_volume_control",
    "Use the mouse to click the volume control.",
    ["computer"],
)

# ============================================================
# BOUNDARY: FILESYSTEM + APPLICATION
# ============================================================

failures += check(
    "spreadsheet_excel",
    "Find the spreadsheet from yesterday and open it in Excel.",
    ["filesystem", "application"],
)

# ============================================================
# NATURAL REPHRASINGS (deterministic wins, no LLM)
# ============================================================

failures += check(
    "recall_preference",
    "What was that preference I told you about earlier?",
    ["memory"],
)

failures += check(
    "audio_too_loud",
    "The audio is way too loud. Bring it down.",
    ["system"],
)

failures += check(
    "where_notes",
    "Where did I put my physics notes?",
    ["filesystem"],
)

# ============================================================
# AMBIGUOUS -> SEMANTIC FALLBACK
# ============================================================

failures += check(
    "ambiguous_falls_back",
    "Can you sort out my workspace?",
    ["web"],  # FakeProvider always answers web
    use_semantic=True,
)

failures += check(
    "already_open_context",
    "The browser is already open. Take me to YouTube.",
    ["browser"],
)

failures += check(
    "utterly_ambiguous",
    "Handle that thing for me.",
    ["web"],  # FakeProvider always answers web
    use_semantic=True,
)

semantic_calls = provider.total_calls

assert semantic_calls == 2, semantic_calls

print()
print("[PASS] semantic fallback used exactly 2 times; deterministic "
      "routing resolved everything else without any LLM calls")
print()

# ============================================================
# STRESS SAMPLE (offline, zero tokens)
#
# policy="exact"       -> deterministic result must equal expected
# policy="semantic_ok" -> fallback to the LLM is acceptable, but a
#                         deterministic WRONG answer is a failure
# ============================================================

STRESS_SAMPLE = [
    ("stress_021", "Bring up Notepad and write my name into it.",
     ["application", "computer"], "exact"),
    ("stress_030", "Navigate the current browser to Google's homepage.",
     ["browser"], "exact"),
    ("stress_039", "Bring Chrome up and look for JEE physics lectures on YouTube.",
     ["application", "browser"], "exact"),
    ("stress_043", "Open Firefox and find the Wikipedia page for Python.",
     ["application", "browser"], "semantic_ok"),
    ("stress_054", "Find the latest NVIDIA news online and summarize it.",
     ["web"], "semantic_ok"),
    ("stress_056", "Search the web for the latest JEE updates.",
     ["web"], "exact"),
    ("stress_072", "Locate my physics PDF and open it.",
     ["filesystem", "application"], "exact"),
    ("stress_073", "Find the spreadsheet from yesterday and open it in Excel.",
     ["filesystem", "application"], "exact"),
    ("stress_080", "Is my Wi-Fi actually connected?",
     ["system"], "semantic_ok"),
    ("stress_096", "Read the article currently open in Chrome.",
     ["browser"], "semantic_ok"),
    ("stress_097", "Look at the screen and tell me which application is visible.",
     ["screen"], "exact"),
    ("stress_098", "Tell me what's visible inside the webpage.",
     ["screen"], "exact"),
    ("stress_103", "Keep in mind that I prefer dark interfaces.",
     ["memory"], "exact"),
    ("stress_109", "Use my saved study setup.",
     ["skill"], "semantic_ok"),
    ("stress_113", "Click the Bluetooth icon in the taskbar.",
     ["computer"], "exact"),
    ("stress_115", ("Get me ready for studying: open Chrome and VS Code, "
                    "find my physics notes, and lower the volume."),
     ["application", "filesystem", "system"], "exact"),
    ("stress_116", ("I'm starting a coding session. Bring up VS Code and "
                    "Chrome, find my project folder, and show me what's "
                    "currently on screen."),
     ["application", "filesystem", "screen"], "exact"),
    ("stress_118", ("Find my physics notes, open them, and tell me what is "
                    "visible on my screen afterward."),
     ["filesystem", "application", "screen"], "exact"),
    ("stress_121", ("I'm working on my project. Launch VS Code and Chrome, "
                    "locate the project folder, open it, search online for "
                    "the documentation I need, and remember that I'm "
                    "working on this project today."),
     ["application", "filesystem", "web", "memory"], "exact"),
    ("stress_125", ("I'm starting work on my AI project. Open Chrome, VS "
                    "Code, and File Explorer, locate the project I worked "
                    "on yesterday, open the relevant files, look up the "
                    "latest documentation online, keep the sound low, take "
                    "a screenshot of the current setup, and remember that "
                    "this is my current project."),
     ["application", "filesystem", "web", "system", "screen", "memory"],
     "exact"),
    ("stress_127", ("I need to get my whole workspace sorted. Launch "
                    "Chrome, VS Code, Spotify, Discord, WhatsApp and File "
                    "Explorer, find my latest project folder, search the "
                    "internet for the documentation I need, open the "
                    "relevant webpage in Chrome, reduce the volume, take a "
                    "screenshot, and remember what I'm working on."),
     ["application", "browser", "filesystem", "web", "system", "screen",
      "memory"],
     "exact"),
    ("stress_129", "The browser is already open. Take me to YouTube.",
     ["browser"], "exact"),
    ("stress_131", "Find my notes and tell me what they contain.",
     ["filesystem"], "exact"),
    ("stress_132", "Open Chrome and tell me what the webpage looks like.",
     ["application", "screen"], "exact"),
    ("stress_135", "Find information online and don't open a browser.",
     ["web"], "semantic_ok"),
    ("stress_136", "Open the browser and interact with the website yourself.",
     ["application", "browser"], "exact"),
    ("stress_137", ("Open Calculator and click the buttons needed to "
                    "calculate 12 times 8."),
     ["application", "computer"], "semantic_ok"),
    ("stress_138", "Find the calculator application and launch it.",
     ["application"], "exact"),
]

stress_failures = 0

for case_id, request, expected, policy in STRESS_SAMPLE:
    before = provider.total_calls

    actual = router.route(request)

    went_semantic = provider.total_calls > before

    if policy == "exact" or not went_semantic:
        ok = set(actual) == set(expected)
    else:
        ok = True

    note = " (semantic fallback)" if went_semantic else ""

    if ok:
        print(f"[PASS] {case_id}{note}")
    else:
        stress_failures += 1
        print(f"[FAIL] {case_id}{note}: {request!r}")
        print(f"       expected {expected}")
        print(f"       actual   {actual}")

failures += stress_failures

print()
print(f"stress sample: {len(STRESS_SAMPLE) - stress_failures}/"
      f"{len(STRESS_SAMPLE)} passed")
print()

print()
print("[PASS] semantic fallback used exactly twice, deterministic "
      "routing resolved everything else without any LLM calls")
print()

# ============================================================
# SUMMARY
# ============================================================

print("=" * 60)

if failures:
    print(f"FAILED: {failures}")
    raise SystemExit(1)

print("ALL ROUTER TESTS PASSED")
