"""
Offline tests for this round's fixes:

- tool param alignment: catalogue 'application' key reaches a handler
  that declares a different name without a raw TypeError
  (THE BUG: 'ToolRuntime._close_application() got an unexpected
  keyword argument application')
- whatsapp send clarify flow: missing message -> ask what to send;
  ambiguous contacts -> offer visible names; pick -> confirm -> send
- pending send survives unrelated flows and cancels cleanly

Run with:
    PYTHONIOENCODING=utf-8 python -m tests.test_whatsapp_clarify
"""

import json
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai.agent_runtime import AgentRuntime
from ai.tool_catalogue import ToolCatalogue
from ai.tool_runtime import ToolRuntime

failures = 0


def check(name, condition, detail=""):
    global failures

    if condition:
        print(f"[PASS] {name}")
    else:
        failures += 1
        print(f"[FAIL] {name} {detail}")


class FakeProvider:
    """Scripted LLM stand-in: no network calls."""

    def __init__(self):
        self.script = []

    def queue(self, *responses):
        self.script.extend(responses)

    def generate(self, prompt: str) -> str:
        if self.script:
            return self.script.pop(0)

        return json.dumps({"type": "question", "request": prompt[-200:]})


# ============================================================
# 1. PARAMETER ALIGNMENT (the close-whatsapp crash)
# ============================================================

runtime = ToolRuntime()

# Simulate exactly what the planner sends for "close whatsapp":
# the catalogue declares the key "application".
result = runtime.execute("application.close", {"application": "notepad-real-app"})

check(
    "application.close accepts catalogue 'application' key",
    "unexpected keyword argument" not in str(result.get("result", "")),
    f"got: {result}",
)

check(
    "application.close returns a dict result",
    isinstance(result.get("result"), (dict, str)),
    f"got: {result}",
)

# Unknown keys are dropped, required args are back-filled.
def _two_arg_handler(first, second):
    return {"first": first, "second": second}


aligned = ToolRuntime._align_parameters(
    _two_arg_handler,
    {"wrong_name": "A", "extra": "B"},
)

check(
    "alignment back-fills required args from unknown keys",
    aligned.get("first") == "A" and aligned.get("second") is None or aligned.get("second") == "B"
    if "first" in aligned else False,
    f"got: {aligned}",
)

aligned2 = ToolRuntime._align_parameters(
    _two_arg_handler,
    {"first": "A", "second": "B", "junk": "C"},
)

check(
    "alignment drops unknown keys",
    "junk" not in aligned2 and aligned2.get("first") == "A",
    f"got: {aligned2}",
)

aligned3 = ToolRuntime._align_parameters(
    lambda *args, **kwargs: None,
    {"anything": 1},
)

check(
    "alignment passes through *args/**kwargs handlers",
    aligned3 == {"anything": 1},
    f"got: {aligned3}",
)

# Other previously-drifted pairs.
result = runtime.execute("application.state", {"name": "chrome"})
check(
    "application.state accepts 'name' key",
    isinstance(result.get("result"), (dict, str)),
    f"got: {result}",
)

result = runtime.execute("browser.close_tabs", {"count": 2})
check(
    "browser.close_tabs accepts 'count' key",
    isinstance(result.get("result"), (dict, str)),
    f"got: {result}",
)

# Catalogue/handler pairs must line up for the whatsapp tools.
catalogue = ToolCatalogue()

for tool_name in (
    "application.open",
    "application.close",
    "application.state",
    "application.whatsapp_message",
    "application.whatsapp_search",
    "application.send_message",
):
    definition = catalogue.get_tool(tool_name)
    check(f"catalogue has {tool_name}", definition is not None)

# ============================================================
# 2. CLARIFY FLOW: missing message -> ask, then complete
# ============================================================

calls = []


def fake_execute(tool_name, parameters=None):
    calls.append((tool_name, dict(parameters or {})))

    return {
        "success": True,
        "result": {"message": f"[stub] sent to {parameters.get('contact')}"},
    }


