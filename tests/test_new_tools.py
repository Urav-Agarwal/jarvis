"""
Offline tests for the newer JARVIS tool subsystems:
skill store, application.open fallbacks, memory store, and the
browser controller's URL normalization. No LLM calls.

Run with:
    python -m tests.test_new_tools
"""

import os
import tempfile

from tools.skill_store import SkillStore
from tools.reminders import ReminderStore
from tools.browser_control import BrowserController
from assistant.memory import MemoryStore
from ai.tool_catalogue import ToolCatalogue


failures = 0


def check(name, condition, detail=""):
    global failures

    if condition:
        print(f"[PASS] {name}")
    else:
        failures += 1
        print(f"[FAIL] {name} {detail}")


# ============================================================
# SKILL STORE
# ============================================================

catalogue = ToolCatalogue()

skill_path = os.path.join(
    tempfile.gettempdir(),
    "jarvis_skills_test.json",
)

store = SkillStore(path=skill_path, tool_validator=catalogue.get_tool)

created = store.create(
    "test skill",
    "probe skill",
    [
        {"tool": "application.open", "parameters": {"application": "Notepad"}},
    ],
)

check("skill_create", created.get("success") is True, created)

duplicate = store.create(
    "test skill",
    "probe skill",
    [
        {"tool": "application.open", "parameters": {"application": "Paint"}},
    ],
)

check("skill_create_updates_existing", duplicate.get("success") is True)

check(
    "skill_rejects_unknown_tool",
    store.create("bad", "", [{"tool": "not.a.tool", "parameters": {}}]).get("success") is False,
)

check(
    "skill_rejects_empty_steps",
    store.create("bad2", "", []).get("success") is False,
)

found = store.discover("test")

check(
    "skill_discover",
    found.get("success") is True and len(found.get("skills", [])) == 1,
)

check(
    "skill_validate_ok",
    store.validate({"steps": [{"tool": "system.cpu", "parameters": {}}]}).get("success") is True,
)

check(
    "skill_validate_rejects_unknown",
    store.validate({"steps": [{"tool": "nope", "parameters": {}}]}).get("success") is False,
)

check(
    "skill_get",
    store.get("TEST SKILL") is not None,
)

deleted = store.delete("test skill")

check("skill_delete", deleted.get("success") is True)

# ============================================================
# BROWSER URL NORMALIZATION (pure, no windows touched)
# ============================================================

check(
    "url_scheme_preserved",
    BrowserController._normalize_url("https://example.com/x") == "https://example.com/x",
)

check(
    "url_domain_gets_https",
    BrowserController._normalize_url("example.com") == "https://example.com",
)

check(
    "url_query_becomes_search",
    BrowserController._normalize_url("python documentation").startswith(
        "https://duckduckgo.com/?q="
    ),
)

# ============================================================
# MEMORY STORE
# ============================================================

memory_path = os.path.join(
    tempfile.gettempdir(),
    "jarvis_memory_test.json",
)

memory = MemoryStore(path=memory_path)

memory.remember("I prefer dark mode")

remembered = memory.remember("remember that I study physics")

check(
    "memory_strips_prefix",
    remembered["information"] == "I study physics",
    remembered,
)

recalled = memory.recall("physics")

check(
    "memory_recall_keyword",
    "I study physics" in recalled.get("results", []),
)

check(
    "memory_recent_fallback",
    "results" in memory.recall("zzzunmatchable"),
)

check(
    "memory_forget",
    memory.forget("dark mode").get("success") is True,
)

# ============================================================
# SKILL TRIGGERS + VERSIONING (context 14/46)
# ============================================================

check(
    "skill_trigger_match",
    store.create(
        "study setup",
        "probe",
        [{"tool": "system.cpu", "parameters": {}}],
        triggers=["get my study setup ready"],
    ).get("success") is True,
)

matched = store.find_by_trigger("hey jarvis get my study setup ready please")

check(
    "skill_trigger_found",
    matched is not None and matched["name"] == "study setup",
)

check(
    "skill_trigger_no_false_positive",
    store.find_by_trigger("open the door") is None,
)

versioned = store.create(
    "study setup",
    "probe v2",
    [{"tool": "system.volume", "parameters": {"action": "get"}}],
    triggers=["study setup"],
)

check(
    "skill_versioning",
    versioned.get("skill", {}).get("version") == 2,
    versioned,
)

store.delete("study setup")

# ============================================================
# REMINDERS (context 52)
# ============================================================

reminder_path = os.path.join(tempfile.gettempdir(), "jarvis_rem_test.json")

reminders = ReminderStore(path=reminder_path)

parsed = reminders.parse_and_add(
    "remind me to submit the assignment at 8 PM"
)

check(
    "reminder_parse_time",
    parsed.get("success") is True
    and "08:00 PM" in parsed.get("message", ""),
    parsed,
)

recurring = reminders.parse_and_add(
    "remind me to check my study plan every evening at 9"
)

check(
    "reminder_recurring_evening_pm",
    recurring.get("reminder", {}).get("recurring") == "daily"
    and "21:00" in recurring.get("reminder", {}).get("due", ""),
    recurring,
)

check(
    "reminder_rejects_no_time",
    reminders.parse_and_add("remind me to do something sometime")
    .get("success")
    is False,
)

check(
    "reminder_cancel",
    reminders.cancel("submit the assignment").get("success") is True,
)

# ============================================================
# CATALOGUE / RUNTIME SYNC
# ============================================================

from ai.tool_runtime import ToolRuntime

runtime = ToolRuntime()

advertised = {tool.name for tool in ToolCatalogue().get_tools()}
implemented = set(runtime._handlers)

check(
    "catalogue_runtime_sync",
    advertised == implemented,
    f"missing={sorted(advertised - implemented)} extra={sorted(implemented - advertised)}",
)

# ============================================================
# SUMMARY
# ============================================================

print()

if failures:
    print(f"FAILED: {failures}")
    raise SystemExit(1)

print("ALL NEW-TOOL TESTS PASSED")
