import json
import re
import time

from ai.tool_catalogue import ToolCatalogue
from ai.plan_parser import PlanParser


def _extract_json(text: str):
    """
    Pull the first JSON object out of an LLM reply. Models wrap
    decisions in code fences or lead with prose; a strict
    json.loads(reply) loses those decisions and the whole brain
    degrades to "unknown".
    """

    if not isinstance(text, str):
        return None

    candidate = text.strip()

    # Strip markdown code fences.
    candidate = re.sub(
        r"^```(?:json)?\s*|\s*```$",
        "",
        candidate,
        flags=re.IGNORECASE,
    ).strip()

    try:
        parsed = json.loads(candidate)

        return parsed if isinstance(parsed, dict) else None

    except (json.JSONDecodeError, ValueError):
        pass

    # First { ... last } span.
    start = candidate.find("{")

    if start == -1:
        return None

    end = candidate.rfind("}")

    if end <= start:
        return None

    try:
        parsed = json.loads(candidate[start : end + 1])

        return parsed if isinstance(parsed, dict) else None

    except (json.JSONDecodeError, ValueError):
        return None


def _looks_like_json(text: str) -> bool:
    """Guard so a JSON echo is never SPOKEN aloud."""

    if not isinstance(text, str):
        return True

    stripped = text.strip()

    if not stripped:
        return False

    return stripped[0] in "{[" or '"type"' in stripped[:80]