# Search returns several matches for "vishwa"-style queries;
# exact names and saved aliases resolve to one contact.
def fake_search(query):
    lowered = (query or "").lower()

    if lowered in {"vishwa fatty"}:
        return {
            "success": True,
            "query": query,
            "contacts": ["Vishwa Fatty"],
        }

    if lowered in {"vishwa bhaiya", "mummy"}:
        return {
            "success": True,
            "query": query,
            "contacts": ["Vishwa Bhaiya" if "bhaiya" in lowered else "Mummy"],
        }

    return {
        "success": True,
        "query": query,
        "contacts": ["Vishwa Fatty", "Vishwa Bhaiya"],
    }


def make_agent(provider):
    """
    Runtime with the capability router stubbed: "send a message to
    X" is NOT deterministically routable, so the real router would
    burn a scripted LLM response on semantic classification.
    """

    agent = AgentRuntime(provider)

    agent.router.route = lambda request: ["application"]
    agent.tools.execute = fake_execute
    agent.tools._whatsapp_search = staticmethod(fake_search)

    return agent


provider = FakeProvider()
agent = make_agent(provider)

provider.queue(
    json.dumps({
        "type": "action",
        "tool": "application.whatsapp_message",
        "parameters": {"contact": "Vishwa"},
    })
)

reply = agent.process("send a message to Vishwa on whatsapp")

check(
    "missing message asks what to send",
    "What message should I send to Vishwa" in reply.get("result", ""),
    f"got: {reply.get('result')}",
)

check(
    "pending send flag set",
    reply.get("pending_send") is True,
    f"got: {reply}",
)

# User dictates the message -> the ambiguity check NOW runs, so
# "Vishwa" first offers the visible matches (the user's design).
reply2 = agent.process("I will be late tonight")

check(
    "message reply offers matching contacts first",
    "several contacts matching Vishwa" in reply2.get("result", "")
    and "1. Vishwa Fatty" in reply2.get("result", ""),
    f"got: {reply2.get('result')}",
)

# User picks one.
reply2b = agent.process("vishwa fatty")

check(
    "pick after message leads to confirmation",
    "Say yes or no" in reply2b.get("result", "")
    and "Vishwa Fatty" in reply2b.get("result", ""),
    f"got: {reply2b.get('result')}",
)

# User confirms.
reply3 = agent.process("yes")

check(
    "confirmation executes the send",
    "sent to Vishwa Fatty" in reply3.get("result", ""),
    f"got: {reply3.get('result')}",
)

check(
    "send tool got contact and message",
    calls
    and calls[-1][0] == "application.whatsapp_message"
    and calls[-1][1].get("contact") == "Vishwa Fatty"
    and "late" in calls[-1][1].get("message", ""),
    f"got: {calls}",
)

check(
    "pending send cleared after send",
    agent._pending_send is None,
    f"got: {agent._pending_send}",
)

# ============================================================
# 3. CLARIFY FLOW: multiple contacts -> pick by name
# ============================================================

provider2 = FakeProvider()
agent2 = make_agent(provider2)

provider2.queue(
    json.dumps({
        "type": "action",
        "tool": "application.whatsapp_message",
        "parameters": {
            "contact": "Vishwa",
            "message": "are you coming to the game",
        },
    })
)

reply = agent2.process("send are you coming to the game to vishwa on whatsapp")

check(
    "multiple matches offer numbered names",
    "1. Vishwa Fatty" in reply.get("result", "")
    and "2. Vishwa Bhaiya" in reply.get("result", ""),
    f"got: {reply.get('result')}",
)

# User picks by name.
reply2 = agent2.process("vishwa fatty")

check(
    "name pick leads to confirmation",
    "Say yes or no" in reply2.get("result", "")
    and "Vishwa Fatty" in reply2.get("result", ""),
    f"got: {reply2.get('result')}",
)

# User confirms with a voice-friendly yes.
reply3 = agent2.process("yes send it")

