"""
BRAIN v3 — the reasoning engine of JARVIS.

Before v3 the "brain" was a gauntlet of ~20 keyword fast-paths that
intercepted utterances before the LLM ever saw them, plus a
single-shot JSON planner. It behaved like a keyword-oriented piece
of code, not a thinking component.

v3 inverts the architecture:

    understand -> act -> observe the real result -> reason again

One canonical loop, `run()`, drives every request through the same
path. Anything the model needs to know — live machine state, memory,
learned skills, prior turns — is injected into its reasoning context
instead of being pre-decided by regexes.

What is deliberately NOT here anymore:
    - "what battery/what cpu" regex interception. The model reads the
      STATE block and decides itself to call the observation tool.
    - app/history/pointer/driver keyword routers. The model picks the
      tool; the reflex layer only handles reflexes.

What the reflex layer (below) still owns, and why:
    - speech-level interrupts ("stop", "hey jarvis"): physical safety
      of the voice loop; must work even if the LLM is on fire.
    - pending conversational state (confirmations, drafts, contact
      picks, teaching names): the answer to a question WE asked has
      a fixed grammar; a round-trip through the LLM would risk
      corrupting it.
    - deterministic repairs the model has repeatedly proven unable to
      do (browser profile selection), kept as LAST-RESORT fixes after
      the model's decision, not as pre-emptive interception.
    - THE JUDGE receipt rule: a spoken answer claiming an action must
      carry this turn's tool receipt — kept as a post-composition
      repair, never as a reason to skip the brain.

The loop is bounded by MAX_STEPS and an optional interrupt_check so
"stop" kills work at any step boundary.
"""

import json
import re

from ai.agent import _extract_json, _looks_like_json
import time

# Upper bound on reasoning steps per request. Genuine tasks finish in
# 1-3 steps; the bound exists so a confused loop can never spin.
MAX_STEPS = 4

# Reflex phrases: spoken interrupts handled without any LLM.
_STOP_PATTERN = re.compile(
    r"\b(stop|cancel|abort|nevermind|never mind|"
    r"don'?t do (?:it|that)|do not do (?:it|that)|"
    r"forget it|leave it|hold on|wait stop|"
    r"that'?s enough|skip it)\b",
    re.IGNORECASE,
)

_WAKE_PATTERN = re.compile(
    r"\b(?:hey\s+)?(?:jarvis|jamvis)\b", re.IGNORECASE
)

_SLEEP_PATTERN = re.compile(
    r"\b(?:thanks|thank\s*you)\b[^.?!]*"
    r"\b(?:that'?s\s+(?:all|it|enough)|no\s+more|"
    r"don'?t\s+need\s+you|bye|goodbye|good\s+night|"
    r"see\s+you|sleep|nothing\s+else)\b"
    r"|^\s*(?:bye|goodbye|good\s+night|see\s+you)\s*$"
    r"|\b(?:go\s+to\s+sleep|take\s+a\s+nap|get\s+some\s+rest)\b",
    re.IGNORECASE,
)