class AgentBrain:
    """
    v3 REASONER: turns (request + live machine state + memory +
    working notes from prior steps) into exactly ONE decision:

        speak / action / plan / clarify / unknown

    The decision CONTRACT is tiny; the loop (ai/brain.py) owns what
    happens next. The prompt carries the real machine state and the
    user's remembered facts so the model reasons about the actual
    computer instead of guessing — no keyword router decides for it.

    compose() is the second half of the brain: after tools have run,
    it turns real tool results into a natural spoken answer.
    """

    def __init__(self, provider):
        self.provider = provider
        self.catalogue = ToolCatalogue()
        self.plan_parser = PlanParser()

        # Personality tone: formal / balanced / witty (config).
        from app.config import get as _get

        self.tone = (_get("agent", "tone") or "balanced").lower()

    # ----------------------------------------------------------
    # CONTEXT BLOCKS (real data, fail-soft)
    # ----------------------------------------------------------

    def _tone_block(self) -> str:
        if self.tone == "formal":
            return (
                "TONE: Formal. Impeccably courteous, measured, and "
                "precise. 'Very good, sir.' Minimal jokes — warmth "
                "through polish."
            )

        if self.tone == "witty":
            return (
                "TONE: Witty. Dry British humor front and center — one "
                "genuinely funny line per reply when it lands naturally. "
                "Still competent and clear first; the quip is garnish, "
                "never the meal."
            )

        return (
            "TONE: Balanced. Warm, dry, capable. A light touch of "
            "wit when it fits; clarity always wins."
        )

    def _system_state_block(self) -> str:
        """
        Live snapshot of the machine for the reasoning prompt. Every
        component fails soft — state must never break the brain.
        """

        lines = []

        try:
            from datetime import datetime

            now = datetime.now()

            lines.append(
                "time: " + now.strftime("%A %d %b, %I:%M %p")
            )

        except Exception:
            pass

        try:
            import psutil

            battery = psutil.sensors_battery()

            if battery is not None:
                state = (
                    "charging"
                    if battery.power_plugged
                    else "on battery"
                )

                lines.append(
                    f"battery: {int(battery.percent)}% ({state})"
                )

            cpu = psutil.cpu_percent(interval=None)

            lines.append(f"cpu: {cpu:.0f}%")

            mem = psutil.virtual_memory()

            lines.append(
                f"ram: {mem.percent:.0f}% used"
            )

        except Exception:
            pass

        try:
            from tools.computer_observer import ComputerObserver

            active = ComputerObserver().get_active_window()

            if active.get("success"):
                lines.append(
                    "active window: "
                    + str(active.get("title") or "unknown")
                    + " ("
                    + str(active.get("process") or "?").removesuffix(
                        ".exe"
                    )
                    + ")"
                )

        except Exception:
            pass

        try:
            from tools.computer_observer import ComputerObserver

            apps = ComputerObserver().get_running_applications()

            if apps.get("success"):
                names = [
                    (a.get("name") or "").removesuffix(".exe")
                    for a in (apps.get("applications") or [])[:8]
                ]

                if names:
                    lines.append(
                        "running apps: " + ", ".join(names)
                    )

        except Exception:
            pass

        if not lines:
            return ""

        return (
            "CURRENT SYSTEM STATE (real, from this machine):\n"
            + "\n".join(lines)
            + "\n"
        )

    def _memory_block(self) -> str:
        """
        The user's remembered facts, so personalization ('open my
        code editor' -> VS Code, because that's what they told us)
        comes from data, not hardcoded aliases.
        """

        try:
            from assistant.memory import MemoryStore

            facts = MemoryStore().all_facts()

        except Exception:
            return ""

        if not facts:
            return ""

        fact_lines = []

        for fact in facts[:12]:
            if isinstance(fact, dict):
                text = str(
                    fact.get("text") or fact.get("information") or ""
                )

            else:
                text = str(fact)

            if text.strip():
                fact_lines.append("- " + text.strip()[:100])

        if not fact_lines:
            return ""

        return (
            "WHAT THE USER TOLD YOU TO REMEMBER (use for "
            "personalization; 'my code editor' means whatever they "
            "said it means):\n"
            + "\n".join(fact_lines)
            + "\n"
        )

    def _clarify_block(self) -> str:
        return '''
CLARIFYING (critical for natural conversation):

If the request is AMBIGUOUS in a way that changes what you would do,
return type "clarify" with ONE short spoken question that resolves
it. Ask like a person, not a form. Examples:
- "open my files" with several candidates -> clarify: "Which one,
  sir — the project folder or Documents?"
- "play some music" when no player is running -> clarify: "Spotify
  or YouTube, sir?"
Do NOT clarify when the request is clear enough to act: bias toward
action. Never ask two questions. Never clarify a request that one
of the tools obviously satisfies.
'''

    # ----------------------------------------------------------
    # TOOL MENU
    # ----------------------------------------------------------

    def _tool_menu(self, capabilities) -> str:
        tools = self.catalogue.get_tools_for_capabilities(capabilities)

        if tools is None:
            tools = self.catalogue.get_tools()

        tool_lines = []

        for tool in tools:
            params = ",".join(tool.parameters.keys()) or "-"

            risk = "CONFIRM" if tool.confirmation_required else "low"

            description = " ".join(tool.description.split())

            tool_lines.append(
                f"{tool.name}({params}) [{risk}]: {description[:90]}"
            )

        return "\n".join(tool_lines)

    # ----------------------------------------------------------
    # THE DECISION PROMPT
    # ----------------------------------------------------------

    def _working_notes_block(self, history) -> str:
        """
        Render prior loop steps so the model OBSERVES what it already
        did and reasons over the real results: continue, correct, or
        speak the final answer.
        """

        if not history:
            return ""

        lines = ["WORKING NOTES — steps already taken this turn:"]

        for index, entry in enumerate(history, start=1):
            tool = entry.get("tool")

            ok = "ok" if entry.get("success") else "FAILED"

            parameters = entry.get("parameters") or {}

            param_text = json.dumps(parameters, default=str)[:120]

            result = entry.get("result")

            if isinstance(result, (dict, list)):
                result_text = json.dumps(result, default=str)[:300]

            else:
                result_text = str(result)[:300]

            lines.append(
                f"{index}. {tool}({param_text}) -> {ok}: {result_text}"
            )

        lines.append(
            "Reason over these REAL results. If the task is complete, "
            "return type \"speak\" with the final answer. If a step "
            "FAILED, you may take one corrective action with a "
            "different tool or parameters. Do not repeat a step that "
            "already succeeded."
        )

        return "\n".join(lines) + "\n"

    def think(
        self,
        user_input: str,
        capabilities=None,
        context: str = "",
        force_action: bool = False,
        history=None,
    ):
        """
        One reasoning step. Returns a decision dict:

            {"type": "speak", "speech": str}
            {"type": "action", "tool": str, "parameters": dict}
            {"type": "plan", "description": str, "actions": [...]}
            {"type": "clarify", "question": str}
            {"type": "unknown", "request": str}
            {"type": "rate_limited", "request": str}
        """

        tools_json = self._tool_menu(capabilities)

        state_block = self._system_state_block()
        memory_block = self._memory_block()
        clarify_block = self._clarify_block()
        tone_block = self._tone_block()
        notes_block = self._working_notes_block(history or [])

        action_bias = ""

        if capabilities or force_action:
            action_bias = """
GROUNDING (critical):
Requests about the CURRENT state of this computer (battery, CPU, RAM,
storage, network, windows, applications, screen) are ACTIONS that use
the matching observation tool — NEVER answer them from general
knowledge, even though the state block above shows values. Requests to
remember, recall, teach, or search the web are ACTIONS too. Only
return "speak" for general knowledge that needs no tool ("What is the
capital of India?").
"""

        context_block = ""

        if context:
            context_block = f"""
CONVERSATION CONTEXT (most recent last):
{context}

FOLLOW-UP RULES:
- Every new request is INDEPENDENT by default. Execute it fully on
  its own merits.
- Treat it as a follow-up ONLY when it contains an explicit reference
  ("it", "that", "them", "also", "too", "same") or clearly continues
  the previous task. Never invent a connection.
- A brand-new command right after another command is NOT a follow-up.
"""

        prompt = f"""
You are the reasoning brain of JARVIS, a personal desktop AI
assistant. You are speaking out loud with the user: concise, warm,
never robotic, never filler.

{tone_block}

UNDERSTAND the user's request and return exactly ONE decision:

1. {{"type": "speak", "speech": "..."}}
   The user asked a question or wants conversation. "speech" is the
   full spoken answer, 1-3 sentences, clean spoken English, no
   markdown, no lists, no emojis. Examples: "What is the capital of
   India?", "tell me a joke", "how was your day".

2. {{"type": "action", "tool": "...", "parameters": {{...}}}}
   One concrete step you can take with ONE available tool. Requests
   about the user's actual machine are actions (see GROUNDING).

3. {{"type": "plan", "description": "...", "actions": [
      {{"tool": "...", "parameters": {{...}}, "description": "..."}} ]}}
   Multiple distinct steps in order. Never combine two tools into one
   action. If a later step needs an earlier step's result, still list
   it in order — the runtime feeds earlier results forward
   automatically (e.g. filesystem.search then filesystem.open).

4. {{"type": "clarify", "question": "..."}}
   Ambiguous in a way that changes what you would do. ONE short
   spoken question, bias toward action.

5. {{"type": "unknown", "request": "..."}}
   No available tool can do it and it is not a question.

RULES:
- Return ONLY the JSON object. No prose, no markdown fences.
- Never invent a tool; the tool name must exactly match the menu.
- Use only parameters that tool defines.
- Multi-step requests ("open Chrome and set volume to 40") are plans.
- "What application am I using?" -> computer.active_window.
- "Is Chrome running?" / "what apps are open" -> computer.running_apps.
- System state questions (battery, cpu, ram, storage, wifi, gpu,
  network) -> the matching system.* observation tool.
- "What time is it?" -> system.time. NEVER guess the time.
- News, recent events, product updates, anything after your training
  -> web.search. Never answer those from memory.
- "search YouTube/Google for X" -> browser.search with site and query.
- "open youtube.com" -> browser.navigate. Never navigate to search
  results directly; open the site's search page.
- Messaging: WhatsApp sends use application.whatsapp_message (contact,
  message). It is CONFIRM-gated; the user confirms out loud.
- Browser + PROFILE together ("open chrome with my school profile")
  -> browser.open with browser AND profile in one action; the profile
  value is the bare word (personal, school, work) without "profile".
- "close the tabs you opened" -> browser.close_tabs with count.
- App-specific volume ("volume of the YouTube video") -> system.app_volume.
- Screenshots -> screen.screenshot. Reading/understanding the screen
  -> screen.analyze with the question parameter.
- Files: search before opening when no path is given. Never invent a
  path.
- If an action fails (see working notes), try ONE correction or
  honestly report the failure; never claim success you did not see.

{action_bias}{context_block}
STATE AND MEMORY:

{state_block}
{memory_block}
Use the state to ground pronouns and choices: "the active window",
"that app" refer to what the state says is real. Use remembered
facts to resolve personal references ("my editor", "my usual").

{clarify_block}

Available tools:

{tools_json}
{notes_block}
User request:
{user_input}
"""

        try:
            _t0 = time.perf_counter()

            response = self.provider.generate(prompt)

            # v4.1 latency: duration of THIS reasoning call. The
            # runtime reads total_llm_ms after the loop to feed the
            # exchange trace (last = debugging, total = the trace).
            spent_ms = (time.perf_counter() - _t0) * 1000.0

            self.last_llm_ms = spent_ms

            self.total_llm_ms = (
                getattr(self, "total_llm_ms", 0.0) + spent_ms
            )

        except InterruptedError:
            # User said "stop"/"hey Jarvis" mid-think: surface it to
            # the brain loop instead of inventing a decision.
            raise
        except Exception as error:
            print(f"Brain LLM call failed: {error}")

            error_text = str(error).lower()

            if (
                "413" in error_text
                or "429" in error_text
                or "rate limit" in error_text
                or "tokens per minute" in error_text
            ):
                return {
                    "type": "rate_limited",
                    "request": user_input,
                }

            return {
                "type": "unknown",
                "request": user_input,
            }

        decision = _extract_json(response)

        if decision is None:
            return {
                "type": "unknown",
                "request": user_input,
            }

        kind = decision.get("type")

        # speak carries the actual answer text.
        if kind == "speak":
            speech = str(
                decision.get("speech")
                or decision.get("answer")
                or decision.get("text")
                or ""
            ).strip()

            if _looks_like_json(speech):
                speech = ""

            return {
                "type": "speak",
                "speech": speech,
                "request": user_input,
            }

        if kind == "clarify":
            question = str(decision.get("question") or "").strip()

            return {
                "type": "clarify",
                "question": question,
                "request": user_input,
            }

        if kind == "action":
            tool = self.catalogue.get_tool(decision.get("tool"))

            if tool is None:
                return {
                    "type": "unknown",
                    "request": user_input,
                }

            parameters = decision.get("parameters")

            if not isinstance(parameters, dict):
                parameters = {}

            return {
                "type": "action",
                "tool": tool.name,
                "parameters": parameters,
                "speech": str(decision.get("speech") or "").strip(),
                # v4 CRITICAL FIX: propagate "then" — the loop's
                # continue-vs-compose contract. It was dropped here,
                # so chained multi-step reasoning NEVER continued
                # past the first tool call in production.
                "then": bool(decision.get("then")),
                "request": user_input,
            }

        if kind == "plan":
            try:
                plan = self.plan_parser.parse(decision)

            except ValueError:
                return {
                    "type": "unknown",
                    "request": user_input,
                }

            actions = []

            for action in plan.actions:
                if self.catalogue.get_tool(action.tool) is None:
                    return {
                        "type": "unknown",
                        "request": user_input,
                    }

                actions.append(
                    {
                        "tool": action.tool,
                        "parameters": dict(action.parameters or {}),
                        "description": getattr(
                            action, "description", ""
                        ),
                    }
                )

            if not actions:
                return {
                    "type": "unknown",
                    "request": user_input,
                }

            return {
                "type": "plan",
                "description": str(
                    decision.get("description") or ""
                ),
                "actions": actions,
                "request": user_input,
            }

        if kind == "rate_limited":
            return {
                "type": "rate_limited",
                "request": user_input,
            }

        if kind == "question":
            # Legacy contract (v2 fakes/tests): a plain chat question.
            # The loop fetches the answer with one direct generation
            # and speaks it verbatim.
            return {
                "type": "speak",
                "speech": "",
                "_speak_raw": True,
                "request": user_input,
            }

        return {
            "type": "unknown",
            "request": str(
                decision.get("request") or user_input
            ),
        }

    # Legacy alias used by tests and older callers.
    def decide(self, user_input, context="", history=None,
               capabilities=None):
        return self.think(
            user_input,
            capabilities=capabilities,
            context=context,
            history=history,
        )

    # ----------------------------------------------------------
    # COMPOSER: tool results -> spoken answer
    # ----------------------------------------------------------

    def compose(self, user_input, history, context: str = "") -> str:
        """
        Turn the REAL results of the loop's steps into one natural
        spoken reply. Returns "" when the composer LLM fails; the
        caller then falls back to deterministic formatting.
        """

        if not history:
            return ""

        lines = []

        for entry in history:
            result = entry.get("result")

            if isinstance(result, (dict, list)):
                result_text = json.dumps(result, default=str)[:300]

            else:
                result_text = str(result)[:300]

            lines.append(
                f"- {entry.get('tool')} "
                f"({'succeeded' if entry.get('success') else 'FAILED'}): "
                f"{result_text}"
            )

        results_text = "\n".join(lines)

        context_text = f"\nRecent conversation:\n{context}\n" if (
            context
        ) else ""

        prompt = f"""You are JARVIS, a personal desktop assistant
speaking aloud. Compose the spoken reply for the user's request,
based ONLY on the real tool results below.

RULES:
- 1-3 short sentences, natural spoken English.
- Report what actually happened. A failed step is reported honestly;
  never claim success you did not see.
- No markdown, no lists, no emojis, no URLs spoken aloud (say "the
  link is on screen" style instead).
- No filler. Do not repeat the user's request back.
{context_text}
User request: {user_input}

Tool results:
{results_text}

Speak the reply now. Output only the reply text."""

        try:
            answer = self.provider.generate(prompt)

        except InterruptedError:
            raise
        except Exception:
            return ""

        answer = str(answer or "").strip()

        if _looks_like_json(answer):
            return ""

        return answer