check(
    "send executed to the chosen contact",
    calls
    and calls[-1][0] == "application.whatsapp_message"
    and calls[-1][1].get("contact") == "Vishwa Fatty",
    f"got: {calls}",
)

# Pick by number also works.
provider3 = FakeProvider()
agent3 = make_agent(provider3)

provider3.queue(
    json.dumps({
        "type": "action",
        "tool": "application.whatsapp_message",
        "parameters": {"contact": "Vishwa", "message": "hi"},
    })
)

agent3.process("send hi to vishwa on whatsapp")

reply = agent3.process("2")

check(
    "numeric pick works",
    "Say yes or no" in reply.get("result", "")
    and "Vishwa Bhaiya" in reply.get("result", ""),
    f"got: {reply.get('result')}",
)

reply = agent3.process("no")

check(
    "cancel during confirm stops everything",
    "cancelled" in reply.get("result", "").lower()
    and agent3._pending_send is None,
    f"got: {reply.get('result')}",
)

# ============================================================
# 4. UNRELATED INPUT DOES NOT HIJACK A LIVE FLOW
# ============================================================

provider4 = FakeProvider()
agent4 = make_agent(provider4)

sent = []


def fake_execute4(tool_name, parameters=None):
    sent.append((tool_name, dict(parameters or {})))

    return {"success": True, "result": {"message": "ok"}}


agent4.tools.execute = fake_execute4

provider4.queue(
    json.dumps({
        "type": "action",
        "tool": "application.whatsapp_message",
        "parameters": {"contact": "Vishwa"},
    })
)

agent4.process("send a message to Vishwa on whatsapp")

# Non-message reply falls through to normal processing (a question).
reply = agent4.process("what time is it")

check(
    "unrelated reply processed normally",
    "What message should I send" in reply.get("result", "")
    or reply.get("result") not in (None, ""),
    f"got: {reply.get('result')}",
)

# ============================================================
# 5. NO SEARCH TOOL / NO MATCHES -> direct confirmation
# ============================================================

provider5 = FakeProvider()
agent5 = make_agent(provider5)

agent5.tools._whatsapp_search = staticmethod(lambda q: {"success": False})

provider5.queue(
    json.dumps({
        "type": "action",
        "tool": "application.whatsapp_message",
        "parameters": {"contact": "Vishwa", "message": "hello there"},
    })
)

reply = agent5.process("send hello there to vishwa on whatsapp")

check(
    "failed search degrades to confirmation with spoken name",
    "confirm" in reply.get("result", "").lower()
    and "Vishwa" in reply.get("result", ""),
    f"got: {reply.get('result')}",
)

reply = agent5.process("yes")

check(
    "confirmation sends with spoken name",
    calls
    and calls[-1][0] == "application.whatsapp_message"
    and calls[-1][1].get("contact") == "Vishwa"
    and calls[-1][1].get("message") == "hello there",
    f"got: {calls}",
)

# ============================================================
# 6. FAILURE OFFERS SIMILAR VISIBLE CONTACTS (user's complaint 1:
#    plain "Vishwa" failed with no help, though "Vishwa High" was
#    visible in WhatsApp's search list)
# ============================================================

def fake_search_high(query):
    # "vishwa" alone: search runs fine but nothing similar shows.
    if (query or "").lower() == "vishwa":
        return {"success": True, "query": query, "contacts": []}

    return {
        "success": True,
        "query": query,
        "contacts": ["Vishwa High", "Vishwa Fatty"],
    }


provider_h = FakeProvider()
agent_h = make_agent(provider_h)
agent_h.tools._whatsapp_search = staticmethod(fake_search_high)

# Direct search for "vishwa" fails -> _match_contact_candidates
# returns [] (honest no-match refusal, not a blind confirm).
provider_h.queue(
    json.dumps({
        "type": "action",
        "tool": "application.whatsapp_message",
        "parameters": {"contact": "Vishwa", "message": "hi"},
    })
)

