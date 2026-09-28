import json
import re

from ai.provider import GroqProvider


provider = GroqProvider()


TEST_CASES = [
    {
        "id": "computer_application_1",
        "request": "Open Notepad and type hello into it.",
        "expected": ["application", "computer"],
    },
    {
        "id": "computer_application_2",
        "request": "Launch Calculator and press the number 5.",
        "expected": ["application", "computer"],
    },
]


ROUTING_RULES = """
You are JARVIS's semantic capability router.

Identify ALL high-level capability categories genuinely required
to fulfill the user's request.

Available capabilities:

computer:
Generic desktop interaction such as mouse movement, mouse clicks,
keyboard typing, keyboard presses, and interaction with arbitrary
desktop windows.

application:
Launching, opening, closing, or inspecting desktop applications.

browser:
Controlling an already-open browser and interacting with websites.
This includes navigation, clicking, typing, scrolling, reading webpages,
managing tabs, and searching YouTube or Google through the browser.

filesystem:
Finding, reading, creating, copying, moving, deleting, opening,
or inspecting files and folders.

system:
Operating-system and laptop controls such as volume, brightness,
battery, CPU, RAM, storage, Wi-Fi, Bluetooth, sleep, restart,
shutdown, and network state.

screen:
Taking screenshots or visually analyzing what is currently visible
on the computer screen.

web:
Internet information retrieval without controlling a browser UI.
Use this for web research/search/fetch when the user wants information,
not browser interaction.

memory:
Remembering, recalling, or updating information about the user.

skill:
Creating, validating, discovering, or executing reusable workflows.

IMPORTANT ROUTING RULES:

1. Choose capabilities based on the user's intended task.

2. If the user asks JARVIS to launch a desktop application,
   include "application".

3. If the user asks JARVIS to interact with a browser after it is
   launched, include "browser".

4. If a request requires both launching an application and then
   interacting with it, include both capabilities.

5. APPLICATION vs COMPUTER:
   - Use "application" when the user asks JARVIS to launch, open,
     close, or inspect a desktop application.
   - Also use "computer" when the user asks JARVIS to directly
     interact with that desktop application's interface by typing,
     pressing keys, clicking, scrolling, or using other generic
     mouse/keyboard actions.
   - This applies to ordinary desktop applications that do not have
     their own specialized interaction capability.
   - For example:
       "Open Notepad and type hello" → application + computer
       "Launch Calculator and press 5" → application + computer
       "Open Chrome and click a webpage button" → application + browser

6. Do not add "computer" merely because a specialized capability
   internally uses mouse/keyboard operations.

   For example, browser interaction uses mouse/keyboard internally,
   but should remain "browser".

   However, ordinary desktop applications without a specialized
   interaction capability require "computer" when the user asks
   JARVIS to interact with their interface.

7. Use "computer" for generic desktop interaction that is not already
   covered by a specialized capability.

8. Use "browser" for browser UI interaction.

9. Use "web" for internet information retrieval without browser UI.

10. Do not add "web" merely because a browser is accessing online content.

11. Use "screen" only when a screenshot or visual analysis of the
    actual current screen is required.

12. Reading webpage content through the browser does NOT automatically
    require "screen".

13. Use "filesystem" for files and folders even if another application
    will eventually open the file.

14. Use "application" when the user explicitly asks to launch or close
    an application.

15. Use "system" for OS-level controls such as volume and Bluetooth.

16. Use "memory" for remembering, recalling, or updating user information.

17. Use "skill" for reusable workflows or saved routines.

18. A request may require multiple capabilities.

19. Never add a capability merely because another capability might
    internally use it.

20. Never invent a capability.

21. Return ONLY valid JSON.
"""

def extract_json(text):
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)

        if not match:
            raise

        return json.loads(match.group(0))


def classify_batch(batch):
    batch_prompt = f"""
{ROUTING_RULES}

Analyze every test case below.

Return exactly this JSON structure:

{{
    "results": [
        {{
            "id": "test_id",
            "capabilities": ["category1", "category2"]
        }}
    ]
}}

Rules:
- Return one result for every test case.
- Do not omit any test case.
- Do not include explanations.
- Return ONLY valid JSON.
- Capability order does not matter.

TEST CASES:

{json.dumps(
    [
        {
            "id": case["id"],
            "request": case["request"],
        }
        for case in batch
    ],
    indent=2,
)}
"""

    response = provider.generate(batch_prompt)

    if not response.strip():
        raise RuntimeError(
            "Groq returned an empty response for this batch."
        )

    return extract_json(response)


BATCH_SIZE = 8

all_results = []

for start in range(0, len(TEST_CASES), BATCH_SIZE):
    batch = TEST_CASES[start:start + BATCH_SIZE]

    print(
        f"Running batch "
        f"{start // BATCH_SIZE + 1}/"
        f"{(len(TEST_CASES) + BATCH_SIZE - 1) // BATCH_SIZE} "
        f"({len(batch)} tests)..."
    )

    data = classify_batch(batch)

    if not isinstance(data, dict):
        raise RuntimeError("Groq returned an invalid batch structure.")

    batch_results = data.get("results")

    if not isinstance(batch_results, list):
        raise RuntimeError(
            "Groq response does not contain a valid 'results' list."
        )

    all_results.extend(batch_results)


results = {
    item["id"]: item["capabilities"]
    for item in all_results
}


passed = 0
failed = 0


print()
print("=" * 70)
print("JARVIS SEMANTIC CAPABILITY ROUTER TEST")
print("=" * 70)
print()


for case in TEST_CASES:
    actual = results.get(case["id"])
    expected = case["expected"]

    actual_set = set(actual or [])
    expected_set = set(expected)

    if actual_set == expected_set:
        status = "PASS"
        passed += 1
    else:
        status = "FAIL"
        failed += 1

    print(f"[{status}] {case['id']}")
    print(f"  Request : {case['request']}")
    print(f"  Expected: {expected}")
    print(f"  Actual  : {actual}")
    print()


print("=" * 70)
print(f"PASSED: {passed}")
print(f"FAILED: {failed}")
print(f"TOTAL : {len(TEST_CASES)}")
print("=" * 70)