class BrainV3:
    """
    The agent loop. Owns HOW JARVIS thinks; the catalogue owns WHAT
    JARVIS can do; the provider owns the raw language model.

    Callbacks (all optional, injected by AgentRuntime):

    execute_tool(tool_name, parameters) -> dict   runs a real tool
    interrupt_check() -> bool                     True = user said stop
    note_receipt(tool_name, parameters, result)   receipt observer
    pre_act(decision) -> dict | None              pending-grammar hook
    format_result(tool_name, result) -> str       spoken formatting
    """

    def __init__(
        self,
        reasoner,
        execute_tool,
        note_receipt=None,
        interrupt_check=None,
        max_steps=MAX_STEPS,
        pre_act=None,
        format_result=None,
    ):
        self.reasoner = reasoner          # the LLM (AgentBrain)
        self.execute_tool = execute_tool  # real tool execution
        self.note_receipt = note_receipt or (lambda *a, **k: None)
        self.interrupt_check = interrupt_check
        self.pre_act = pre_act
        self.format_result = format_result or (lambda tool, result: "")
        self.max_steps = max(1, int(max_steps))

        self._last_plan_description = ""

        # Steps of a gated multi-step plan waiting for "yes".
        self._pending_plan_steps = []

    # ----------------------------------------------------------
    # PUBLIC ENTRY: the one loop every request flows through
    # ----------------------------------------------------------

    def run(self, user_input: str, context: str = "") -> dict:
        """
        Returns one of (the runtime may also return a "final" outcome
        produced inside the executor, e.g. a WhatsApp clarify reply):

            {"success": True,  "result": str}              spoken reply
            {"success": False, "result": str}              honest failure
            {"success": True,  "result": str,
             "clarification": True}                        asked a question
            {"success": True,  "result": str,
             "confirmation_required": True}                gated action
            {"success": True,  "result": str, "go_to_sleep": True}
            {"success": False, "result": str,
             "rate_limited": True}                         provider quota

        The orchestrator only ever reads these keys; the loop's
        internals stay private.
        """

        try:
            return self._run_loop(user_input, context)
        except InterruptedError:
            # The user said "stop"/"hey Jarvis" while thinking. This
            # is NOT a failure — re-raise so the orchestrator turns it
            # into the interrupt path (no error message, listen now).
            raise
        except Exception as error:
            print(f"Brain loop error: {error}")
            import traceback

            traceback.print_exc()

            return {
                "success": False,
                "result": (
                    "Something tripped in my head just then, sir. "
                    "Say it again."
                ),
            }

    def _run_loop(self, user_input: str, context: str) -> dict:
        # ------------------------------------------------------
        # REFLEX: sleep / goodbye (before any thinking)
        # ------------------------------------------------------
        if self._is_sleep_request(user_input):
            return {
                "success": True,
                "result": (
                    "You're welcome, sir. I'll be here when you need "
                    "me — just say 'Hey JARVIS'."
                ),
                "go_to_sleep": True,
            }

        # ------------------------------------------------------
        # THE LOOP: reason -> act -> observe -> reason again
        # ------------------------------------------------------
        history = []   # [{"tool", "parameters", "result", "success"}]
        steps = 0

        while steps < self.max_steps:
            # User said "stop" mid-task (checked at every boundary).
            if self._interrupted():
                return self._stopped_reply(history)

            steps += 1

            decision = self.reasoner.decide(
                user_input,
                context=context,
                history=history,
            )

            decision = self._validate_decision(decision)

            kind = decision.get("type")

            # Legacy contract (v2 and older fakes): a plain chat
            # question. v2 fetched the answer with one more direct
            # generation and spoke it verbatim — keep that.
            if kind == "question":
                answer = str(
                    decision.get("answer")
                    or decision.get("speech")
                    or decision.get("text")
                    or ""
                ).strip()

                decision["type"] = "speak"
                decision["speech"] = answer
                decision["_speak_raw"] = not answer

                kind = "speak"

            # ---------------- SPEAK ----------------
            if kind == "speak":
                # v2 contract: fetch the answer with one plain
                # generation pass and speak it verbatim.
                if decision.get("_speak_raw"):
                    raw = self._raw_answer(user_input)

                    if raw:
                        return {
                            "success": True,
                            "result": self.judge(
                                raw,
                                self.receipt_for_judge(),
                            ),
                        }

                    speech = ""

                else:
                    speech = str(decision.get("speech") or "").strip()

                    if _looks_like_json(speech):
                        speech = ""

                if speech:
                    return self._compose_and_judge(
                        user_input,
                        decision,
                        history,
                        context,
                    )

                # The model meant to answer but produced junk. With
                # work done: compose, then deterministic formatting —
                # the REAL tool results are the honest answer.
                if history:
                    composed = self.reasoner.compose(
                        user_input,
                        history,
                        context=context,
                    )

                    if composed and not _looks_like_json(composed):
                        return {
                            "success": True,
                            "result": composed,
                        }

                    spoken = self._deterministic_speech(history)

                    if spoken:
                        return {
                            "success": True,
                            "result": spoken,
                        }

                # Plain chat with no usable text: the v2 escape
                # hatch — one direct generation pass.
                raw = self._raw_answer(user_input)

                if raw:
                    return {
                        "success": True,
                        "result": self.judge(
                            raw,
                            self.receipt_for_judge(),
                        ),
                    }

                return {
                    "success": False,
                    "result": (
                        "I'm not sure how to respond to that, sir. "
                        "Say it again?"
                    ),
                }

            # ---------------- CLARIFY ----------------
            if kind == "clarify":
                question = str(decision.get("question") or "").strip()

                if not question:
                    question = (
                        "Could you tell me a little more about "
                        "that, sir?"
                    )

                return {
                    "success": True,
                    "result": question,
                    "clarification": True,
                }

            if kind == "unknown":
                fallback = self._unknown_fallback(
                    user_input,
                    decision,
                )

                # The brain understood something real: either work
                # already happened (compose it) or the request was a
                # plain question mislabeled as unknown. Never waste a
                # good answer on a flat "I can't do that".
                if fallback.get("success") is False:
                    if history:
                        composed = self.reasoner.compose(
                            user_input,
                            history,
                            context=context,
                        )

                        if composed and not _looks_like_json(
                            composed
                        ):
                            return {
                                "success": True,
                                "result": composed,
                            }

                        spoken = self._deterministic_speech(history)

                        if spoken:
                            return {
                                "success": True,
                                "result": spoken,
                            }

                    else:
                        composed = self.reasoner.compose(
                            user_input,
                            [
                                {
                                    "tool": "reasoning",
                                    "success": False,
                                    "result": str(
                                        decision.get("request")
                                        or user_input
                                    ),
                                }
                            ],
                            context=context,
                        )

                    if composed and not _looks_like_json(composed):
                        return {
                            "success": True,
                            "result": composed,
                        }

                return fallback

            # ---------------- RATE LIMITED ----------------
            if kind == "rate_limited":
                return {
                    "success": False,
                    "result": (
                        "My thinking service hit its per-minute limit "
                        "just now. Give me a few seconds and say that "
                        "again."
                    ),
                    "rate_limited": True,
                }

            # ---------------- PLAN ----------------
            if kind == "plan":
                return self._run_plan(
                    decision,
                    user_input,
                    context,
                )

            # ---------------- ACT ----------------
            if kind == "action":
                outcome = self._act(decision)

                if outcome is None:
                    return self._stopped_reply(history)

                # The runtime finished the exchange inside the
                # executor (a WhatsApp clarify question, a pending
                # pick): its reply IS the answer; loop ends.
                if outcome.get("final"):
                    outcome.pop("final", None)

                    return outcome

                # Gated: the runtime queued a confirmation; the loop
                # ends here and the user's "yes" re-enters process().
                if outcome.get("cancelled"):
                    return {
                        "success": True,
                        "result": (
                            "Okay, I've cancelled that. Nothing was "
                            "changed."
                        ),
                    }

                if outcome.get("confirmation_required"):
                    return {
                        "success": True,
                        "result": outcome["result"],
                        "confirmation_required": True,
                    }

                success = bool(outcome.get("success"))

                history.append(
                    {
                        "tool": decision.get("tool"),
                        "parameters": decision.get("parameters") or {},
                        "result": outcome.get("result"),
                        "success": success,
                    }
                )

                # A pre-written success line is only valid if the
                # step actually succeeded — on failure the next
                # reasoning step owns the reply (correction or an
                # honest report).
                if not success:
                    decision.pop("speech", None)

                if success:
                    speech = str(decision.get("speech") or "").strip()

                    # The model wrote the answer for THIS outcome.
                    if speech and not _looks_like_json(speech):
                        return self._finish(decision, speech)

                    # Single finished step with no pre-written line:
                    # compose the reply from the real result now.
                    # Reasoning continues ONLY when the model marked
                    # "then": true (it wants the result before its
                    # next step) or the step failed.
                    if not decision.get("then"):
                        return self._compose_and_judge(
                            user_input,
                            decision,
                            history,
                            context,
                        )

                # Observation step: reason again over the real result
                # (failure recovery, chained reads, verification).
                continue

            return self._unknown_fallback(user_input, decision)

        # Steps exhausted with an open loop: still speak honestly.
        if history:
            return self._compose_and_judge(
                user_input,
                {"request": user_input},
                history,
                context,
            )

        return {
            "success": False,
            "result": (
                "I couldn't finish that task, sir. It kept needing "
                "one more step than I could take."
            ),
        }

    # ----------------------------------------------------------
    # PLAN: execute a multi-step plan as one reasoning unit
    # ----------------------------------------------------------

    def _run_plan(
        self,
        decision,
        user_input: str,
        context: str,
    ) -> dict:
        """
        Run each step through the executor in order. Later steps
        receive earlier results through the runtime's context
        filling. A gated step pauses the plan in the runtime so the
        user's "yes" continues it. Any failure is reported honestly
        through the composer.
        """

        actions = decision.get("actions") or []

        if not actions:
            return {
                "success": False,
                "result": (
                    "I understood the task but couldn't build a "
                    "valid plan for it."
                ),
            }

        history = []

        for action in actions:
            if self._interrupted():
                return self._stopped_reply(history)

            outcome = self._act(action)

            if outcome is None:
                return self._stopped_reply(history)

            # The executor finished the exchange (WhatsApp clarify
            # question, pending pick): its reply IS the answer.
            if outcome.get("final"):
                outcome.pop("final", None)

                return outcome

            if outcome.get("cancelled"):
                return {
                    "success": True,
                    "result": (
                        "Okay, I've cancelled that. Nothing was "
                        "changed."
                    ),
                }

            if outcome.get("confirmation_required"):
                remaining = [
                    (
                        str(step.get("tool")),
                        dict(step.get("parameters") or {}),
                    )
                    for step in actions[actions.index(action) + 1 :]
                ]

                if remaining:
                    self.pre_queue_plan(remaining)

                return {
                    "success": True,
                    "result": outcome["result"],
                    "confirmation_required": True,
                }

            success = bool(outcome.get("success"))

            history.append(
                {
                    "tool": action.get("tool"),
                    "parameters": action.get("parameters") or {},
                    "result": outcome.get("result"),
                    "success": success,
                }
            )

            if not success:
                break

        # All steps done (or one failed): compose the reply from the
        # REAL results. This is the observe-and-report half of the
        # loop for multi-step work.
        return self._compose_and_judge(
            user_input,
            decision,
            history,
            context,
        )

    def pre_queue_plan(self, steps):
        """Hold the not-yet-run steps of a gated plan."""

        self._pending_plan_steps = list(steps or [])

    def drain_pending_plan(self):
        steps = getattr(self, "_pending_plan_steps", [])

        self._pending_plan_steps = []

        return steps

    # ----------------------------------------------------------
    # ACT: execute one tool through the runtime (gating + receipts)
    # ----------------------------------------------------------

    def _act(self, decision, pre_act=True):
        """
        Execute a validated action. Returns the tool result dict, or
        {"confirmation_required": True, "result": ...} when the
        action was queued behind a confirmation, or None when
        interrupted.
        """

        if self._interrupted():
            return None

        tool_name = decision.get("tool")
        parameters = decision.get("parameters") or {}

        # pre_act hook: the runtime may resolve pending grammar
        # (WhatsApp contact/message clarify) before execution.
        if                pre_act and getattr(self, "pre_act", None) is not None:
            try:
                handled = self.pre_act(decision)

            except Exception as error:
                print(f"pre_act hook failed: {error}")
                handled = None

            if handled is not None:
                return handled

        # Delegate the ENTIRE execution contract (gating, receipts,
        # parameter alignment, retries) to the runtime's executor.
        return self.execute_tool(tool_name, parameters)

    def _deterministic_speech(self, history) -> str:
        """
        Format the last tool result with the runtime's battle-tested
        formatter (memory recall, file searches, observations). Used
        when the composer cannot produce clean text.
        """

        if not history:
            return ""

        last = history[-1]

        try:
            spoken = self.format_result(
                last.get("tool"),
                last.get("result"),
            )

        except Exception:
            spoken = ""

        if spoken and not _looks_like_json(spoken):
            return str(spoken).strip()

        fallback = self._format_history(history)

        if fallback and fallback != "Done.":
            return fallback

        return ""

    def _raw_answer(self, user_input: str) -> str:
        """
        v2 escape hatch for plain chat: one direct generation pass.
        Returns "" when the provider fails or echoes decision JSON.
        """

        try:
            raw = str(
                self.reasoner.provider.generate(user_input) or ""
            ).strip()

        except InterruptedError:
            raise
        except Exception:
            return ""

        return raw

    def _stopped_reply(self, history) -> dict:
        if history:
            done = ", ".join(
                str(h.get("tool")) for h in history if h.get("success")
            )
            if done:
                return {
                    "success": True,
                    "result": f"Stopped, sir. {done} completed.",
                }

        return {
            "success": True,
            "result": "Stopped, sir.",
        }

    # ----------------------------------------------------------
    # COMPOSE: turn the finished work into a natural spoken answer
    # ----------------------------------------------------------

    def _finish(self, decision, spoken: str) -> dict:
        """Judge and return a completed spoken answer."""

        receipt = self.receipt_for_judge()

        judged = self.judge(spoken, receipt)

        return {
            "success": True,
            "result": judged,
        }

    def _compose_and_judge(
        self,
        user_input: str,
        decision: dict,
        history,
        context: str,
    ) -> dict:
        """
        1. If the model's decision already carries good prose, use it.
        2. Else compose from the tool results via one LLM call.
        3. LLM down -> format the results deterministically.
        4. THE JUDGE: no receipt this turn -> downgrade action claims.
        """

        self._last_plan_description = str(
            decision.get("description") or ""
        )

        spoken = str(decision.get("speech") or "").strip()

        # A JSON echo must never be SPOKEN aloud: ignore it and let
        # the composer work from the REAL tool results instead.
        if _looks_like_json(spoken):
            spoken = ""

        if not spoken and history:
            spoken = self.reasoner.compose(
                user_input,
                history,
                context=context,
            )

        if not spoken:
            spoken = self._deterministic_speech(history) or "Done."

        # THE JUDGE (receipt rule): a claim of action with no receipt
        # this turn is downgraded to honest phrasing.
        receipt = self.receipt_for_judge()
        judge_spoken = self.judge(spoken, receipt)

        return {
            "success": True,
            "result": judge_spoken,
        }

    # Overridden via constructor injection by AgentRuntime.
    def receipt_for_judge(self):
        return None

    def judge(self, answer: str, receipt) -> str:
        return answer

    # ----------------------------------------------------------
    # UNKNOWN: try app launch, then file search, like v2 did — but
    # only AFTER the brain already said it cannot help.
    # ----------------------------------------------------------

    def _unknown_fallback(self, user_input: str, decision: dict) -> dict:
        text = user_input.lower().strip()

        if re.search(r"\b(?:open|launch|start|run)\b", text):
            app_match = re.search(
                r"\b(?:open|launch|start|run)\s+"
                r"(?:up\s+|my\s+|the\s+)?"
                r"([a-z0-9][a-z0-9 +\-]{1,28}?)"
                r"(?:\s+(?:app|application|for me|please|now))?"
                r"(?:\s+and\b.*)?$",
                text,
                re.IGNORECASE,
            )

            if app_match:
                candidate = app_match.group(1).strip()

                result = self.execute_tool(
                    "application.open",
                    {"application": candidate},
                )

                if result and result.get("success"):
                    return {
                        "success": True,
                        "result": f"Opening {candidate}.",
                    }

        request = str(decision.get("request") or user_input)

        if re.search(r"\b(?:open|find|show|launch)\b", text):
            search_result = self.execute_tool(
                "filesystem.search",
                {"query": request},
            )

            matches = []

            if search_result and search_result.get("success"):
                raw = search_result.get("result")

                if isinstance(raw, list):
                    matches = [
                        m
                        for m in raw
                        if isinstance(m, dict) and m.get("path")
                    ]

            if len(matches) == 1:
                opened = self.execute_tool(
                    "filesystem.open",
                    {"path": matches[0]["path"]},
                )

                if opened and opened.get("success"):
                    return {
                        "success": True,
                        "result": (
                            f"I found "
                            f"{matches[0].get('name', 'it')} and "
                            "opened it."
                        ),
                    }

            if len(matches) > 1:
                choices = matches[:5]

                self.last_choices = choices

                # Speak names only — never read paths aloud. The
                # full path stays available via follow-ups.
                options = "\n".join(
                    f"{number}. {match.get('name', 'item')}"
                    for number, match in enumerate(choices, start=1)
                )

                return {
                    "success": True,
                    "result": (
                        "I found several: \n" + options
                        + "\nWhich one would you like?"
                    ),
                    "choices": choices,
                    "artifacts": {
                        "path": matches[0].get("path"),
                        "name": matches[0].get("name"),
                    },
                }

        return {
            "success": False,
            "result": (
                "I understood the words, sir, but I don't have a way "
                "to do that yet."
            ),
        }

    # ----------------------------------------------------------
    # VALIDATION
    # ----------------------------------------------------------

    def _validate_decision(self, decision) -> dict:
        if not isinstance(decision, dict):
            return {"type": "unknown", "request": ""}

        kind = decision.get("type")

        if kind == "action":
            tool_name = decision.get("tool")

            tool = self.reasoner.catalogue.get_tool(tool_name)

            if tool is None:
                return {"type": "unknown", "request": ""}

            parameters = decision.get("parameters")

            if not isinstance(parameters, dict):
                parameters = {}

            decision["parameters"] = parameters

        return decision

    def _interrupted(self) -> bool:
        try:
            return bool(
                self.interrupt_check is not None
                and self.interrupt_check()
            )

        except Exception:
            return False

    def _is_sleep_request(self, text: str) -> bool:
        cleaned = re.sub(
            r"\b(?:hey\s+)?jarvis\b",
            " ",
            text,
            flags=re.IGNORECASE,
        )

        return bool(_SLEEP_PATTERN.search(cleaned))

    # ----------------------------------------------------------
    # DETERMINISTIC FORMATTER (composer fallback)
    # ----------------------------------------------------------

    def _format_history(self, history) -> str:
        if not history:
            return "Done."

        parts = []

        for entry in history:
            result = entry.get("result")

            text = ""

            if isinstance(result, dict):
                text = str(
                    result.get("message")
                    or result.get("summary")
                    or result.get("text")
                    or ""
                )

            elif isinstance(result, str):
                text = result

            text = text.strip()

            if text:
                parts.append(text)

        if not parts:
            return "Done."

        return " ".join(parts)[:600]