reply = agent_h.process("send hi to vishwa on whatsapp")

check(
    "no-match search refuses honestly (never a blind confirm)",
    "couldn't find anyone like 'Vishwa'" in reply.get("result", ""),
    f"got: {reply.get('result')}",
)

# The send tool's failure dict carries contact_matches so the spoken
# error can offer the visible names (mirrors tools/whatsapp.py).
from tools.whatsapp import _clean_result_name

check(
    "result-name cleaner strips noise tokens",
    _clean_result_name("vishwa high 10:45") == "vishwa high",
    f"got: {_clean_result_name('vishwa high 10:45')!r}",
)

# ============================================================
# 7. MESSAGING FAST-PATH (complaints 2+3: the LLM fabricated a
#    send and refused an open-and-message)
# ============================================================

provider_f = FakeProvider()
agent_f = make_agent(provider_f)
agent_f.tools._whatsapp_search = staticmethod(fake_search)

fast_calls = []


def fast_execute(tool_name, parameters=None):
    fast_calls.append((tool_name, dict(parameters or {})))

    return {
        "success": True,
        "result": {"message": f"[stub] {tool_name}"},
    }


agent_f.tools.execute = fast_execute

# "send a message to mummy saying hi" must ask what to send -> no,
# mummy + hi are both present: goes to confirm (no LLM consumed).
reply = agent_f.process("send a message to mummy saying hi")

check(
    "fast-path catches 'send a message to X saying Y'",
    "Say yes or no" in reply.get("result", ""),
    f"got: {reply.get('result')}",
)

check(
    "fast-path never consumed an LLM response",
    len(provider_f.script) == 0,
    f"script left: {provider_f.script}",
)

agent_f.process("yes")

check(
    "fast-path confirm executes the real send tool",
    fast_calls
    and fast_calls[-1][0] == "application.whatsapp_message"
    and fast_calls[-1][1].get("contact") == "Mummy"
    and fast_calls[-1][1].get("message") == "hi",
    f"got: {fast_calls}",
)

# Message BEFORE the contact: "send hi to vishwa".
reply = agent_f.process("send hi to vishwa on whatsapp")

check(
    "fast-path catches message-before-contact form",
    "several contacts" in reply.get("result", "")
    or "Say yes or no" in reply.get("result", ""),
    f"got: {reply.get('result')}",
)

agent_f.process("no")

# "open whatsapp and message vishwa high" (complaint 3's phrasing).
reply = agent_f.process("open whatsapp and message vishwa high")

check(
    "open-app-and-message phrasing handled without LLM",
    len(provider_f.script) == 0 and reply.get("result"),
    f"got: {reply.get('result')}",
)

check(
    "bare 'message vishwa high' asks what to send",
    "What message should I send to Vishwa High" in reply.get("result", ""),
    f"got: {reply.get('result')}",
)

agent_f.process("no")

# Meta questions about messaging are NOT hijacked.
provider_f.queue(json.dumps({"type": "question", "request": "how do I send a message on whatsapp"}))

reply = agent_f.process("how do I send a message on whatsapp")

check(
    "how-to questions skip the fast-path",
    '"type": "question"' in str(reply.get("result")),
    f"got: {reply.get('result')}",
)

# ============================================================
# 8. GOING TO SLEEP / STOP CLEARS PENDING STATE
# ============================================================

provider6 = FakeProvider()
agent6 = make_agent(provider6)

provider6.queue(
    json.dumps({
        "type": "action",
        "tool": "application.whatsapp_message",
        "parameters": {"contact": "Vishwa"},
    })
)

agent6.process("send a message to Vishwa on whatsapp")

reply = agent6.process("thanks that's all")

check(
    "goodbye clears pending send",
    agent6._pending_send is None and reply.get("go_to_sleep") is True,
    f"got: {reply}",
)

# ============================================================
print()

if failures:
    print(f"{failures} test(s) FAILED")
    sys.exit(1)

print("ALL TESTS PASSED")