# ==============================================================
# REFLEX LAYER
# ==============================================================

class ReflexLayer:
    """
    Spoken reflexes and pending conversational state. Runs BEFORE the
    loop on every turn, in fixed priority order. Each handler returns
    a full reply dict or None.

    This is intentionally SMALL. Every handler here must satisfy one
    of the tests in the Reflex doctrine:

    1. It protects the voice loop physically (interrupts, sleep).
    2. It guards pending conversational grammar the user is mid-way
       through (confirmations, contact picks, teaching names, drafts).
    3. It triggers learned skills ("study setup") whose trigger phrase
       the user themselves defined.
    """

    def __init__(self, runtime):
        self.runtime = runtime

    def handle(self, user_input: str) -> dict | None:
        for handler in (
            self._pending_confirmation,
            self._pending_send,
            self._pending_draft,
            self._teaching_name,
            self._learned_skill,
            self._stop_or_cancel,
            self._numeric_selection,
        ):
            try:
                reply = handler(user_input)

            except Exception as error:
                print(f"Reflex {handler.__name__} failed: {error}")
                continue

            if reply is not None:
                return reply

        return None

    # ----------------------------------------------------------

    def _stop_or_cancel(self, text: str) -> dict | None:
        normalized = text.lower().strip().rstrip(".!")

        if normalized in {
            "stop", "stop it", "stop that",
            "stop whatever you're doing",
            "stop whatever you are doing",
            "cancel", "cancel that", "cancel it",
            "nevermind", "never mind", "abort",
            "don't do it", "do not do it",
            "stop the task", "cancel the task",
            "hold on", "wait stop",
        }:
            runtime = self.runtime

            stopped = bool(
                runtime._remaining_plan
                or runtime.confirmations.get_pending()
            )

            runtime._remaining_plan = []
            runtime._plan_context = {}
            runtime._last_choices = []

            if runtime.recorder.is_active():
                runtime.recorder.cancel()
                stopped = True

            runtime.confirmations.cancel()

            return {
                "success": True,
                "result": (
                    "Stopped. The remaining steps were cancelled."
                    if stopped
                    else "There was nothing running, but okay — "
                    "stopped."
                ),
            }

        return None

    def _pending_confirmation(self, text: str) -> dict | None:
        runtime = self.runtime

        if not (
            runtime.confirmations.has_pending()
            or getattr(runtime, "_teaching_pending_save", None)
            is not None
        ):
            return None

        normalized = text.lower().strip().rstrip(".!? ")

        if runtime._is_confirmation_no(normalized):
            runtime.confirmations.cancel()
            runtime._clear_transient_state()

            return {
                "success": True,
                "result": (
                    "Okay, I've cancelled that. Nothing was changed."
                ),
            }

        if runtime._is_confirmation_yes(normalized):
            pending = runtime.confirmations.consume()

            runtime._pending_send = None
            runtime._pending_contact_choices = []
            if pending is None:
                return {
                    "success": False,
                    "result": (
                        "There is no pending action to confirm."
                    ),
                }

            tool_result = runtime._execute_confirmed(
                pending["tool"],
                pending["parameters"],
            )

            # Continue any multi-step plan that paused for the
            # confirmation (v3: gated plans queue their remaining
            # steps on the loop).
            remaining = list(runtime._remaining_plan)

            if getattr(runtime, "brain_loop", None) is not None:
                remaining = remaining + (
                    runtime.brain_loop.drain_pending_plan()
                )

            runtime._remaining_plan = []

            if not tool_result.get("success"):
                error_text = str(
                    tool_result.get("result", "unknown error")
                )

                return {
                    "success": False,
                    "result": (
                        f"Sorry, that didn't work: {error_text}"
                    ),
                }

            spoken = runtime._format_tool_result(
                pending["tool"],
                tool_result.get("result"),
            )

            if remaining:
                rest = runtime._execute_actions(remaining)

                if rest:
                    spoken = f"{spoken} {rest}"

            return {
                "success": True,
                "result": spoken,
            }

        # Any other input while a teaching name is pending: that is
        # the name (consumed by _teaching_name later in the chain).
        if (
            not runtime.confirmations.has_pending()
            and getattr(runtime, "_teaching_pending_save", None)
            is not None
        ):
            return None

        # Any other input: drop the pending action silently and let
        # the request flow to the brain (v2 contract).
        runtime.confirmations.cancel()
        runtime._clear_transient_state()

        return None

    def _pending_send(self, text: str) -> dict | None:
        return self.runtime._handle_pending_send(text)

    def _pending_draft(self, text: str) -> dict | None:
        return self.runtime._handle_pending_draft(text)

    def _teaching_name(self, text: str) -> dict | None:
        return self.runtime._handle_teaching_name(text)

    def _numeric_selection(self, text: str) -> dict | None:
        """
        "open the second one" after JARVIS offered numbered file
        choices. Reading a set of offered options is conversation
        state, not reasoning.
        """

        runtime = self.runtime

        if not runtime._last_choices:
            return None

        selection = runtime._match_selection(text)

        if selection is None:
            return None

        runtime._last_choices = []

        tool_result = runtime._executor(
            "filesystem.open",
            {"path": selection.get("path", "")},
        )

        return {
            "success": tool_result.get("success", False),
            "result": (
                f"Opening {selection.get('name', 'it')}."
                if tool_result.get("success")
                else "I couldn't open that one."
            ),
        }

    def _learned_skill(self, text: str) -> dict | None:
        runtime = self.runtime

        # A TEACHING phrase ("whenever I say X, do Y") must never be
        # eaten by an existing skill whose trigger resembles X — the
        # teaching handler in process() owns those.
        if re.search(
            r"\b(?:whenever|when|every\s+time|each\s+time|anytime)"
            r"\s+i\s+say\b|\blearn\s+(?:this|that)\b"
            r"|\bwatch\s+me\s+and\s+learn\b",
            text,
            re.IGNORECASE,
        ):
            return None

        try:
            triggered = runtime.tools.skills.find_by_trigger(text)

        except Exception:
            triggered = None

        if triggered is None:
            return None

        result = runtime.tools._run_skill_steps(triggered)

        message = result.get("message", "Done.")

        skipped = result.get("skipped_steps") or []

        if skipped:
            tool_name, parameters = skipped[0]

            description = runtime._get_confirmation_description(
                tool_name,
                parameters,
            )

            runtime.confirmations.request_confirmation(
                tool_name,
                parameters,
                description,
            )

            runtime._remaining_plan = skipped[1:]

            message += (
                f" I also need your confirmation to {description}."
                " Say yes or no."
            )

        return {
            "success": True,
            "result": message,
        }
