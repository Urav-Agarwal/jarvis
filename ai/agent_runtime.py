import difflib
import re
import time

from ai.agent import AgentBrain
from app.activity_log import log_event
from ai.tool_runtime import ToolRuntime
from router.capability_router_v2 import CapabilityRouter
from security.confirmations import ConfirmationManager

try:
    from ai.brain import BrainV3, ReflexLayer

except Exception as _brain_import_error:  # pragma: no cover
    print(f"Brain v3 import failed: {_brain_import_error}")

    BrainV3 = None
    ReflexLayer = None

class AgentRuntime:
    def __init__(self, provider, interrupt_check=None):
        self.brain = AgentBrain(provider)
        self.provider = provider
        self.tools = ToolRuntime()
        self.confirmations = ConfirmationManager()
        self.router = CapabilityRouter(provider)

        # Optional callable returning True when the user has asked to
        # interrupt (checked between plan steps so "stop" halts work).
        self.interrupt_check = interrupt_check
        self._remaining_plan = []
        self._plan_context = {}
        self._last_choices = []

        # Multi-turn WhatsApp send state: when the user asks to
        # message someone without saying what, or when several
        # contacts match the spoken name, JARVIS asks and holds the
        # open slots here until the send completes or is cancelled.
        self._pending_send = None
        self._pending_contact_choices = []

        # Last path/URL/name touched, so follow-ups like "copy that
        # path" or "what was the site?" work without repeating names.
        self.last_artifacts = {"path": None, "url": None, "name": None}

        # Screen-observation recorder: "watch me and learn this" —
        # sees which apps/sites are used (not mouse movements), and
        # converts the timeline into a replayable skill on stop.
        from tools.action_recorder import ActionRecorder

        self.recorder = ActionRecorder(
            vision=getattr(self.tools, "screen_vision", None),
        )

        self._recorder_pending_save = None

        # Pending teach-by-explanation: steps planned, waiting for
        # the user to name the routine ("study setup").
        self._teaching_pending_save = None

        # Agent hands: a drafted email/message awaiting "do it".
        self._pending_draft = None

        # THE JUDGE's receipt: set when a real tool executed this
        # turn (what tool, when). The orchestrator clears it each turn.
        self.last_tool_receipt = None

        # Filming mode mirror: the orchestrator reads this to decide
        # wake behavior. Toggled by the hard voice rules.
        self._filming_mode = False

        # ------------------------------------------------------
        # BRAIN v3: the agent loop + reflex layer. The loop owns
        # how requests are processed (reason -> act -> observe ->
        # reason again); the reflex layer owns pending
        # conversational grammar and speech-level interrupts.
        # ------------------------------------------------------
        self._executor_calls_locked = False

        self.brain_loop = None
        self.reflexes = None

        if BrainV3 is not None and ReflexLayer is not None:
            self.brain_loop = BrainV3(
                reasoner=self.brain,
                execute_tool=self._executor,
                note_receipt=self._set_tool_receipt,
                interrupt_check=self.interrupt_check,
                pre_act=self._pre_act_for_loop,
            )

            self.brain_loop.receipt_for_judge = self._judge_receipt
            self.brain_loop.judge = self._judge_answer
            self.brain_loop.format_result = self._format_tool_result

            self.reflexes = ReflexLayer(self)

    # ------------------------------------------------------
    # EXECUTOR: the one doorway to real tool execution. The loop,
    # the reflexes, and the confirmation flow all run tools through
    # here, so receipts are never missed.
    # ------------------------------------------------------

    def _executor(self, tool_name, parameters=None):
        """
        The gate lives HERE so every path — the loop, plans, reflexes,
        repairs — is covered. Confirmed pending actions are executed
        via tools.execute directly (they already passed this gate).
        """

        parameters = dict(parameters or {})

        if self._requires_confirmation(tool_name):
            description = self._get_confirmation_description(
                tool_name,
                parameters,
            )

            message = self.confirmations.request_confirmation(
                tool_name,
                parameters,
                description,
            )

            return {
                "confirmation_required": True,
                "result": message,
            }

        result = self.tools.execute(tool_name, parameters)

        self._set_tool_receipt(tool_name, parameters, result)

        return result

    def _execute_confirmed(self, tool_name, parameters=None):
        """
        Execute an action that ALREADY passed the confirmation gate
        (the user said yes). Same receipting, no re-gating.
        """

        parameters = dict(parameters or {})

        result = self.tools.execute(tool_name, parameters)

        self._set_tool_receipt(tool_name, parameters, result)

        return result

    def _pre_act_for_loop(self, decision):
        """
        pre_act hook for the loop: resolve pending WhatsApp-send
        grammar (missing contact/message, ambiguous contacts) before
        the executor runs. A non-None reply ends the exchange.
        """

        tool_name = decision.get("tool")
        parameters = decision.get("parameters") or {}

        reply = self._handle_whatsapp_send(tool_name, parameters)

        if reply is not None:
            reply["final"] = True

            return reply

        return None

    def _set_tool_receipt(self, tool_name, parameters, result):
        """
        THE JUDGE's receipt: remember that a REAL tool ran this turn
        (what, with what). Spoken answers claiming an action must be
        backed by this receipt — otherwise they get rewritten.
        """

        try:
            self.last_tool_receipt = {
                "tool": tool_name,
                "parameters": dict(parameters or {}),
                "time": time.time(),
                "success": bool(
                    result.get("success") if isinstance(result, dict)
                    else False
                ),
            }

        except Exception:
            pass

    def process(self, user_input: str, context: str = ""):
        """
        BRAIN v3 — the single entry point for every utterance.

        Order of authority:
        1. THE JUDGE receipt reset (per-turn honesty tracking).
        2. Pending conversational state (a confirmation we asked
           for, a contact pick, a draft awaiting "do it", a teaching
           name): the user is answering OUR question — handled by
           the reflex layer, never by the reasoning loop.
        3. Learned skill triggers the user themselves defined.
        4. Deterministic repairs with narrow triggers (browser
           profile selection, WhatsApp-send clarity). These run
           FIRST only because the reasoning model has repeatedly
           mishandled these exact forms; each one consumes the same
           executor the loop uses, so behavior stays identical.
        5. THE LOOP: reason -> act -> observe the real result ->
           reason again, until the brain speaks the final answer.

        There is deliberately NO keyword interception for
        "what's my battery", "what apps are open", system control,
        research, or pointer/driver requests anymore: the model
        sees the live STATE block and the tool menu and decides.
        """

        # Fresh turn: the honesty judge only trusts receipts from
        # THIS turn's tool executions.
        self.last_tool_receipt = None

        # -------------------------------------------------
        # GOODBYE / SLEEP (v2 position: before everything): "thank
        # you, that's all" ends the exchange, clears pending state,
        # and returns to passive wake-word listening.
        # -------------------------------------------------

        if self._is_sleep_request(user_input):
            self._clear_transient_state()

            if self.recorder.is_active():
                self.recorder.cancel()

            return {
                "success": True,
                "result": (
                    "You're welcome, sir. I'll be here when you need "
                    "me — just say 'Hey JARVIS'."
                ),
                "go_to_sleep": True,
            }

        # -------------------------------------------------
        # REFLEX LAYER: pending grammar, stop/cancel, learned
        # skills. Each returns a full reply or None.
        # -------------------------------------------------

        reflex_reply = self.reflexes.handle(user_input)

        if reflex_reply is not None:
            return reflex_reply

        # -------------------------------------------------
        # SELF SHUTDOWN / RESTART (explicit user command): the
        # assistant's own lifecycle is physical, not conversational.
        # -------------------------------------------------

        self_command = self._match_self_command(user_input)

        if self_command:
            self.confirmations.cancel()
            self._clear_transient_state()

            if self.recorder.is_active():
                self.recorder.cancel()

            if self_command == "shutdown":
                return {
                    "success": True,
                    "result": (
                        "Shutting down. It was a pleasure, sir. "
                        "Goodbye."
                    ),
                    "self_shutdown": True,
                }

            return {
                "success": True,
                "result": (
                    "Restarting myself. Back in a moment, sir."
                ),
                "self_restart": True,
            }

        # -------------------------------------------------
        # META QUESTIONS about the assistant itself: what it can
        # do, how to teach it, how memory works. Fixed, helpful
        # answers that always name the exact phrases.
        # -------------------------------------------------

        capability_answer = self._answer_capability_question(
            user_input
        )

        if capability_answer:
            return {
                "success": True,
                "result": capability_answer,
            }

        # -------------------------------------------------
        # ARTIFACT FOLLOW-UPS ("copy that path", "what was the
        # link"): these read the runtime's own short-term memory of
        # what it just touched — the reasoning loop cannot see it.
        # -------------------------------------------------

        artifact_reply = self._handle_artifact_followup(user_input)

        if artifact_reply is not None:
            return artifact_reply

        # -------------------------------------------------
        # LEARNING MODE: "whenever I say X, do Y" — the phrase the
        # user chose becomes a permanent trigger; parsing the
        # described steps must not burn a reasoning step.
        # -------------------------------------------------

        teaching = self._handle_teaching(user_input)

        if teaching is not None:
            return teaching

        # -------------------------------------------------
        # DETERMINISTIC REPAIRS (narrow, executor-backed)
        # Chat sends and browser+profile requests: high-risk forms
        # the reasoning model has repeatedly fabricated or dropped
        # (tests pin them to zero LLM calls). They route to the SAME
        # executor and confirmation gates the loop uses.
        # -------------------------------------------------

        message_reply = self._handle_message_fast_path(user_input)

        if message_reply is not None:
            return message_reply

        profile_reply = self._handle_browser_profile_request(
            user_input
        )

        if profile_reply is not None:
            return profile_reply

        hands_reply = self._handle_agent_hands(user_input)

        if hands_reply is not None:
            return hands_reply

        pointer_match = re.search(
            r"\bwhere (?:do|can|to) i (?:click|tap|press)\b(.*)$"
            r"|\bshow me where\b(.*)$",
            user_input,
            re.IGNORECASE,
        )

        if pointer_match:
            target = (
                pointer_match.group(1) or pointer_match.group(2) or ""
            ).strip()

            target = re.sub(
                r"^(?:to|for|the|on)\s+",
                "",
                target,
                flags=re.IGNORECASE,
            ).rstrip(".!? ")

            pointer_result = self._executor(
                "screen.pointer",
                {"target": target},
            )

            return {
                "success": pointer_result.get("success", False),
                "result": pointer_result.get(
                    "result", "I couldn't inspect the screen."
                ),
            }

        driver_match = re.search(
            r"\btake over (?:and|&)?\s*(.+)$",
            user_input,
            re.IGNORECASE,
        )

        if driver_match:
            task = driver_match.group(1).strip().rstrip(".!? ")

            driver_result = self._executor(
                "computer.driver",
                {"task": task, "confirmed": False},
            )

            spoken = driver_result.get("result", "")

            # Queue the confirmed execution behind a "go".
            self.confirmations.request_confirmation(
                "computer.driver",
                {"task": task, "confirmed": True},
                f"drive the screen to: {task}",
            )

            return {
                "success": True,
                "result": spoken,
                "confirmation_required": True,
            }

        # -------------------------------------------------
        # RECORDER (watch me and learn this / stop learning /
        # filming-mode toggles): a live screen-capture session is
        # real physical state — must never wait on an LLM call.
        # -------------------------------------------------

        recorder_reply = self._handle_action_recorder(user_input)

        if recorder_reply is not None:
            return recorder_reply

        # -------------------------------------------------
        # THE LOOP
        # -------------------------------------------------

        log_event(
            "request",
            request=user_input[:200],
            engine="brain_v3",
        )

        return self.brain_loop.run(user_input, context=context)

    def _clear_transient_state(self):
        """
        Reset every pending conversational slot. Used by stop/cancel
        and confirmation cancellation.
        """

        self._remaining_plan = []
        self._plan_context = {}
        self._last_choices = []
        self._pending_send = None
        self._pending_contact_choices = []
        self._recorder_pending_save = None

    # ------------------------------------------------------
    # THE JUDGE: receipt helpers (see BrainV3 wiring below)
    # ------------------------------------------------------

    def _judge_receipt(self):
        receipt = self.last_tool_receipt

        return receipt

    def _judge_answer(self, answer: str, receipt) -> str:
        """
        THE JUDGE (pure code, never model-dependent): a spoken answer
        that CLAIMS an action happened ("I've sent it") must be
        backed by this turn's tool receipt. Otherwise downgrade to
        honest phrasing so the assistant never lies.
        """

        if not answer:
            return answer

        if receipt:
            return answer

        if not self._CLAIM_PATTERN.search(answer):
            return answer

        corrected = re.sub(
            r"\bI(?:'ve| have)\s+",
            "I'll get ",
            answer,
            flags=re.IGNORECASE,
        )

        corrected = re.sub(
            r"\b(?:is|are)\s+sent\b",
            "will be sent once you confirm",
            corrected,
            flags=re.IGNORECASE,
        )

        corrected = re.sub(
            r"\b(?:sent|booked|posted|deleted|emailed|texted)\b",
            "ready to go",
            corrected,
            flags=re.IGNORECASE,
        )

        log_event("judge_corrected", answer=answer[:120])

        return corrected

    _CLAIM_PATTERN = re.compile(
        r"\b(?:i(?:'ve| have|'d| had)?\s+(?:just\s+)?)?"
        r"(?:sent|called|booked|posted|paid|deleted|emailed|"
        r"transferred|messed|texted)\b",
        re.IGNORECASE,
    )

    # ------------------------------------------------------
    # SLEEP DETECTION (also used by the reflex layer indirectly
    # through BrainV3's own pattern; kept here for parity with
    # older callers/tests that probe process() directly).
    # ------------------------------------------------------

    def _is_sleep_request(self, user_input: str) -> bool:
        cleaned = re.sub(
            r"\b(?:hey\s+)?jarvis\b",
            " ",
            user_input,
            flags=re.IGNORECASE,
        )

        return bool(
            re.search(
                r"\b(?:thanks|thank\s*you)\b[^.?!]*"
                r"\b(?:that'?s\s+(?:all|it|enough)|no\s+more|"
                r"don'?t\s+need\s+you|bye|goodbye|good\s+night|"
                r"see\s+you|sleep|nothing\s+else)\b"
                r"|^\s*(?:bye|goodbye|good\s+night|see\s+you)\s*$"
                r"|\b(?:go\s+to\s+sleep|take\s+a\s+nap|"
                r"get\s+some\s+rest)\b",
                cleaned,
                re.IGNORECASE,
            )
        )

    # -------------------------------------------------
    # LEGACY v2 SECTION (below this line the file retains the
    # v2 helpers the v3 pipeline still calls: executor,
    # formatting, confirmation plumbing, WhatsApp clarify,
    # teaching, skills, artifacts, drafts, research).
    # -------------------------------------------------

    def _legacy_v2_marker(self):
        pass

    def _legacy_goodbye_placeholder(self):

        # -------------------------------------------------
        # GOODBYE / SLEEP: "thank you, I don't need you anymore"
        # -> brief acknowledgment and back to passive wake-word
        # listening (process exits the conversation; the next 'hey
        # jarvis' starts a fresh exchange with a greeting again).
        # -------------------------------------------------
        sleep_text = re.sub(
            r"\b(?:hey\s+)?jarvis\b",
            " ",
            user_input,
            flags=re.IGNORECASE,
        )

        if re.search(
            r"\b(?:thanks|thank\s*you)\b[^.?!]*"
            r"\b(?:that'?s\s+(?:all|it|enough)|no\s+more|"
            r"don'?t\s+need\s+you|bye|goodbye|good\s+night|"
            r"see\s+you|sleep|nothing\s+else)\b"
            r"|^\s*(?:bye|goodbye|good\s+night|see\s+you)\s*$"
            r"|\b(?:go\s+to\s+sleep|take\s+a\s+nap|get\s+some\s+rest)\b",
            sleep_text,
            re.IGNORECASE,
        ):
            self._remaining_plan = []
            self._plan_context = {}
            self._last_choices = []
            self._pending_send = None
            self._pending_contact_choices = []
            self._recorder_pending_save = None

            if self.recorder.is_active():
                self.recorder.cancel()

            return {
                "success": True,
                "result": (
                    "You're welcome, sir. I'll be here when you need "
                    "me — just say 'Hey JARVIS'."
                ),
                "go_to_sleep": True,
            }

        # -------------------------------------------------
        # SELF SHUTDOWN / RESTART (explicit user command)
        # -------------------------------------------------

        self_command = self._match_self_command(user_input)

        if self_command:
            self.confirmations.cancel()
            self._remaining_plan = []
            self._plan_context = {}
            self._pending_send = None
            self._pending_contact_choices = []
            self._recorder_pending_save = None

            if self.recorder.is_active():
                self.recorder.cancel()

            if self_command == "shutdown":
                return {
                    "success": True,
                    "result": "Shutting down. It was a pleasure, sir. Goodbye.",
                    "self_shutdown": True,
                }

            return {
                "success": True,
                "result": "Restarting myself. Back in a moment, sir.",
                "self_restart": True,
            }

        # -------------------------------------------------
        # CAPABILITY QUESTION: what JARVIS can do / teaching
        # -------------------------------------------------

        capability_answer = self._answer_capability_question(user_input)

        if capability_answer:
            return {
                "success": True,
                "result": capability_answer,
            }

        # -------------------------------------------------
        # HANDLE PENDING CONFIRMATION
        # Fuzzy yes/no. Anything else cancels the pending
        # action and is processed as a NEW request — the
        # confirmation question is never repeated.
        # -------------------------------------------------

        if self.confirmations.has_pending():

            normalized = user_input.lower().strip().rstrip(".!?, ")

            if self._is_confirmation_no(normalized):
                self.confirmations.cancel()
                self._remaining_plan = []
                self._plan_context = {}
                self._last_choices = []
                self._pending_send = None
                self._pending_contact_choices = []

                return {
                    "success": True,
                    "result": (
                        "Okay, I've cancelled that. Nothing was changed."
                    ),
                }

            if self._is_confirmation_yes(normalized):
                pending = self.confirmations.consume()

                # A completed WhatsApp clarify flow ends here too.
                self._pending_send = None
                self._pending_contact_choices = []

                if pending is None:
                    return {
                        "success": False,
                        "result": "There is no pending action to confirm.",
                    }

                tool_result = self.tools.execute(
                    pending["tool"],
                    pending["parameters"],
                )

                # Continue any plan that was paused for confirmation.
                remaining = self._remaining_plan
                self._remaining_plan = []

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

                spoken = self._format_tool_result(
                    pending["tool"],
                    tool_result.get("result"),
                )

                if remaining:
                    rest = self._execute_actions(remaining)
                    if rest:
                        spoken = f"{spoken} {rest}"

                return {
                    "success": True,
                    "result": spoken,
                }

            # Any other input: drop the pending action silently and
            # treat this as a fresh request instead of looping.
            self.confirmations.cancel()
            self._remaining_plan = []
            self._plan_context = {}
            self._pending_send = None
            self._pending_contact_choices = []

        # -------------------------------------------------
        # PENDING WHATSAPP SEND (clarify flow)
        # Waiting for the user to name a contact, pick among
        # matching contacts, or dictate the message text.
        # -------------------------------------------------

        pending_send_reply = self._handle_pending_send(user_input)

        if pending_send_reply is not None:
            return pending_send_reply

        # -------------------------------------------------
        # AGENT HANDS: a draft awaiting "do it" / revision.
        # -------------------------------------------------

        draft_reply = self._handle_pending_draft(user_input)

        if draft_reply is not None:
            return draft_reply

        # -------------------------------------------------
        # AGENT HANDS: new draft requests.
        # -------------------------------------------------

        hands_reply = self._handle_agent_hands(user_input)

        if hands_reply is not None:
            return hands_reply

        # -------------------------------------------------
        # VOICE RESEARCH: "research X" -> summary + sources.
        # -------------------------------------------------

        research_reply = self._handle_research(user_input)

        if research_reply is not None:
            return research_reply

        # -------------------------------------------------
        # SCREEN PACK: "where do I click to X" -> Pointer.
        # -------------------------------------------------

        pointer_match = re.search(
            r"\bwhere (?:do|can|to) i (?:click|tap|press)\b(.*)$"
            r"|\bshow me where\b(.*)$",
            user_input,
            re.IGNORECASE,
        )

        if pointer_match:
            target = (
                pointer_match.group(1) or pointer_match.group(2) or ""
            ).strip()

            target = re.sub(
                r"^(?:to|for|the|on)\s+",
                "",
                target,
                flags=re.IGNORECASE,
            ).rstrip(".!? ")

            pointer_result = self.tools.execute(
                "screen.pointer",
                {"target": target},
            )

            return {
                "success": pointer_result.get("success", False),
                "result": self._format_tool_result(
                    "screen.pointer",
                    pointer_result.get("result"),
                ),
            }

        # -------------------------------------------------
        # SCREEN PACK: "take over and X" -> Careful Driver (gated).
        # -------------------------------------------------

        driver_match = re.search(
            r"\btake over (?:and|&)?\s*(.+)$",
            user_input,
            re.IGNORECASE,
        )

        if driver_match:
            task = driver_match.group(1).strip().rstrip(".!?")

            driver_result = self.tools.execute(
                "computer.driver",
                {"task": task, "confirmed": False},
            )

            spoken = self._format_tool_result(
                "computer.driver",
                driver_result.get("result"),
            )

            # Queue the confirmed execution behind a "go".
            self.confirmations.request_confirmation(
                "computer.driver",
                {"task": task, "confirmed": True},
                f"drive the screen to: {task}",
            )

            return {
                "success": True,
                "result": spoken,
                "confirmation_required": True,
            }

        # -------------------------------------------------
        # TEACHING NAME TURN: an explained routine was planned and
        # JARVIS asked what to call it — the next utterance IS the
        # name. Checked early so no other handler hijacks it.
        # -------------------------------------------------

        teaching_name_reply = self._handle_teaching_name(user_input)

        if teaching_name_reply is not None:
            return teaching_name_reply

        # -------------------------------------------------
        # STOP / CANCEL (user authority)
        # -------------------------------------------------

        normalized_stop = user_input.lower().strip().rstrip(".!")

        if normalized_stop in {
            "stop", "stop it", "stop that", "stop whatever you're doing",
            "stop whatever you are doing", "cancel", "cancel that",
            "cancel it", "nevermind", "never mind", "abort",
            "don't do it", "do not do it", "stop the task",
            "cancel the task", "hold on", "wait stop",
        }:
            stopped = self._remaining_plan or (
                self.confirmations.get_pending()
            )

            self._remaining_plan = []
            self._plan_context = {}
            self._last_choices = []
            self._pending_send = None
            self._pending_contact_choices = []
            self._recorder_pending_save = None

            if self.recorder.is_active():
                self.recorder.cancel()
                stopped = True

            self.confirmations.cancel()

            return {
                "success": True,
                "result": (
                    "Stopped. The remaining steps were cancelled."
                    if stopped
                    else "There was nothing running, but okay — stopped."
                ),
            }

        # -------------------------------------------------
        # ARTIFACT FOLLOW-UPS ("copy that path", "what was the link")
        # -------------------------------------------------

        artifact_reply = self._handle_artifact_followup(user_input)

        if artifact_reply is not None:
            return artifact_reply

        # -------------------------------------------------
        # NUMERIC / ORDINAL SELECTION of offered choices
        # -------------------------------------------------

        selection = self._match_selection(user_input)

        if selection is not None:
            self._last_choices = []

            tool_result = self._executor(
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

        # -------------------------------------------------
        # LEARNING MODE: "whenever I say X, do Y"
        # -------------------------------------------------

        teaching = self._handle_teaching(user_input)

        if teaching is not None:
            return teaching

        # -------------------------------------------------
        # LEARNED SKILL TRIGGERS
        # -------------------------------------------------

        try:
            triggered = self.tools.skills.find_by_trigger(user_input)
        except Exception:
            triggered = None

        if triggered is not None:
            result = self.tools._run_skill_steps(triggered)

            message = result.get("message", "Done.")

            # Gated steps are never auto-run: queue the first one for
            # the normal confirmation flow ("say yes or no").
            skipped_steps = result.get("skipped_steps") or []

            if skipped_steps:
                tool_name, parameters = skipped_steps[0]

                description = self._get_confirmation_description(
                    tool_name,
                    parameters,
                )

                self.confirmations.request_confirmation(
                    tool_name,
                    parameters,
                    description,
                )

                self._remaining_plan = skipped_steps[1:]

                message += (
                    f" I also need your confirmation to {description}."
                    " Say yes or no."
                )

            return {
                "success": True,
                "result": message,
            }

        # -------------------------------------------------
        # DETERMINISTIC MESSAGING FAST-PATH (no LLM)
        # "send a message to X saying Y on whatsapp" -> the send tool
        # directly. The LLM sometimes answers chat sends as a question
        # ("Sure, I've sent it" — a lie) or refuses claiming it cannot,
        # so the most common send phrasings never reach it.
        # -------------------------------------------------

        message_reply = self._handle_message_fast_path(user_input)

        if message_reply is not None:
            return message_reply

        # -------------------------------------------------
        # DETERMINISTIC BROWSER+PROFILE FAST-PATH (no LLM)
        # "Open chrome and my personal profile" / "open chrome with
        # the school profile": the LLM planner would split this into
        # two application.open steps and silently drop the profile,
        # so it is parsed here and sent to browser.open directly.
        # -------------------------------------------------

        profile_reply = self._handle_browser_profile_request(user_input)

        if profile_reply is not None:
            return profile_reply

        # -------------------------------------------------
        # ACTION RECORDER ("watch me and learn this")
        # Intercepts start/stop before the LLM; active capture is
        # checked every turn.
        # -------------------------------------------------

        recorder_reply = self._handle_action_recorder(user_input)

        if recorder_reply is not None:
            return recorder_reply

        # -------------------------------------------------
        # TEACHING NAME TURN: after an explained routine was
        # planned, the next utterance is the skill's name.
        # -------------------------------------------------

        teaching_name_reply = self._handle_teaching_name(user_input)

        if teaching_name_reply is not None:
            return teaching_name_reply

        # -------------------------------------------------
        # DETERMINISTIC SYSTEM FAST-PATH (no LLM)
        # Battery/CPU/GPU/RAM/volume/brightness/time commands are
        # pure regex + one tool call: instant, and they keep working
        # even when the LLM quota is exhausted (burst commands at
        # 22:09 were failing on Groq's 8k tokens-per-minute limit).
        # -------------------------------------------------

        fast_path = self._system_fast_path(user_input)

        if fast_path is not None:
            return {
                "success": True,
                "result": fast_path,
            }

        # -------------------------------------------------
        # NORMAL JARVIS PROCESSING
        # -------------------------------------------------

        # Step 1: capability routing (deterministic-first, LLM only
        # for ambiguity). Failures degrade to the full catalogue.
        try:
            capabilities = self.router.route(user_input)
        except Exception:
            capabilities = []

        log_event(
            "request",
            request=user_input[:200],
            capabilities=capabilities,
        )

        # Step 2: constrain the agent's tool choice to the routed
        # capabilities (no capabilities -> full catalogue). With a
        # capability list, requests are interpreted as actions on the
        # user's computer unless they are clearly general knowledge.
        if capabilities:
            decision = self.brain.think(
                user_input,
                capabilities,
                context,
                force_action=True,
            )
        else:
            decision = self.brain.think(user_input, capabilities, context)

        request_type = decision.get("type")

        # -------------------------------------------------
        # NORMAL QUESTION
        # -------------------------------------------------

        if request_type == "rate_limited":
            return {
                "success": False,
                "result": (
                    "My thinking service hit its per-minute limit just "
                    "now. Give me a few seconds and say that again."
                ),
            }

        if request_type == "question":
            try:
                answer = self.provider.generate(user_input)

            except Exception:
                return {
                    "success": False,
                    "result": (
                        "My thinking service hit its per-minute limit. "
                        "Say that again in a few seconds."
                    ),
                }

            return {
                "success": True,
                "result": answer,
            }

        # -------------------------------------------------
        # CLARIFY: the brain judged the request ambiguous. Ask its
        # ONE question and hold the mic — the answer comes back as
        # a fresh request with the exchange still open.
        # -------------------------------------------------

        if request_type == "clarify":
            question = str(decision.get("question") or "").strip()

            if not question:
                question = (
                    "Could you tell me a little more about that, sir?"
                )

            return {
                "success": True,
                "result": question,
                "clarification": True,
            }

        # -------------------------------------------------
        # PLAN (multi-action request)
        # -------------------------------------------------

        if request_type == "plan":
            try:
                plan = self.brain.plan_parser.parse(decision)
            except ValueError:
                return {
                    "success": False,
                    "result": "I understood the task but couldn't build a valid plan for it.",
                }

            spoken = self._execute_actions(
                [
                    (action.tool, action.parameters)
                    for action in plan.actions
                ]
            )

            return {
                "success": True,
                "result": spoken or "Done.",
            }

        # -------------------------------------------------
        # ACTION
        # -------------------------------------------------

        if request_type == "action":

            tool_name = decision.get("tool")
            parameters = decision.get("parameters", {})

            # ---------------------------------------------
            # WHATSAPP SEND: ask for a missing contact or message
            # (and check for ambiguous contact names) BEFORE the
            # normal confirmation flow.
            # ---------------------------------------------

            whatsapp_reply = self._handle_whatsapp_send(
                tool_name,
                parameters,
            )

            if whatsapp_reply is not None:
                return whatsapp_reply

            # ---------------------------------------------
            # HIGH-RISK ACTION → REQUIRE CONFIRMATION
            # ---------------------------------------------

            if self._requires_confirmation(tool_name):

                description = self._get_confirmation_description(
                    tool_name,
                    parameters,
                )

                message = self.confirmations.request_confirmation(
                    tool_name,
                    parameters,
                    description,
                )

                return {
                    "success": True,
                    "result": message,
                    "confirmation_required": True,
                }

            # ---------------------------------------------
            # NORMAL ACTION → EXECUTE IMMEDIATELY
            # ---------------------------------------------

            tool_result = self.tools.execute(
                tool_name,
                parameters,
            )

            if not tool_result.get("success"):
                return tool_result

            return {
                "success": True,
                "result": self._with_personality(
                    tool_name,
                    self._format_tool_result(
                        tool_name,
                        tool_result.get("result"),
                    ),
                ),
            }

        # -------------------------------------------------
        # UNKNOWN REQUEST → TRY APPS FIRST, THEN FILE AMBIGUITY
        # -------------------------------------------------

        # "Open instagram" must launch the app, never degrade to a
        # filesystem search with "found many results". Every unknown
        # open/launch request gets an app-resolution attempt first.
        if re.search(
            r"\b(?:open|launch|start|run)\b",
            user_input.lower(),
        ):
            app_match = re.search(
                r"\b(?:open|launch|start|run)\s+(?:up\s+|my\s+|the\s+)?"
                r"([a-z0-9][a-z0-9 +\-]{1,28}?)"
                r"(?:\s+(?:app|application|for me|please|now))?"
                r"(?:\s+and\b.*)?$",
                user_input.lower(),
                re.IGNORECASE,
            )

            if app_match:
                candidate = app_match.group(1).strip()

                opened = self.tools.execute(
                    "application.open",
                    {"application": candidate},
                )

                if opened.get("success"):
                    return {
                        "success": True,
                        "result": f"Opening {candidate}.",
                    }

        # "Open my notes" with several matches should trigger a
        # follow-up question instead of a flat failure (context 17).
        if re.search(
            r"\b(?:open|find|show|launch)\b",
            user_input.lower(),
        ):
            request = self._unknown_request_text(decision, user_input)

            search_result = self.tools.execute(
                "filesystem.search",
                {"query": request},
            )

            if search_result.get("success"):
                result = search_result.get("result")

                matches = (
                    result
                    if isinstance(result, list)
                    else []
                )

                matches = [
                    match
                    for match in matches
                    if isinstance(match, dict) and match.get("path")
                ]

                if len(matches) == 1:
                    opened = self.tools.execute(
                        "filesystem.open",
                        {"path": matches[0]["path"]},
                    )

                    if opened.get("success"):
                        return {
                            "success": True,
                            "result": (
                                f"I found {matches[0].get('name', 'it')} "
                                "and opened it."
                            ),
                        }

                if len(matches) > 1:
                    self._last_choices = matches[:5]

                    # Speak names only — never read paths aloud.
                    # The full path stays available via follow-ups
                    # ("copy the path", "what was the file?").
                    self.last_artifacts["path"] = matches[0].get("path")
                    self.last_artifacts["name"] = matches[0].get("name")

                    options = "\n".join(
                        f"{number}. {match.get('name', 'item')}"
                        for number, match in enumerate(
                            self._last_choices,
                            start=1,
                        )
                    )

                    return {
                        "success": True,
                        "result": (
                            "I found several: \n" + options
                            + "\nWhich one would you like?"
                        ),
                    }

        return {
            "success": False,
            "result": self._unknown_request_text(decision, user_input),
        }

    # ------------------------------------------------------
    # MESSAGING FAST-PATH: deterministic send requests, no LLM.
    # The LLM sometimes fabricates "I've sent it" or refuses sends
    # outright; chat messaging is high-risk and fully tooled, so the
    # common phrasings are matched with regex and executed as the
    # gated send action (which still asks for confirmation).
    # ------------------------------------------------------

    _MESSAGE_FAST_PATTERN = re.compile(
        r"\b(?:send|message|text|whatsapp|ping)\b.*"
        r"\b(?:to|on|via|through)\b.*"
        r"|\b(?:whatsapp|discord|telegram|instagram)\b",
        re.IGNORECASE,
    )

    _MESSAGE_CONTACT_EXTRACTION = re.compile(
        r"\b(?:send|message|text|ping)\b.*?\bto\s+"
        r"([a-z][a-z0-9 .'-]{1,40}?)\s*"
        r"(?:\bon|\bvia|\bthrough|\bin\b|\bsaying\b|\bthat\b|\babout\b|"
        r"\btelling\b|[,;.?!]|$)",
        re.IGNORECASE,
    )

    def _handle_message_fast_path(self, user_input: str):
        """
        Route direct chat-send requests straight to the messaging
        tools (still via the confirmation gate). Returns None for
        anything that is not clearly a chat-send request.
        """

        raw = user_input.strip().rstrip(".!?")
        text = raw.lower()

        # Obvious non-sends exit immediately (cheap).
        if not self._MESSAGE_FAST_PATTERN.search(text):
            return None

        # Polite imperatives are still sends: "can you send a message
        # to mummy". Genuine questions (how/what/why) are not.
        polite = re.compile(
            r"^(?:hey\s+)?(?:jarvis\b[,]?\s*)?"
            r"(?:can|could|would|will)\s+you\s+(?:please\s+)?",
            re.IGNORECASE,
        )

        raw = polite.sub("", raw).strip()
        text = polite.sub("", text).strip()

        if re.search(
            r"\b(?:how (?:do|can|to)|what(?:'s| is)|why|are you able)",
            text,
        ):
            return None

        # "open whatsapp and message vishwa high" / "open whatsapp and
        # send hi to vishwa": strip the launch prefix, it is implied.
        opener = re.compile(
            r"^(?:open|launch|start|bring\s+up)\s+"
            r"(?:whats\s?app|telegram|discord|instagram)\s+and\s+",
            re.IGNORECASE,
        )

        raw = opener.sub("", raw).strip()
        text = opener.sub("", text).strip()

        # ---------------------------------------------
        # APP DETECTION
        # ---------------------------------------------

        app = None

        if re.search(r"\bwhats\s?app\b", text):
            app = "whatsapp"
        elif re.search(r"\btelegram\b", text):
            app = "telegram"
        elif re.search(r"\bdiscord\b", text):
            app = "discord"
        elif re.search(r"\binstagram\b|\binsta\b", text):
            app = "instagram"

        # ---------------------------------------------
        # MESSAGE + CONTACT EXTRACTION
        # "send a message to vishwa saying hi on whatsapp"
        # "send hi to vishwa"        (message BEFORE 'to')
        # "send a message to mummy saying hi"
        # "message vishwa high"      (bare imperative)
        # ---------------------------------------------

        message = ""
        contact = ""

        saying = re.search(
            r"\bsaying\s+(.+?)\s*(?:\bon\s+whats\s?app\b|\bvia\s+whats\s?app\b"
            r"|\bwhats\s?app\b|\bon\s+telegram\b|\bon\s+discord\b"
            r"|\bon\s+instagram\b|\bthrough\s+\w+\b|\bvia\s+\w+\b)?$",
            text,
        )

        if saying:
            message = saying.group(1).strip()

        # Extraction runs on the CASE-PRESERVED text so contact names
        # reach WhatsApp as "Vishwa High", not "vishwa high".
        contact_match = self._MESSAGE_CONTACT_EXTRACTION.search(raw)

        if contact_match:
            contact = " ".join(contact_match.group(1).split())

        # Message stated BEFORE the contact: "send hi to vishwa",
        # "text good morning to mummy".
        if not message and contact:
            before = re.match(
                r"^(?:send|text|ping|whatsapp)\s+(.+?)\s+to\s+",
                text,
            )

            if before:
                candidate = before.group(1).strip()

                # "send a message to X" — that filler is not content.
                if candidate and candidate not in {
                    "a message", "message", "a text", "text",
                    "a msg", "msg", "something", "it", "that",
                }:
                    message = candidate

        if not contact:
            # Bare imperative form: "message vishwa high",
            # "whatsapp mom saying hi", "text mummy hi".
            bare = re.match(
                r"^(?:message|whatsapp|text|ping)\s+"
                r"([a-z][a-z0-9 .'-]{1,40}?)(?:\s+\bon\b|\s+\bvia\b|"
                r"\s+\bsaying\b|\s+\babout\b|\s+\bthat\b|[,;.?!]|$)",
                text,
            )

            if bare:
                contact = " ".join(bare.group(1).split())

        # "message vishwa high saying hi": the bare/`to` extraction
        # stops before 'saying', so 'high' stays in the contact.
        if message and contact:
            message = re.sub(
                rf"^{re.escape(contact)}\s+",
                "",
                message,
                flags=re.IGNORECASE,
            ) or message

        # Contacts are matched by WhatsApp case-insensitively, but a
        # Title Case name reads correctly back to the user.
        if contact and contact.islower():
            contact = contact.title()

        if not contact:
            return None

        # ---------------------------------------------
        # Execute via the EXISTING whatsapp clarify flow: missing
        # message -> "What message should I send to X?"; multiple
        # matches -> numbered choices; single match -> confirm.
        # ---------------------------------------------

        tool = (
            "application.whatsapp_message"
            if app in ("whatsapp", None)
            else "application.send_message"
        )

        parameters = {"contact": contact, "message": message}

        if tool == "application.send_message":
            parameters["app"] = app

        reply = self._handle_whatsapp_send(tool, parameters)

        return reply

    # ------------------------------------------------------
    # BROWSER+PROFILE FAST-PATH: "open chrome and my personal
    # profile" -> one browser.open call with the profile, no LLM.
    # ------------------------------------------------------

    _PROFILE_HINT_PATTERN = re.compile(
        r"\b(profile|account)\b",
        re.IGNORECASE,
    )

    def _handle_browser_profile_request(self, user_input: str):
        """
        Deterministically handle open/switch requests that name a
        browser profile: "open chrome and my personal profile",
        "open chrome with my school account", "switch to my personal
        profile in chrome". Returns None when the request is not a
        browser+profile request (falls through to the normal flow).
        """

        text = user_input.lower().strip().rstrip(".!?")

        if not self._PROFILE_HINT_PATTERN.search(text):
            return None

        if not re.search(
            r"\b(?:open|launch|start|switch|use)\b",
            text,
        ):
            return None

        browser = None

        for known in (
            "chrome", "edge", "firefox", "brave", "opera",
            "comet", "safari",
        ):
            if re.search(rf"\b{known}\b", text):
                browser = known
                break

        if browser is None:
            # "open my personal profile" with no browser named: an
            # already-running browser is implied (context 96 style).
            import psutil

            for process in psutil.process_iter(["name"]):
                try:
                    exe = (process.info["name"] or "").lower()

                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

                if exe in {
                    "chrome.exe", "msedge.exe", "firefox.exe",
                    "brave.exe", "opera.exe", "comet.exe",
                }:
                    browser = exe.removesuffix(".exe").replace(
                        "msedge", "edge"
                    )

                    break

        if browser is None:
            return None

        # Extract the profile phrase. ANY natural phrasing should
        # work: "open chrome and my personal profile", "switch to my
        # school account in chrome", "open my personal chrome
        # profile", "open chrome with the work one". Several word
        # orders are matched before giving up to the LLM planner.
        profile_match = re.search(
            r"\b(?:with|using|and|in|to)\s+"
            r"(?:my\s+|the\s+|your\s+)?"
            r"((?:personal|school|work|college|office|main|default|own)"
            r"(?:\s+(?:profile|account|one|email))?"
            r"|[a-z0-9][a-z0-9 '.-]{0,30}?(?:profile|account))"
            r"(?:\s+(?:profile|account|one|please|now|too|also|as well))*",
            text,
        )

        profile_name = (
            " ".join(profile_match.group(1).split())
            if profile_match
            else ""
        )

        if not profile_name:
            # Possessive order: "open my personal chrome profile",
            # "open the school profile in edge".
            possessive = re.search(
                r"\b(?:my|the|your)\s+"
                r"([a-z][a-z0-9 ]{0,25}?)\s*"
                r"(?:\bchrome\b|\bedge\b|\bfirefox\b|\bbrave\b|"
                r"\bopera\b|\bbrowser\b)?\s*"
                r"(?:profile|account)\b",
                text,
            )

            if possessive:
                profile_name = " ".join(
                    possessive.group(1).split()
                )

        if not profile_name:
            return None

        # Wrapper words that carry no profile meaning ("open my
        # personal chrome profile" -> "personal").
        profile_name = re.sub(
            r"\b(?:chrome|edge|firefox|brave|opera|browser|"
            r"the|a|an|open|launch|start|switch|use|in|on|to|please)\b",
            " ",
            profile_name,
        )

        profile_name = " ".join(profile_name.split())

        opened = self.tools.execute(
            "browser.open",
            {
                "browser": browser,
                "profile": profile_name,
            },
        )

        if not opened.get("success"):
            # Real failure (unknown profile): surface the names the
            # user can pick from instead of a flat error.
            profiles = self.tools.tools.browsers.get_profiles(browser)

            names = ", ".join(
                getattr(profile, "name", str(profile))
                for profile in profiles
            ) or "none found"

            return {
                "success": False,
                "result": (
                    f"I opened {browser.title()} but couldn't find a "
                    f"profile matching '{profile_name}'. The profiles I "
                    f"can see are: {names}."
                ),
            }

        return {
            "success": True,
            "result": (
                f"Opening {browser.title()} with your "
                f"{profile_name} profile."
            ),
        }

    # ------------------------------------------------------
    # ACTION RECORDER: "watch me and learn this" — JARVIS watches
    # the SCREEN (which app/site/file is visible), NOT mouse moves.
    # Stop -> steps are offered as a replayable skill.
    # ------------------------------------------------------

    # Filming mode (reflexes pack): hard voice toggles, code rules.
    _FILMING_ON_PATTERN = re.compile(
        r"\bwe(?:'re| are)\s+filming\b|\bfilming\s+mode\s+on\b"
        r"|\bstart\s+filming\b",
        re.IGNORECASE,
    )

    _FILMING_OFF_PATTERN = re.compile(
        r"\bfilming\s+mode\s+off\b|\bwe(?:'re| are)\s+done\s+filming\b"
        r"|\bstop\s+filming\b",
        re.IGNORECASE,
    )

    _RECORDER_SAVE_NAME_PATTERN = re.compile(
        r"^(?:call it|name it|save it as|save as|named)\s+(.+)$",
        re.IGNORECASE,
    )

    def _handle_action_recorder(self, user_input: str):
        """
        Deterministic interception of recorder start/stop and the
        follow-up naming turn. Returns None when the request has
        nothing to do with the recorder (normal processing).
        """

        # ---------------------------------------------
        # FILMING MODE (reflexes pack): hard voice toggles that work
        # with or without the wake word nearby. Code rule, not LLM.
        # ---------------------------------------------
        if self._FILMING_ON_PATTERN.search(
            user_input.lower()
        ):
            self._filming_mode = True

            return {
                "success": True,
                "result": (
                    "Filming mode on, sir. I'll keep quiet unless you're "
                    "clearly talking to me."
                ),
                "filming_mode": True,
            }

        if self._FILMING_OFF_PATTERN.search(
            user_input.lower()
        ):
            self._filming_mode = False

            return {
                "success": True,
                "result": (
                    "Filming mode off — I'm back to full attention."
                ),
                "filming_mode": False,
            }

        # ---------------------------------------------
        # PENDING SAVE: the user stopped recording and JARVIS asked
        # for a skill name — the next utterance IS the name.
        # ---------------------------------------------

        if self._recorder_pending_save is not None:
            normalized = user_input.lower().strip().rstrip(".!?")

            if normalized in {
                "no", "nope", "nah", "cancel", "never mind",
                "nevermind", "forget it", "don't save", "do not save",
                "discard",
            }:
                self._recorder_pending_save = None

                return {
                    "success": True,
                    "result": "Okay, discarded. Nothing was saved.",
                }

            pending = self._recorder_pending_save
            self._recorder_pending_save = None

            name_match = self._RECORDER_SAVE_NAME_PATTERN.match(
                user_input.strip(),
            )

            name = (
                name_match.group(1).strip()
                if name_match
                else user_input.strip()
            )

            name = name[:40]

            if not name:
                return {
                    "success": True,
                    "result": (
                        "I need a name for that skill. What should I "
                        "call it?"
                    ),
                }

            saved = self.tools.skills.create(
                name,
                "Learned by watching the screen: "
                + "; ".join(
                    filter(
                        None,
                        pending.get("observations", [])[:3],
                    )
                )[:150],
                pending.get("steps", []),
                triggers=[name.lower()],
            )

            if not saved.get("success"):
                return {
                    "success": False,
                    "result": saved.get(
                        "error",
                        "I couldn't save that skill.",
                    ),
                }

            return {
                "success": True,
                "result": (
                    f"Saved. From now on just say '{name}' and I'll run "
                    "those steps for you."
                ),
            }

        text = user_input.lower().strip().rstrip(".!?")

        # ---------------------------------------------
        # STOP while recording: build steps, ask for a name.
        # ---------------------------------------------

        if self.recorder.is_active():
            if re.search(
                r"\bstop\b.*\b(?:learning|recording|watching)\b"
                r"|\bstop\s+learning\b"
                r"|^\s*(?:done|finished|that'?s it|i'?m done)\s*$"
                r"|\b(?:done|finished)\s+(?:with\s+)?(?:the\s+)?task\b",
                text,
            ):
                stopped = self.recorder.stop()

                steps = stopped.get("steps") or []

                if not stopped.get("success") or not steps:
                    return {
                        "success": True,
                        "result": (
                            stopped.get(
                                "message",
                                "I couldn't identify stable steps, so "
                                "nothing was saved.",
                            )
                        ),
                    }

                self._recorder_pending_save = {
                    "steps": steps,
                    "observations": stopped.get("observations") or [],
                }

                summary = stopped.get("message", "")

                return {
                    "success": True,
                    "result": (
                        f"{summary} What should I call this?"
                    ),
                }

            if re.search(
                r"\b(?:cancel|forget it|nevermind|never mind)\b"
                r".*\b(?:learning|recording|watching|it|that)?\b",
                text,
            ) and re.search(
                r"\b(?:cancel|forget it|nevermind|never mind)\b",
                text,
            ):
                self.recorder.cancel()

                return {
                    "success": True,
                    "result": (
                        "Cancelled. I stopped watching and saved "
                        "nothing."
                    ),
                }

            # While recording, anything else still processes normally
            # (the user may talk to JARVIS mid-task); observations
            # keep accumulating in the background.
            return None

        # ---------------------------------------------
        # START: "watch me and learn this", "record my actions",
        # "learn this task", "start recording".
        # ---------------------------------------------

        wants_start = bool(
            (
                re.search(r"\b(?:watch|observe)\b", text)
                and re.search(
                    r"\b(?:learn|record|task|me|screen|steps|actions)\b",
                    text,
                )
            )
            or re.search(
                r"\b(?:start|begin)\s+(?:learning|recording|watching)\b",
                text,
            )
            or re.search(
                r"\blearn\b.{0,24}\b(?:task|routine|action|step|this)\b",
                text,
            )
            or re.search(
                r"\brecord\b.{0,24}\b(?:task|actions|routine|screen|me)\b",
                text,
            )
        )

        if not wants_start:
            return None

        started = self.recorder.start()

        return {
            "success": True,
            "result": started.get(
                "message",
                "Watching. Say 'stop learning' when you're done.",
            ),
            "recording": True,
        }

    # ------------------------------------------------------
    # SYSTEM FAST-PATH: regex -> tool, no LLM involved
    # ------------------------------------------------------

    def _system_fast_path(self, user_input: str):
        """
        Handle the common observation/control commands directly.
        Returns the spoken answer, or None when the request is not a
        simple system command (falls through to the normal brain).
        """

        text = user_input.lower().strip().rstrip(".!?")

        text = re.sub(r"\b(?:hey\s+)?jarvis\b", " ", text)
        text = re.sub(r"\s+", " ", text).strip()

        if not text:
            return None

        # Must look like a system-ish request; otherwise bail fast.
        # Apps/windows/history included so observations stay LLM-free.
        if not re.search(
            r"\b(?:battery|cpu|processor|gpu|graphics|ram|memory|"
            r"volume|sound|brightness|time|date|"
            r"apps?|applications?|programs?|windows?|"
            r"doing|did\s+i\s+do|history)\b",
            text,
        ):
            return None

        runtime = self

        def run(tool_name, parameters=None):
            result = runtime.tools.execute(tool_name, parameters or {})

            if not result.get("success"):
                error = str(result.get("result", "it failed"))

                return f"Sorry, that didn't work: {error[:80]}"

            return runtime._format_tool_result(
                tool_name,
                result.get("result"),
            )

        # ----------------------------------------------------
        # VOLUME (get/set/max/up/down/mute)
        # ----------------------------------------------------
        if re.search(r"\b(?:volume|sound)\b", text):
            if re.search(r"\b(?:mute)\b", text):
                return run("system.volume", {"action": "mute"})

            if re.search(r"\b(?:unmute)\b", text):
                return run("system.volume", {"action": "unmute"})

            if re.search(
                r"\b(?:max|maximum|full|hundred percent|100)\b",
                text,
            ):
                return run("system.volume", {"action": "set", "amount": 100})

            digits = re.search(
                r"(?:to|at)\s*(\d{1,3})\s*(?:percent|%)?",
                text,
            )

            if digits:
                return run(
                    "system.volume",
                    {"action": "set", "amount": int(digits.group(1))},
                )

            delta = re.search(
                r"\b(?:by|about)\s*(\d{1,3})\b",
                text,
            )

            amount = int(delta.group(1)) if delta else None

            if re.search(
                r"\b(?:increase|raise|turn\s+(?:it\s+)?up|louder|go\s+up)\b",
                text,
            ):
                return run("system.volume", {"action": "increase", "amount": amount})

            if re.search(
                r"\b(?:decrease|reduce|lower|turn\s+(?:it\s+)?down|quieter|go\s+down)\b",
                text,
            ):
                return run("system.volume", {"action": "decrease", "amount": amount})

            return run("system.volume", {"action": "get"})

        # ----------------------------------------------------
        # OBSERVATION TOOLS (battery/cpu/gpu/ram/brightness)
        # ----------------------------------------------------
        if re.search(r"\bbattery\b", text):
            return run("system.battery")

        if re.search(r"\b(?:gpu|graphics)\b", text):
            return run("system.gpu")

        if re.search(r"\b(?:cpu|processor)\b", text):
            return run("system.cpu")

        if re.search(r"\b(?:ram|memory usage|memory is|how much memory)\b", text):
            return run("system.memory")

        if re.search(r"\bbrightness\b", text):
            if re.search(r"\b(?:max|maximum|full)\b", text):
                return run("system.brightness", {"action": "set", "amount": 100})

            digits = re.search(
                r"(?:to|at)\s*(\d{1,3})\s*(?:percent|%)?",
                text,
            )

            if digits:
                return run(
                    "system.brightness",
                    {"action": "set", "amount": int(digits.group(1))},
                )

            if re.search(r"\b(?:increase|raise|up|brighter)\b", text):
                return run("system.brightness", {"action": "increase"})

            if re.search(r"\b(?:decrease|lower|down|dim|darker)\b", text):
                return run("system.brightness", {"action": "decrease"})

            return run("system.brightness", {"action": "get"})

        # ----------------------------------------------------
        # TIME / DATE
        # ----------------------------------------------------
        if re.search(
            r"\b(?:time|date|day)\b",
            text,
        ) and re.search(
            r"\b(?:what|whats|current|right\s+now|now|is\s+it|today)\b",
            text,
        ):
            return run("system.time")

        # ----------------------------------------------------
        # RUNNING APPLICATIONS: "what apps are open right now" is a
        # pure observation -> computer.running_apps, NO LLM. Without
        # this the planner used to fall into a FILE search and read
        # out .docx filenames as "applications".
        # ----------------------------------------------------
        if re.search(
            r"\b(?:apps?|applications?|programs?|windows?)\b",
            text,
        ) and re.search(
            r"\b(?:open|running|active|started)\b",
            text,
        ) and re.search(
            r"\b(?:what|which|whats|list|show|tell|see|any)\b",
            text,
        ):
            return run("computer.running_apps")

        # ----------------------------------------------------
        # TIME MACHINE: "what was I doing last Tuesday?" — but
        # "what was that" / "what do you remember" are MEMORY
        # questions, not history queries.
        # ----------------------------------------------------
        if re.search(
            r"\b(?:remember|recall|memory)\b",
            text,
        ):
            return None

        history_match = re.search(
            r"\b(?:what|whats)\b.*\b(?:doing|did)\b.*"
            r"\b(?:last\s+)?(?:monday|tuesday|wednesday|thursday|friday|"
            r"saturday|sunday|yesterday|today|earlier)\b"
            r"|\b(?:what\s+did\s+i\s+do)\b",
            text,
        )

        if history_match:
            period = "today"

            for candidate in (
                "yesterday", "monday", "tuesday", "wednesday",
                "thursday", "friday", "saturday", "sunday",
            ):
                if candidate in text:
                    period = candidate
                    break

            return run("computer.history", {"period": period})

        return None

    # ------------------------------------------------------
    # CONFIRMATION WORD MATCHING (fuzzy, voice-friendly)
    # ------------------------------------------------------

    _YES_PREFIXES = (
        "yes", "yeah", "yep", "yup", "sure", "okay", "ok",
        "confirmed", "confirm", "do it", "go ahead", "proceed",
        "sounds good", "affirmative", "of course", "please do",
        "do that", "go on", "alright", "right",
    )

    _NO_PREFIXES = (
        "no", "nope", "nah", "cancel", "stop", "don't", "dont",
        "do not", "never mind", "nevermind", "abort", "forget it",
        "negative",
    )

    @classmethod
    def _is_confirmation_yes(cls, normalized: str) -> bool:
        if not normalized:
            return False

        if normalized in {"y", "k", "kk", "okey"}:
            return True

        return any(
            normalized == prefix or normalized.startswith(prefix + " ")
            or normalized.startswith(prefix + ",")
            for prefix in cls._YES_PREFIXES
        )

    @classmethod
    def _is_confirmation_no(cls, normalized: str) -> bool:
        if not normalized:
            return False

        if normalized in {"n"}:
            return True

        return any(
            normalized == prefix or normalized.startswith(prefix + " ")
            or normalized.startswith(prefix + ",")
            for prefix in cls._NO_PREFIXES
        )

    # ------------------------------------------------------
    # SELF SHUTDOWN / RESTART MATCHING
    # ------------------------------------------------------

    @staticmethod
    def _match_self_command(user_input: str):
        """
        Detect explicit self-commands: "shut down/shutdown yourself",
        "shut yourself down", "restart yourself", "reboot yourself",
        "restart myself" variants. Returns "shutdown", "restart",
        or None. Deliberately requires "yourself"-style phrasing so
        normal laptop shutdown/restart requests still route to the
        gated system tools.
        """

        text = user_input.lower().strip().rstrip(".!?")

        text = re.sub(r"\bjarvis\b|\bhey\b", " ", text)
        text = re.sub(r"\s+", " ", text).strip()

        shutdown_patterns = (
            "shut down yourself", "shutdown yourself",
            "shut yourself down", "shut yourself off",
            "turn yourself off", "power yourself off",
            "shut down now yourself",
            "exit yourself", "quit yourself",
        )

        restart_patterns = (
            "restart yourself", "reboot yourself",
            "restart yourself now",
            "relaunch yourself", "reload yourself",
        )

        for pattern in shutdown_patterns:
            if pattern in text:
                return "shutdown"

        for pattern in restart_patterns:
            if pattern in text:
                return "restart"

        return None

    # ------------------------------------------------------
    # CAPABILITY / TEACHING / MEMORY QUESTIONS
    # ------------------------------------------------------

    @staticmethod
    def _answer_capability_question(user_input: str):
        """
        Deterministic answers to meta questions so the user always
        knows how to drive JARVIS: what it can do, how to teach it,
        and how memory works.
        """

        text = user_input.lower().strip().rstrip(".!?")

        text = re.sub(r"\bjarvis\b|\bhey\b", " ", text)
        text = re.sub(r"\s+", " ", text).strip()

        # "how do I teach you / how to teach you new tasks"
        if re.search(
            r"\bhow (?:do|can) i (?:teach|train|learn) you\b"
            r"|\bhow (?:do|can) i (?:add|create) (?:a )?(?:new )?(?:task|skill|command)\b"
            r"|\bteach you (?:new )?tasks\b",
            text,
        ):
            return (
                "There are two ways to teach me, sir. The quick way is "
                "to say the steps: whenever I say study setup, open "
                "Chrome and set volume to 30. The other way is to let "
                "me watch: say watch me and learn this, then do the "
                "task on your screen. I'll see which apps and sites you "
                "use, not your mouse. When you're done, say stop "
                "learning, give the routine a name, and it's saved. "
                "From then on just say the name and I'll do those "
                "steps. You can ask what skills I know any time."
            )

        # "will you remember ..." / "do you remember things"
        if re.search(
            r"\bwill you remember\b|\bdo you remember (?:things|stuff|it)\b"
            r"|\bcan you remember\b|\bis your memory persistent\b",
            text,
        ):
            return (
                "Yes. Say remember that, followed by the fact, and I'll "
                "store it permanently, even after a restart. Later just "
                "ask, like: what do you remember about my study plan, or "
                "what's my exam date. You can also say forget that to "
                "remove something."
            )

        # "what can you do" / "what are your features"
        if re.fullmatch(
            r"(?:what (?:all )?can you do|what are you(?:r|) (?:features|abilities|capabilities|skills)"
            r"|what do you do|what tasks can you do|list your (?:features|capabilities|skills))"
            r"(?: for me| exactly| all)?",
            text,
        ):
            return (
                "Quite a lot, sir. I can open apps and websites, search "
                "Google or YouTube, find and open your files, take and "
                "analyze screenshots, set volume and brightness, report "
                "battery, CPU, memory, network and time, set reminders, "
                "remember facts you tell me, and learn custom routines "
                "when you say whenever I say, something, do something. "
                "I always confirm before shutting down, locking or "
                "deleting anything. Try me with whatever you need."
            )

        return None

    # ------------------------------------------------------
    # ARTIFACT FOLLOW-UPS: "copy the path", "what was the site?"
    # ------------------------------------------------------

    def _handle_artifact_followup(self, user_input: str):
        """
        Handle follow-ups about the last file/URL touched: copy the
        path/URL to the clipboard, or speak the path/site NAME only
        when explicitly asked. URLs are otherwise spoken as 'a YouTube
        video' style descriptions, never character by character.
        """

        text = user_input.lower().strip().rstrip(".!?")

        wants_path = bool(
            re.search(
                r"\b(?:copy|read|show|tell|speak|what(?:'s| is)\s+the|"
                r"give me|paste)\b.*\b(?:path|location|folder)\b"
                r"|^\s*(?:the\s+)?path\b",
                text,
            )
        )

        wants_url = bool(
            re.search(
                r"\b(?:copy|read|show|tell|speak|give me|paste)\b.*"
                r"\b(?:url|link|website address)\b"
                r"|^\s*(?:the\s+)?(?:url|link)\b",
                text,
            )
        )

        if not wants_path and not wants_url:
            return None

        wants_copy = bool(
            re.search(r"\b(?:copy|paste)\b", text)
        )

        target_kind = "url" if wants_url else "path"
        value = self.last_artifacts.get(target_kind)

        if not value:
            return {
                "success": False,
                "result": (
                    "I don't have a recent "
                    + ("link" if wants_url else "file")
                    + " to give you."
                ),
            }

        if wants_copy:
            try:
                import win32clipboard
                import win32con

                win32clipboard.OpenClipboard()

                try:
                    win32clipboard.EmptyClipboard()
                    win32clipboard.SetClipboardText(
                        value,
                        win32con.CF_UNICODETEXT,
                    )

                finally:
                    win32clipboard.CloseClipboard()

                spoken_name = self.last_artifacts.get("name")

                if target_kind == "url":
                    reply = "I've copied the link to your clipboard."

                elif spoken_name:
                    reply = (
                        f"I've copied the full path of {spoken_name} to "
                        "your clipboard."
                    )

                else:
                    reply = "I've copied the path to your clipboard."

                return {
                    "success": True,
                    "result": reply,
                }

            except Exception as error:
                return {
                    "success": False,
                    "result": f"I couldn't copy that: {error}",
                }

        # Explicit reveal: speak a human-readable form. The FULL
        # exact value goes to the clipboard via "copy the path/link".
        if target_kind == "url":
            domain = re.sub(r"^https?://", "", value)
            domain = domain.split("/")[0]

            return {
                "success": True,
                "result": (
                    f"The site is {domain}. Say copy the link if you "
                    "want the full address on your clipboard."
                ),
            }

        # Path: comma-separated so it is actually speakable.
        spoken = re.sub(r"[\\/]+", ", ", value).strip(", ")

        return {
            "success": True,
            "result": f"The path is: {spoken}",
        }

    @staticmethod
    def _unknown_request_text(decision: dict, user_input: str) -> str:
        request = decision.get("request")

        if isinstance(request, str) and request.strip():
            return (
                f"I couldn't find a way to do that: {request.strip()}. "
                "Could you rephrase it?"
            )

        return "I couldn't understand that request. Could you rephrase it?"

    def _execute_actions(self, actions) -> str:
        """
        Execute planned actions in order, pausing for confirmation when
        an action requires it. Later actions can consume results from
        earlier ones ("find my notes and open it"). Failed steps are
        retried once; execution stops after repeated failures.

        Returns a spoken summary of outcomes.
        """

        spoken_parts = []

        # Resume with context saved when a plan paused for confirmation.
        context = self._plan_context or {}
        self._plan_context = {}

        consecutive_failures = 0

        while actions:
            # User said "stop" mid-task: halt before the next step.
            if self.interrupt_check is not None and self.interrupt_check():
                spoken_parts.append("Stopped.")
                break

            tool_name, parameters = actions[0]
            actions = actions[1:]

            parameters = self._fill_from_context(
                tool_name,
                parameters,
                context,
            )

            if self._requires_confirmation(tool_name):
                description = self._get_confirmation_description(
                    tool_name,
                    parameters,
                )

                self.confirmations.request_confirmation(
                    tool_name,
                    parameters,
                    description,
                )

                self._remaining_plan = actions
                self._plan_context = context

                spoken_parts.append(
                    f"Before I {description}, please confirm."
                )

                break

            tool_result = self._executor(tool_name, parameters)

            # Bounded recovery: one retry, then stop after repeated
            # failures instead of grinding on (max_consecutive_failures).
            if not tool_result.get("success"):
                tool_result = self._executor(tool_name, parameters)

                if not tool_result.get("success"):
                    consecutive_failures += 1

                    log_event(
                        "tool_failure",
                        tool=tool_name,
                        error=str(tool_result.get("result"))[:200],
                        consecutive=consecutive_failures,
                    )

                    spoken_parts.append(
                        f"{tool_name} failed: {tool_result.get('result', 'unknown error')}"
                    )

                    if consecutive_failures >= 3:
                        spoken_parts.append("I stopped there to avoid doing more harm.")
                        break

                    continue

            consecutive_failures = 0

            result = tool_result.get("result")

            log_event(
                "tool_executed",
                tool=tool_name,
                parameters={
                    key: str(value)[:100]
                    for key, value in parameters.items()
                },
            )

            self._collect_context(
                tool_name,
                parameters,
                result,
                context,
            )

            spoken_parts.append(
                self._format_tool_result(
                    tool_name,
                    result,
                )
            )

        return " ".join(
            part for part in spoken_parts if part
        ).strip()

    @staticmethod
    def _fill_from_context(
        tool_name: str,
        parameters: dict,
        context: dict,
    ) -> dict:
        """
        Fill placeholder parameters (path/url) from results of earlier
        plan steps, enabling "find X ... open it" chains.
        """

        parameters = dict(parameters)

        placeholders = {
            "", "none", "null", "found", "it", "them",
            "the file", "the folder", "the page", "the webpage",
            "the website", "the url", "the link", "the result",
            "the first result", "the relevant page", "the documentation",
            "the relevant webpage", "the relevant file",
        }

        if tool_name.startswith("filesystem.") and "path" in parameters:
            value = parameters.get("path")

            if (
                isinstance(value, str)
                and value.strip().lower() in placeholders
                and context.get("path")
            ):
                parameters["path"] = context["path"]

        if tool_name.startswith("browser.") and "url" in parameters:
            value = parameters.get("url")

            if (
                isinstance(value, str)
                and value.strip().lower() in placeholders
                and context.get("url")
            ):
                parameters["url"] = context["url"]

        return parameters

    # Instance method: it records into self.last_artifacts for
    # spoken follow-ups ("copy the path"), so the old @staticmethod
    # decoration crashed every plan that ran filesystem.search
    # mid-chain with NameError: name 'self' is not defined.
    def _collect_context(
        self,
        tool_name: str,
        parameters: dict,
        result,
        context: dict,
    ):
        """Remember useful values from step results for later steps."""

        if tool_name == "filesystem.search":
            if isinstance(result, list) and result:
                first = result[0]

                if isinstance(first, dict) and first.get("path"):
                    context["path"] = first["path"]

                    # Remember for spoken follow-ups ("copy the path").
                    self.last_artifacts["path"] = first["path"]
                    self.last_artifacts["name"] = first.get("name")

        elif tool_name == "web.search":
            if isinstance(result, dict):
                results = result.get("results") or []

                if results and isinstance(results[0], dict):
                    url = results[0].get("url")

                    if url:
                        context["url"] = url

                        self.last_artifacts["url"] = url
                        self.last_artifacts["name"] = (
                            results[0].get("title") or ""
                        )

        elif tool_name == "browser.tab_state":
            if isinstance(result, dict) and result.get("url"):
                context["url"] = result["url"]

    def _requires_confirmation(self, tool_name: str) -> bool:
        tool = self.brain.catalogue.get_tool(tool_name)

        if tool is None:
            return False

        return tool.confirmation_required

    def _get_confirmation_description(
        self,
        tool_name: str,
        parameters: dict,
    ) -> str:
        if tool_name == "system.lock":
            return "lock your laptop"

        if tool_name == "system.sleep":
            return "put your laptop to sleep"

        if tool_name == "system.restart":
            return "restart your laptop"

        if tool_name == "system.shutdown":
            return "shut down your laptop"

        if tool_name == "filesystem.delete":
            path = parameters.get("path")

            if path:
                return f"delete {path}"

            return "delete the selected file or folder"

        if tool_name == "application.close_all":
            return "close all your running applications"

        if tool_name == "application.send_message":
            app = parameters.get("app", "that app")
            contact = parameters.get("contact", "that contact")

            message = str(parameters.get("message", ""))[:60]

            return (
                f"send a {app} message to {contact} saying: {message}"
            )

        if tool_name == "application.whatsapp_message":
            contact = parameters.get("contact", "that contact")

            message = str(parameters.get("message", ""))[:60]

            return (
                f"send a WhatsApp message to {contact} saying: {message}"
            )

        tool = self.brain.catalogue.get_tool(tool_name)

        if tool:
            return tool.description

        return f"perform {tool_name}"

    # ------------------------------------------------------
    # WHATSAPP SEND CLARIFY FLOW (multi-turn)
    # "Send a message to Vishwa" with no message → ask what to
    # send. Ambiguous contact names → read WhatsApp's own search
    # results and offer the visible names.
    # ------------------------------------------------------

    _WHATSAPP_TOOLS = {"application.whatsapp_message", "application.send_message"}

    def _handle_whatsapp_send(self, tool_name: str, parameters: dict):
        """
        Intercept a planned WhatsApp send BEFORE confirmation. Asks
        for whatever is missing and stores the open slots; returns
        None when the request is complete (normal flow continues).
        """

        if tool_name not in self._WHATSAPP_TOOLS:
            return None

        contact = str(parameters.get("contact") or "").strip()
        message = str(parameters.get("message") or "").strip()

        # ------------------------------------------------------
        # DIRECT REPLY to a message question is handled by
        # _handle_pending_send; here we only START the flow.
        # ------------------------------------------------------

        if not message:
            self._pending_send = {
                "tool": tool_name,
                "app": str(parameters.get("app") or "whatsapp"),
                "contact": contact,
                "message": "",
                "awaiting": "message" if contact else "both",
            }

            if contact:
                return {
                    "success": True,
                    "result": (
                        f"What message should I send to {contact}?"
                    ),
                    "pending_send": True,
                }

            return {
                "success": True,
                "result": (
                    "Who should I message, and what should I say?"
                ),
                "pending_send": True,
            }

        if not contact:
            self._pending_send = {
                "tool": tool_name,
                "app": str(parameters.get("app") or "whatsapp"),
                "contact": "",
                "message": message,
                "awaiting": "contact",
            }

            return {
                "success": True,
                "result": "Who should I send that to?",
                "pending_send": True,
            }

        # Both present: check WhatsApp's own search results. The
        # search check is best-effort: if WhatsApp/OCR is unavailable
        # we keep the spoken name and let the real send verify.
        matches = self._match_contact_candidates(contact)

        if matches is None:
            return None

        if not matches:
            # Search ran fine but WhatsApp shows nothing similar:
            # refuse BEFORE the confirmation stage instead of letting
            # the send fail blind.
            return {
                "success": False,
                "result": (
                    f"I couldn't find anyone like '{contact}' in your "
                    "WhatsApp chats. Check the spelling — maybe say "
                    "the full name or number — and try again."
                ),
            }

        if len(matches) == 1:
            chosen = matches[0]

            self._pending_send = {
                "tool": tool_name,
                "app": str(parameters.get("app") or "whatsapp"),
                "contact": chosen,
                "message": message,
                "awaiting": "confirm",
            }

            return self._request_send_confirmation(
                tool_name,
                chosen,
                message,
            )

        # More than one visible match: offer the names WhatsApp
        # actually shows, like the file-search choice flow.
        self._pending_send = {
            "tool": tool_name,
            "app": str(parameters.get("app") or "whatsapp"),
            "contact": contact,
            "message": message,
            "awaiting": "contact_choice",
        }

        self._pending_contact_choices = matches[:5]

        options = "\n".join(
            f"{number}. {name}"
            for number, name in enumerate(
                self._pending_contact_choices,
                start=1,
            )
        )

        return {
            "success": True,
            "result": (
                f"I found several contacts matching {contact}:\n"
                f"{options}\n"
                "Which one should I message?"
            ),
            "pending_send": True,
        }

    def _match_contact_candidates(self, contact: str):
        """
        Ask WhatsApp itself who matches a spoken contact name.
        Returns a list of visible names, a single-item list when the
        search is unambiguous, or None when the search tool is
        unavailable (best-effort only — never blocks the send).
        """

        runtime_search = getattr(self.tools, "_whatsapp_search", None)

        if runtime_search is None:
            return None

        try:
            result = runtime_search(contact)

        except Exception:
            return None

        if not isinstance(result, dict) or not result.get("success"):
            return None

        contacts = result.get("contacts") or []

        if not contacts:
            # Search ran but found NOTHING similar: real signal the
            # contact name is wrong. Empty list (not None) so the
            # caller can tell the user honestly.
            return []

        lowered = contact.lower().strip()

        exact = [
            name
            for name in contacts
            if name.lower().strip() == lowered
        ]

        if exact:
            return exact
        
        return list(contacts)

    def _handle_pending_send(self, user_input: str):
        """
        Consume the next user turn while a WhatsApp send is waiting
        for the contact choice or the message text. Returns the reply
        dict, or None when there is no pending send (or the user said
        something unrelated, which falls through to normal handling).
        """

        if not self._pending_send:
            return None

        state = self._pending_send

        normalized = user_input.lower().strip().rstrip(".!?")

        # ------------------------------------------------------
        # "never mind" / "cancel": drop the whole pending send.
        # ------------------------------------------------------

        if normalized in {
            "no", "nope", "nah", "cancel", "never mind", "nevermind",
            "forget it", "abort", "stop", "stop it",
        }:
            self._pending_send = None
            self._pending_contact_choices = []

            return {
                "success": True,
                "result": (
                    "Okay, I've cancelled that. Nothing was sent."
                ),
            }

        awaiting = state.get("awaiting")

        # ------------------------------------------------------
        # AWAITING CONTACT CHOICE: number, ordinal, or a name.
        # ------------------------------------------------------

        if awaiting == "contact_choice":
            chosen = self._match_contact_choice(user_input)

            if chosen is None:
                return {
                    "success": True,
                    "result": (
                        "Which contact should I message? Say the name "
                        "or a number from the list."
                    ),
                }

            self._pending_send["contact"] = chosen

            if state.get("message"):
                self._pending_send["awaiting"] = "confirm"

                return self._request_send_confirmation(
                    state.get("tool"),
                    chosen,
                    state.get("message"),
                )

            self._pending_send["awaiting"] = "message"

            return {
                "success": True,
                "result": (
                    f"What message should I send to {chosen}?"
                ),
                "pending_send": True,
            }

        # ------------------------------------------------------
        # AWAITING CONTACT NAME (no message yet or message ready).
        # ------------------------------------------------------

        if awaiting == "contact":
            name = self._extract_contact_name(user_input)

            if not name:
                return {
                    "success": True,
                    "result": (
                        "Who should I send it to? Say a contact name."
                    ),
                }

            self._pending_send["contact"] = name

            if state.get("message"):
                matches = self._match_contact_candidates(name)

                if matches is not None and not matches:
                    return {
                        "success": False,
                        "result": (
                            f"I couldn't find anyone like '{name}' in "
                            "your WhatsApp chats. Check the spelling — "
                            "maybe say the full name or number — and "
                            "try again."
                        ),
                    }

                if matches is None or len(matches) == 1:
                    chosen = (
                        matches[0]
                        if matches
                        else name
                    )

                    self._pending_send["contact"] = chosen
                    self._pending_send["awaiting"] = "confirm"

                    return self._request_send_confirmation(
                        state.get("tool"),
                        chosen,
                        state.get("message"),
                    )

                self._pending_send["awaiting"] = "contact_choice"
                self._pending_contact_choices = matches[:5]

                options = "\n".join(
                    f"{number}. {option_name}"
                    for number, option_name in enumerate(
                        self._pending_contact_choices,
                        start=1,
                    )
                )

                return {
                    "success": True,
                    "result": (
                        f"I found several contacts matching {name}:\n"
                        f"{options}\n"
                        "Which one should I message?"
                    ),
                    "pending_send": True,
                }

            self._pending_send["awaiting"] = "message"

            return {
                "success": True,
                "result": (
                    f"What message should I send to {name}?"
                ),
                "pending_send": True,
            }

        # ------------------------------------------------------
        # AWAITING MESSAGE TEXT (contact already known).
        # ------------------------------------------------------

        if awaiting in {"message", "both"}:
            # "both": the user was asked for contact AND message; the
            # reply usually names the contact first ("to mummy, say hi").
            if awaiting == "both":
                name = self._extract_contact_name(user_input)

                if not name:
                    return {
                        "success": True,
                        "result": (
                            "Who should I message? Say a contact name, "
                            "then the message."
                        ),
                    }

                self._pending_send["contact"] = name
                state = self._pending_send

                remainder = self._extract_message_text(user_input)

                if remainder and remainder.lower() not in {
                    name.lower(),
                    f"to {name.lower()}",
                }:
                    self._pending_send["message"] = remainder

            elif awaiting == "message":
                # The reply IS the message text. (Lowercasing the
                # input is reserved for yes/no matching only — the
                # message keeps the user's own casing.)
                message = self._extract_message_text(user_input)

                if message:
                    self._pending_send["message"] = message

            message = self._pending_send.get("message")

            if not message:
                contact = state.get("contact") or "them"

                self._pending_send["awaiting"] = "message"

                return {
                    "success": True,
                    "result": (
                        f"What exactly should I say to {contact}? "
                        "Just tell me the message."
                    ),
                }

            self._pending_send["message"] = message

            # Contact ambiguity is checked NOW (the tool search needs
            # WhatsApp; doing it here means the user confirms WHICH
            # visible contact before the final yes/no).
            matches = self._match_contact_candidates(
                state.get("contact") or "",
            )

            if matches is not None and len(matches) > 1:
                self._pending_send["awaiting"] = "contact_choice"
                self._pending_contact_choices = matches[:5]

                options = "\n".join(
                    f"{number}. {option_name}"
                    for number, option_name in enumerate(
                        self._pending_contact_choices,
                        start=1,
                    )
                )

                return {
                    "success": True,
                    "result": (
                        f"I found several contacts matching "
                        f"{state.get('contact')}:\n"
                        f"{options}\n"
                        "Which one should I message?"
                    ),
                    "pending_send": True,
                }

            if matches is not None and len(matches) == 1:
                self._pending_send["contact"] = matches[0]

            self._pending_send["awaiting"] = "confirm"

            return self._request_send_confirmation(
                state.get("tool"),
                self._pending_send.get("contact"),
                message,
            )

        # ------------------------------------------------------
        # AWAITING FINAL CONFIRMATION: reuse the confirmation
        # yes/no machinery ("yes" / "send it" → go, else cancel).
        # ------------------------------------------------------

        if awaiting == "confirm":
            if self._is_confirmation_yes(normalized):
                tool_name = state.get("tool")
                contact = state.get("contact")
                message = state.get("message")

                parameters = {
                    "contact": contact,
                    "message": message,
                }

                if tool_name == "application.send_message":
                    parameters["app"] = state.get("app") or "whatsapp"

                self._pending_send = None
                self._pending_contact_choices = []

                tool_result = self.tools.execute(tool_name, parameters)

                if not tool_result.get("success"):
                    return {
                        "success": False,
                        "result": str(tool_result.get("result", "The send failed.")),
                    }

                return {
                    "success": True,
                    "result": self._format_tool_result(
                        tool_name,
                        tool_result.get("result"),
                    ),
                }

            if self._is_confirmation_no(normalized):
                self._pending_send = None
                self._pending_contact_choices = []

                return {
                    "success": True,
                    "result": (
                        "Okay, I've cancelled that. Nothing was sent."
                    ),
                }

            # Anything else: ask again — the user is mid-flow.
            contact = state.get("contact") or "them"
            message = state.get("message") or ""

            preview = message[:60]

            return {
                "success": True,
                "result": (
                    f"To confirm: send '{preview}' to {contact}? "
                    "Say yes or no."
                ),
            }

        self._pending_send = None

        return None

    def _match_contact_choice(self, user_input: str):
        """
        Match a reply against the offered WhatsApp contact list:
        number, ordinal, or (closest) spoken name.
        """

        text = user_input.lower().strip().rstrip(".!")

        ordinals = {
            "first": 0, "second": 1, "third": 2,
            "fourth": 3, "fifth": 4,
        }

        for word, index in ordinals.items():
            if word in text:
                if index < len(self._pending_contact_choices):
                    return self._pending_contact_choices[index]

        match = re.search(r"\b(?:number\s*)?([1-5])\b", text)

        if match:
            index = int(match.group(1)) - 1

            if index < len(self._pending_contact_choices):
                return self._pending_contact_choices[index]

        # Spoken name: closest match wins ("vishwa fatty" → the
        # exact list entry; "the second vishwa" handled above).
        best_name = None
        best_score = 0.0

        for name in self._pending_contact_choices:
            lowered = name.lower()

            if text in lowered or lowered in text:
                return name

            ratio = difflib.SequenceMatcher(
                None,
                text,
                lowered,
            ).ratio()

            if ratio > best_score:
                best_score = ratio
                best_name = name

        if best_score >= 0.55:
            return best_name

        return None

    def _extract_contact_name(self, user_input: str) -> str:
        """
        Pull a contact name out of a reply like "send it to Vishwa"
        or "Vishwa Fatty". Falls back to the raw text when no send
        phrasing is present (it usually IS just the name). Case is
        preserved: WhatsApp matching is case-insensitive, but the
        confirmation question should read naturally.
        """

        cleaned_input = user_input.strip().rstrip(".!?")

        match = re.search(
            r"\bto\s+([a-z0-9][a-z0-9 '.-]{1,40})$",
            cleaned_input,
            re.IGNORECASE,
        )

        if match:
            return match.group(1).strip()

        cleaned = re.sub(
            r"\b(?:send|it|that|the|message|to|him|her|them|on|whatsapp)\b",
            " ",
            cleaned_input,
            flags=re.IGNORECASE,
        )

        cleaned = re.sub(r"\s+", " ", cleaned).strip()

        return cleaned[:40]

    def _extract_message_text(self, user_input: str) -> str:
        """
        The message is whatever the user says — strip only leading
        say/tell scaffolding ("tell him I'll be late" → "I'll be late").
        """

        text = user_input.strip()

        text = re.sub(
            r"^(?:say|tell\s+(?:him|her|them|vishwa|[a-z]+)\s+that|"
            r"tell\s+(?:him|her|them)\s+|say\s+that|"
            r"the\s+message\s+is)\s+",
            "",
            text,
            flags=re.IGNORECASE,
        )

        return text.strip()

    def _request_send_confirmation(
        self,
        tool_name: str,
        contact: str,
        message: str,
    ):
        """
        Ask the final yes/no for an assembled WhatsApp send. The
        pending-send state keeps the flow alive; the confirmation
        manager is NOT used so a stray input can't kill the slots.
        """

        preview = str(message or "")[:60]

        return {
            "success": True,
            "result": (
                f"Ready to send '{preview}' to {contact} on WhatsApp. "
                "Say yes or no."
            ),
            "pending_send": True,
        }

    def _handle_teaching(self, user_input: str):
        """
        Detect "whenever I say <trigger>, <instructions>" and save a
        reusable skill. The instruction part is planned with the normal
        agent brain (one LLM call, one time), then stored as steps.
        Returns None when the input is not a teaching request.
        """

        match = re.search(
            r"(?:whenever|when|every time|each time|anytime|if)\s+i\s+say\s+"
            r"['\"]?(.+?)['\"]?\s*[:,]\s*(.+)",
            user_input,
            re.IGNORECASE | re.DOTALL,
        )

        if not match:
            # No separator: "when I say X you should Y ... do you
            # understand". The trigger/instruction boundary is a
            # 'you should / you have to / then / please' marker.
            match = re.search(
                r"(?:whenever|when|every time|each time|anytime|if)\s+i\s+say\s+"
                r"(.+?)\s*,?\s*(?:you\s+(?:should|have to|need to|must|will)"
                r"|then\s+you|please)\s+(.+)",
                user_input,
                re.IGNORECASE | re.DOTALL,
            )

        if not match:
            # Spoken style with no separator at all: "whenever I say
            # study setup open chrome and set volume to 30". Boundary
            # is the first action verb of the instruction part.
            match = re.search(
                r"(?:whenever|when|every time|each time|anytime)\s+i\s+say\s+"
                r"(.+?)\s+(?="
                r"(?:open|close|launch|start|run|kill|shut\s?down|turn|set|"
                r"increase|decrease|lower|raise|mute|unmute|play|pause|"
                r"search|find|send|remind|take|check|read|"
                r"navigate|go\s+to|type|click|lock|sleep|restart)\b"
                r")(.+)",
                user_input,
                re.IGNORECASE | re.DOTALL,
            )

        if not match:
            # Order-inverted teaching: "I want you to open Chrome and
            # set the volume whenever I say study time" — the trigger
            # comes LAST. This is how people naturally explain tasks.
            inverted = re.search(
                r"^\s*(?:hey\s+)?(?:jarvis\s*[,\-]?\s*)?"
                r"(?:i\s+(?:want|need)\s+you\s+to\s+|can\s+you\s+|"
                r"could\s+you\s+|please\s+|every\s+day\s+)?"
                r"(.+?)\s*[,;]?\s+"
                r"(?:whenever|every\s+time|each\s+time|anytime|when)\s+"
                r"i\s+say\s+['\"]?(.+?)['\"]?\s*$",
                user_input,
                re.IGNORECASE | re.DOTALL,
            )

            if inverted:
                trigger = inverted.group(2).strip()
                instructions = inverted.group(1).strip()

            else:
                # Plain explanation with no trigger phrase at all:
                # "learn this: open Chrome and set the volume to 30".
                # The name (and therefore the trigger) comes from the
                # follow-up naming turn. "remember that ..." is NEVER
                # teaching — that phrasing belongs to the memory tool.
                plain = re.search(
                    r"^\s*(?:hey\s+)?(?:jarvis\s*[,\-]?\s*)?"
                    r"(?:learn|teach yourself|save)\s+(?:this|that|the\s+following|"
                    r"a\s+new\s+(?:task|routine|skill|command))\s*[:,]?\s*(.+)$",
                    user_input,
                    re.IGNORECASE | re.DOTALL,
                )

                if not plain:
                    return None

                trigger = ""
                instructions = plain.group(1).strip()

                # Must look like an ACTION sequence, not a fact:
                # "learn this: open chrome and set volume to 30" yes,
                # "learn this: my exam is on friday" no (that's a
                # memory fact and belongs to memory.remember).
                if not re.search(
                    r"\b(?:open|close|launch|start|run|turn|set|increase|"
                    r"decrease|lower|raise|mute|unmute|play|pause|search|"
                    r"find|send|remind|take|check|read|navigate|go\s+to|"
                    r"type|click|lock|sleep|restart)\b",
                    instructions,
                    re.IGNORECASE,
                ):
                    return None

        else:
            instructions = re.sub(
                r"[\s,]*\b(?:do|did)\s+you\s+understand\b[?!.]*\s*$"
                r"|[\s,]*\b(?:got it|understood|okay|ok)\b[?!.]*\s*$",
                "",
                match.group(2).strip(),
                flags=re.IGNORECASE,
            ).strip()

            trigger = match.group(1).strip()

        if not instructions:
            return {
                "success": False,
                "result": (
                    "I heard the trigger but not the instructions. "
                    "Try: whenever I say study setup, open Chrome and "
                    "lower the volume."
                ),
            }

        # Plan the instructions into concrete tool steps.
        decision = self.brain.think(instructions)

        steps = []

        if decision.get("type") == "plan":
            try:
                plan = self.brain.plan_parser.parse(decision)

                steps = [
                    {
                        "tool": action.tool,
                        "parameters": action.parameters,
                    }
                    for action in plan.actions
                ]

            except ValueError:
                pass

        elif decision.get("type") == "action":
            steps = [
                {
                    "tool": decision.get("tool"),
                    "parameters": decision.get("parameters", {}),
                }
            ]

        if not steps:
            # Fallback: let the brain describe the plan in words, and
            # convert those sentences into steps heuristically. This
            # is what makes EXPLANATORY teaching work: the planner
            # may answer with text instead of JSON actions.
            steps = self._steps_from_text(instructions)

        if not steps:
            return {
                "success": False,
                "result": (
                    "I understood the task but couldn't turn it into "
                    "concrete steps. Could you break it down for me?"
                ),
            }

        # ---------------------------------------------
        # DON'T save yet: ask what to call it. The exact-phrase
        # trigger is saved PLUS the core words, so later phrases
        # like "get my study session ready" still fire it.
        # ---------------------------------------------
        self._teaching_pending_save = {
            "steps": steps,
            "description": f"Learned from: {instructions[:100]}",
            "trigger": trigger,
        }

        summary = "; ".join(
            step["tool"] for step in steps
        )

        return {
            "success": True,
            "result": (
                f"Got it — that would be: {summary}. "
                "What should I call this routine?"
            ),
            "awaiting_skill_name": True,
        }

    def _handle_teaching_name(self, user_input: str):
        """
        Consume the naming turn after a teaching explanation. Any
        reasonable phrase is accepted as the skill name; the trigger
        set includes the core words so paraphrases fire the skill.
        """

        if self._teaching_pending_save is None:
            return None

        normalized = user_input.lower().strip().rstrip(".!?")

        # A question or a normal command is NOT a name: let it fall
        # through to normal processing instead of becoming the skill
        # name ("what do you remember about my exam" must still be a
        # memory question even while a name is pending).
        if re.match(
            r"^(?:what|why|how|when|who|where|which|is|are|was|were|"
            r"do|does|did|can|could|would|will|should|whats|open|close|"
            r"send|play|search|find|set|volume|battery|whatsapp)\b",
            normalized,
        ):
            return None

        # Artifact/memory follow-up phrases ("copy the path", "what
        # was the link") are commands with pending-state meaning,
        # never skill names.
        if re.search(
            r"\b(?:copy|paste|path|link|url)\b",
            normalized,
        ):
            return None

        if normalized in {
            "no", "nope", "nah", "cancel", "never mind", "nevermind",
            "forget it", "discard", "don't save", "do not save",
        }:
            self._teaching_pending_save = None

            return {
                "success": True,
                "result": "Okay, discarded. Nothing was saved.",
            }

        pending = self._teaching_pending_save
        self._teaching_pending_save = None

        name = re.sub(
            r"^(?:call it|name it|save it as|save as|named)\s+",
            "",
            user_input.strip().rstrip(".!?") ,
            flags=re.IGNORECASE,
        ).strip()[:40]

        if not name:
            return {
                "success": True,
                "result": "I need a name for that routine. What should I call it?",
            }

        # Triggers: the exact spoken name AND its core words joined,
        # so "get my study session ready" matches a skill saved as
        # "study session" (find_by_trigger also fuzzy-matches).
        triggers = [name.lower()]

        core = " ".join(
            sorted(self.tools.skills._core_words(name)),
        )

        if core and core not in triggers:
            triggers.append(core)

        saved = self.tools.skills.create(
            name,
            pending.get("description", ""),
            pending.get("steps", []),
            triggers=triggers,
        )

        if not saved.get("success"):
            return {
                "success": False,
                "result": saved.get("error", "I couldn't save that skill."),
            }

        return {
            "success": True,
            "result": (
                f"Saved as '{name}'. Say things like 'start {name}' or "
                "'get it ready' and I'll run it."
            ),
        }

    def _steps_from_text(self, text: str) -> list:
        """
        Convert a plain-English task description into tool steps by
        sentence: 'open X', 'set volume to N', 'go to site Y'. Used
        when the planner returns an explanation instead of JSON.
        """

        steps = []

        for sentence in re.split(r"[.\n]", text):
            sentence = " ".join(sentence.lower().split()).strip(" ,;")

            if not sentence:
                continue

            # "open/launch/start X"
            open_match = re.search(
                r"\b(?:open|launch|start)\s+"
                r"([a-z0-9][a-z0-9 +\-]{1,28}?)"
                r"(?:\s+(?:app|application|browser|for me|please|and|then|next))*$",
                sentence.strip(),
            )

            if open_match:
                steps.append(
                    {
                        "tool": "application.open",
                        "parameters": {
                            "application": open_match.group(1).strip(),
                        },
                    }
                )

                continue

            # "set the volume to N" / "volume N percent"
            volume_match = re.search(
                r"\bvolume\b.*?(\d{1,3})",
                sentence,
            )

            if volume_match and re.search(r"\b(?:set|volume)\b", sentence):
                steps.append(
                    {
                        "tool": "system.volume",
                        "parameters": {
                            "action": "set",
                            "amount": int(volume_match.group(1)),
                        },
                    }
                )

                continue

            # "search youtube for X" / "go to site" — browser search.
            site_match = re.search(
                r"\b(?:search|look(?:\s+up)?)\s+"
                r"(?:youtube|google)\s+for\s+(.+)",
                sentence,
            )

            if site_match:
                site = (
                    "youtube"
                    if "youtube" in sentence
                    else "google"
                )

                steps.append(
                    {
                        "tool": "browser.search",
                        "parameters": {
                            "site": site,
                            "query": site_match.group(1).strip(),
                        },
                    }
                )

                continue

            # "play X on youtube" via browser search as well.
            play_match = re.search(
                r"\bplay\s+(.+?)\s+on\s+youtube\b",
                sentence,
            )

            if play_match:
                steps.append(
                    {
                        "tool": "browser.search",
                        "parameters": {
                            "site": "youtube",
                            "query": play_match.group(1).strip(),
                        },
                    }
                )

                continue

            # "take a screenshot"
            if re.search(r"\b(?:screenshot|snapshot)\b", sentence):
                steps.append(
                    {
                        "tool": "screen.screenshot",
                        "parameters": {},
                    }
                )

        return steps

    def _match_selection(self, user_input: str):
        """
        Match "the first one" / "the second one" / "number 2" against
        previously offered choices. Returns the chosen item or None.
        """

        if not self._last_choices:
            return None

        text = user_input.lower().strip().rstrip(".!")

        ordinals = {
            "first": 0, "second": 1, "third": 2,
            "fourth": 3, "fifth": 4,
        }

        index = None

        for word, position in ordinals.items():
            if word in text:
                index = position
                break

        if index is None:
            match = re.search(r"\b(?:number\s*)?([1-5])\b", text)

            if match:
                index = int(match.group(1)) - 1

        if index is None:
            return None

        if index >= len(self._last_choices):
            return None

        return self._last_choices[index]

    # ------------------------------------------------------
    # PERSONALITY: dry-butler flavor and a natural follow-up offer
    # after completed actions. Deterministic, lightweight, and
    # never applied to errors or confirmations.
    # ------------------------------------------------------

    _OPEN_QUIPS = (
        "{app} is up, sir.",
        "{app} is open and at your service.",
        "There you go — {app} is running.",
        "{app} is ready when you are, sir.",
    )

    def _with_personality(self, tool_name: str, spoken: str) -> str:
        """
        Add a natural follow-up offer after successful actions so
        JARVIS behaves like a proactive personal agent: after opening
        WhatsApp, ask who to message; after opening Chrome, ask where
        to navigate. Errors and confirmations stay strictly serious.
        """

        if not spoken:
            return spoken

        lowered = spoken.lower()

        if "confirm" in lowered or "say yes or no" in lowered:
            return spoken

        if tool_name in {
            "application.open", "browser.open",
        } and (
            "open" in lowered or "ready" in lowered
        ):
            if "whatsapp" in lowered:
                return (
                    spoken
                    + " Shall I ping someone before the urge passes?"
                )

            if "chrome" in lowered or "edge" in lowered:
                return spoken + " Where shall I point it?"

            if "spotify" in lowered:
                return spoken + " Something energetic, or background?"

            return spoken + " Anything else while I'm at it?"

        if tool_name == "system.volume" and "percent" in lowered:
            return spoken

        if tool_name == "application.whatsapp_message" and (
            "sent" in lowered
        ):
            return (
                spoken
                + " Delivered with my usual efficiency, sir."
            )

        return spoken

    def _format_tool_result(self, tool_name, result):
        """
        Deterministic formatting for tool results the interpreter does
        not specifically handle. Handles every result shape safely:
        dicts with message, plain strings, lists, nested wrappers.
        """

        if isinstance(result, dict):
            # Nested wrapper from ToolRuntime.execute.
            if (
                set(result.keys()) == {"success", "result"}
                and isinstance(result.get("result"), (dict, list, str))
            ):
                return self._format_tool_result(
                    tool_name,
                    result["result"],
                )

            if isinstance(result.get("message"), str):
                return result["message"]

            if result.get("success") is False and isinstance(
                result.get("error"), str
            ):
                return result["error"]

            if isinstance(result.get("result"), str):
                return result["result"]

        if isinstance(result, str):
            return result

        return self._interpret_tool_result(tool_name, {}, result)

    @staticmethod
    def _folder_name(path: str) -> str:
        """Human name of the folder containing path (never spoken as a full path)."""

        if not isinstance(path, str) or not path:
            return "its folder"

        parts = re.split(r"[\\/]+", path.strip())

        parts = [part for part in parts if part]

        if len(parts) >= 2:
            return parts[-2]

        return "its folder"

    # ------------------------------------------------------
    # VOICE RESEARCH: "Jarvis, research X" -> search, summarize,
    # sources. From the packs; deterministic routing so it never
    # degrades into a casual web.search.
    # ------------------------------------------------------

    def _handle_research(self, user_input: str):
        """
        "research X" -> run web searches, fetch the top sources, and
        deliver a spoken summary WITH its sources. Returns None when
        the request is not a research request.
        """

        text = user_input.lower().strip().rstrip(".!?")

        match = re.search(
            r"\b(?:research|dig\s+into|deep\s+dive(?:\s+on)?|"
            r"find\s+out\s+(?:everything\s+)?about|"
            r"do\s+(?:some\s+)?research\s+(?:on|about))\s+(.{3,120})$",
            text,
        )

        if not match:
            return None

        topic = " ".join(match.group(1).split())

        if not topic:
            return None

        # 1) Search.
        search_result = self.tools.execute(
            "web.search",
            {"query": topic},
        )

        results = []

        if isinstance(search_result.get("result"), dict):
            results = (
                search_result["result"].get("results") or []
            )

        if not results:
            return {
                "success": False,
                "result": (
                    f"I searched for {topic} but found nothing useful, "
                    "sir. Perhaps phrase it differently?"
                ),
            }

        # 2) Fetch the top two sources for substance.
        summaries = []

        for item in results[:2]:
            url = item.get("url") or ""

            if not url:
                continue

            fetched = self.tools.execute(
                "web.fetch",
                {"url": url},
            )

            content = ""

            if isinstance(fetched.get("result"), dict):
                content = str(
                    fetched["result"].get("content", "")
                )[:2500]

            elif isinstance(fetched.get("result"), str):
                content = fetched["result"][:2500]

            summaries.append(
                {
                    "title": item.get("title", "a source"),
                    "url": url,
                    "excerpt": content,
                }
            )

        # 3) Summarize with the brain, grounded in the excerpts.
        source_text = "\n\n".join(
            f"SOURCE: {s['title']} ({s['url']})\n{s['excerpt']}"
            for s in summaries
        )[:5000]

        try:
            answer = self.provider.generate(
                f"Summarize what these sources say about: {topic}. "
                "Answer in 3-4 short spoken sentences in the style of a "
                "witty butler. Ground every claim in the sources; if "
                "they disagree or are thin, say so.\n\n{source_text}"
            )

        except Exception:
            answer = ""

        if not answer:
            first = summaries[0] if summaries else {}
            answer = (
                f"The top source, {first.get('title', 'the results')}, "
                "covers it — I've pinned the details below."
            )

        # 4) The sources card: full links land in the UI + log.
        source_lines = "\n".join(
            f"• {s['title']} — {s['url']}"
            for s in summaries
        )

        self.last_artifacts["url"] = (
            summaries[0]["url"] if summaries else None
        )
        self.last_artifacts["name"] = topic

        log_event(
            "research_completed",
            topic=topic,
            sources=[s["url"] for s in summaries],
        )

        return {
            "success": True,
            "result": (
                f"{answer}\n\nSources:\n{source_lines}\n"
                "Say 'copy the link' for the top source, sir."
            ),
            "research_topic": topic,
            "sources": summaries,
        }

    # ------------------------------------------------------
    # AGENT HANDS: draft first, "do it" gate, then send/copy.
    # The packs' hard rule: nothing leaves the machine without the
    # exact text shown first.
    # ------------------------------------------------------

    def _handle_agent_hands(self, user_input: str):
        """
        Draft emails/messages/content on request; the draft is shown,
        and only an explicit "do it" sends (clipboard for email,
        WhatsApp flow for messages). Returns None when not a draft.
        """

        text = user_input.lower().strip()

        match = re.search(
            r"\bdraft\s+(?:an?\s+)?(?:email|mail|message|whatsapp(?:\s+message)?)\b"
            r"(?:(?:\s+to)\s+(.+?))?"
            r"(?:\s+(?:saying|about|that|for))\s+(.+)$",
            text,
            re.DOTALL,
        )

        if not match:
            return None

        kind = (
            "whatsapp"
            if "whatsapp" in match.group(0)
            else "email"
        )

        recipient = (match.group(1) or "").strip()
        about = (match.group(2) or "").strip()

        if not about:
            return {
                "success": False,
                "result": (
                    "What should the draft say, sir? Give me the gist "
                    "and I'll write it properly."
                ),
            }

        try:
            draft = self.provider.generate(
                f"Write a short, warm, competent {kind} to "
                f"{recipient or 'the recipient'} about: {about}. "
                "3-6 sentences, no placeholders like [name], no subject "
                "line, ready to send as-is."
            )

        except Exception:
            return {
                "success": False,
                "result": (
                    "My writing service is rate-limited this second. "
                    "Ask again in a few moments."
                ),
            }

        draft = (draft or "").strip()

        if not draft:
            return {
                "success": False,
                "result": "The draft came back empty — give me another go.",
            }

        self._pending_draft = {
            "kind": kind,
            "recipient": recipient,
            "text": draft,
        }

        return {
            "success": True,
            "result": (
                f"Here's my draft{(' for ' + recipient) if recipient else ''}:\n\n"
                f"{draft}\n\n"
                "Say 'do it' and I'll send it on its way — or tell me "
                "what to change."
            ),
            "pending_draft": True,
        }

    def _handle_pending_draft(self, user_input: str):
        """
        Consume the turn after a draft was shown: "do it" sends,
        edits revise, anything else falls through untouched.
        """

        if not self._pending_draft:
            return None

        normalized = user_input.lower().strip().rstrip(".!?")

        if normalized in {
            "do it", "send it", "yes", "yes send it", "go ahead",
            "confirmed", "do that", "send",
        }:
            draft = self._pending_draft
            self._pending_draft = None

            kind = draft.get("kind")
            recipient = draft.get("recipient", "")
            text_to_send = draft.get("text", "")

            if kind == "whatsapp" and recipient:
                result = self.tools.execute(
                    "application.whatsapp_message",
                    {
                        "contact": recipient,
                        "message": text_to_send,
                    },
                )

                if not result.get("success"):
                    return {
                        "success": False,
                        "result": str(result.get("result", "The send failed.")),
                    }

                return {
                    "success": True,
                    "result": self._format_tool_result(
                        "application.whatsapp_message",
                        result.get("result"),
                    ),
                }

            # Email (and anything without a verified channel): copy to
            # the clipboard — honest, useful, and one paste away.
            try:
                import win32clipboard
                import win32con

                win32clipboard.OpenClipboard()

                try:
                    win32clipboard.EmptyClipboard()
                    win32clipboard.SetClipboardText(
                        text_to_send,
                        win32con.CF_UNICODETEXT,
                    )

                finally:
                    win32clipboard.CloseClipboard()

            except Exception as error:
                return {
                    "success": False,
                    "result": f"I couldn't reach the clipboard: {error}",
                }

            return {
                "success": True,
                "result": (
                    "The draft is on your clipboard, sir — paste it into "
                    "your mail client and it's away."
                ),
            }

        if normalized in {
            "no", "nope", "cancel", "never mind", "nevermind",
            "forget it", "discard", "scrap it",
        }:
            self._pending_draft = None

            return {
                "success": True,
                "result": "Discarded, sir. Nothing was sent.",
            }

        # A revision request: regenerate with the feedback.
        if re.search(
            r"\b(?:make it|rewrite|revise|change|shorter|longer|more formal|"
            r"more casual|tone)\b",
            normalized,
        ):
            draft = self._pending_draft

            try:
                revised = self.provider.generate(
                    f"Revise this draft per the feedback. Return only the "
                    f"revised draft.\n\nDRAFT:\n{draft.get('text', '')}\n\n"
                    f"FEEDBACK: {user_input.strip()}"
                )

            except Exception:
                return {
                    "success": False,
                    "result": "The rewrite failed — try again in a moment.",
                }

            revised = (revised or "").strip()

            if revised:
                self._pending_draft["text"] = revised

                return {
                    "success": True,
                    "result": (
                        f"Revised:\n\n{revised}\n\n"
                        "Shall I send it?"
                    ),
                    "pending_draft": True,
                }

        # Anything else: NOT about the draft. Keep it pending and let
        # the normal flow handle the input — the user may return to
        # the draft after.
        return None

    def _interpret_tool_result(
        self,
        tool_name: str,
        parameters: dict,
        result,
    ):
        # Second brain: confirm what was stored (the pack's "total
        # recall" flavor) instead of a bare "saved".
        if tool_name == "memory.remember":
            if isinstance(result, dict) and not result.get("success"):
                return result.get("error", "I couldn't store that.")

            try:
                total = len(self.tools.memory.all_facts())

            except Exception:
                total = None

            stored = ""

            if isinstance(result, dict):
                stored = str(result.get("message", ""))

            if total:
                return (
                    f"Committed to memory, sir. {stored} "
                    f"That's {total} fact{'s' if total != 1 else ''} in "
                    "the vault."
                )

            return stored or "Committed to memory, sir."
        # Filesystem search
        if tool_name == "filesystem.search":
            if not result:
                return (
                    f"I couldn't find any file matching "
                    f"{parameters.get('query', 'that request')}."
                )

            first_result = result[0]

            filename = first_result.get("name", "the file")

            folder = self._folder_name(first_result.get("path", ""))

            return (
                f"Yes, I found {filename}. "
                f"It is in your {folder} folder. Say copy the path "
                "if you want the full location."
            )

        # Filesystem information
        if tool_name == "filesystem.info":
            if not result.get("success"):
                return result.get(
                    "error",
                    "I couldn't get information about that file.",
                )

            filename = result.get("name", "the file")
            folder = self._folder_name(result.get("path", ""))
            size = result.get("size", "")
            extension = result.get("extension", "")

            if result.get("is_directory"):
                return (
                    f"{filename} is a folder "
                    f"inside your {folder} folder."
                )

            return (
                f"{filename} is a {extension} file "
                f"and is {size} in size, "
                f"inside your {folder} folder."
            )

        # Current active window
        if tool_name == "computer.active_window":
            if not result.get("success"):
                return "I couldn't determine the active window."

            process = result.get("process", "unknown application")
            title = result.get("title", "")

            if process.lower() == "code.exe":
                application = "Visual Studio Code"
            else:
                application = process.removesuffix(".exe")

            if title:
                return (
                    f"You are currently using {application}. "
                    f"The active window is {title}."
                )

            return f"You are currently using {application}."

        # Currently visible applications
        if tool_name == "computer.running_apps":
            if not result.get("success"):
                return "I couldn't determine which applications are running."

            applications = result.get("applications", [])
            count = result.get("count", len(applications))

            if not applications:
                return (
                    "Nothing visible is running at the moment, sir — "
                    "just the way I like it."
                )

            names = []

            for application in applications:
                name = application.get("name", "Unknown")
                name = name.removesuffix(".exe")
                names.append(name)

            pretty = ", ".join(names)

            if count == 1:
                return (
                    f"Just {names[0]} is open right now. "
                    "Shall I add some company?"
                )

            return (
                f"You've got {count} things going at once: {pretty}. "
                "Quite the operation, sir. Want me to close any of them?"
            )

        # Application state
        if tool_name == "application.state":
            if not result.get("success"):
                return result.get(
                    "error",
                    "I couldn't check that application.",
                )

            application = result.get("application", "That application")
            running = result.get("running", False)

            if running:
                return f"Yes, {application} is currently open."

            return f"No, {application} is not currently open."

        # Browser state
        if tool_name == "browser.state":
            if not result.get("success"):
                return result.get(
                    "error",
                    "I couldn't check that browser.",
                )

            browser = result.get("browser", "That browser")
            running = result.get("running", False)
            matches = result.get("matches", [])

            if not running:
                return f"No, {browser} is not currently open."

            if not matches:
                return f"Yes, {browser} is currently open."

            windows = [
                match.get("window", "")
                for match in matches
                if match.get("window")
            ]

            if windows:
                return (
                    f"Yes, {browser} is currently open. "
                    f"It is showing {windows[0]}."
                )

            return f"Yes, {browser} is currently open."

        # System observation
        if tool_name == "system.cpu":
            if not result.get("success"):
                return result.get(
                    "error",
                    "I couldn't read the CPU information.",
                )

            usage = result.get("usage_percent", 0)
            cores = result.get("cores")
            logical = result.get("logical_processors")

            return (
                f"CPU usage is currently {usage} percent. "
                f"You have {cores} physical cores and "
                f"{logical} logical processors."
            )

        if tool_name == "system.memory":
            if not result.get("success"):
                return result.get(
                    "error",
                    "I couldn't read the memory information.",
                )

            usage = result.get("usage_percent", 0)
            available = result.get("available", "unknown")
            used = result.get("used", "unknown")
            total = result.get("total", "unknown")

            return (
                f"You are currently using {usage} percent of your RAM. "
                f"{used} of {total} is being used, "
                f"with {available} available."
            )

        if tool_name == "system.storage":
            if not result.get("success"):
                return result.get(
                    "error",
                    "I couldn't read the storage information.",
                )

            partitions = result.get("partitions", [])

            if not partitions:
                return "I couldn't find any storage drives."

            storage_details = []

            for partition in partitions:
                storage_details.append(
                    f"{partition.get('drive', 'Unknown drive')} "
                    f"has {partition.get('free', 'unknown')} free "
                    f"out of {partition.get('total', 'unknown')}"
                )

            return "Your storage is: " + "; ".join(storage_details) + "."

        if tool_name == "system.battery":
            if not result.get("success"):
                return result.get(
                    "error",
                    "I couldn't read the battery information.",
                )

            if not result.get("available"):
                return result.get(
                    "message",
                    "Battery information is not available.",
                )

            percentage = result.get("percent", 0)
            plugged_in = result.get("plugged_in", False)

            if plugged_in:
                return f"Your battery is at {percentage} percent and the laptop is plugged in."

            return f"Your battery is at {percentage} percent and the laptop is running on battery."

        if tool_name == "system.network":
            if not result.get("success"):
                return result.get(
                    "error",
                    "I couldn't read the network information.",
                )

            hostname = result.get("hostname", "unknown")
            connections = result.get("active_connections", 0)

            return (
                f"Your computer is named {hostname} and your network "
                f"connection is active, with {connections} active "
                "connections."
            )

        if tool_name == "system.wifi":
            if not result.get("success"):
                return result.get(
                    "error",
                    "I couldn't read the Wi-Fi information.",
                )

            if not result.get("connected"):
                return "Your laptop is not currently connected to Wi-Fi."

            details = result.get("details", {})

            ssid = details.get("ssid", "an unknown network")
            signal = details.get("signal", "unknown")
            band = details.get("band", "unknown")
            channel = details.get("channel", "unknown")

            return (
                f"You're connected to {ssid} on the {band} band, "
                f"channel {channel}, with a signal strength of {signal}."
            )

        if tool_name == "system.wifi_speed":
            if not result.get("success"):
                return result.get(
                    "error",
                    "I couldn't read the Wi-Fi speed.",
                )

            receive = result.get("receive_speed")
            transmit = result.get("transmit_speed")

            if receive is None and transmit is None:
                return "I couldn't determine the current Wi-Fi speed."

            return (
                f"Your Wi-Fi link speed is {receive} megabits per second "
                f"receive and {transmit} megabits per second transmit."
            )

        if tool_name == "system.bluetooth":
            if not result.get("success"):
                return result.get(
                    "error",
                    "I couldn't read the Bluetooth information.",
                )

            if not result.get("available"):
                return "Bluetooth information is not currently available."

            return "Bluetooth is available on your laptop."

        if tool_name == "system.gpu":
            if not result.get("success"):
                return result.get(
                    "error",
                    "I couldn't read the GPU information.",
                )

            usage = result.get("usage_percent", 0)

            return f"Your GPU usage is currently {usage} percent."

        if tool_name == "system.laptop":
            if not result.get("success"):
                return result.get(
                    "error",
                    "I couldn't read the laptop's current state.",
                )

            cpu = result.get("cpu", {})
            memory = result.get("memory", {})
            battery = result.get("battery", {})
            network = result.get("network", {})

            cpu_usage = cpu.get("usage_percent", "unknown")
            memory_usage = memory.get("usage_percent", "unknown")
            battery_percent = battery.get("percent", "unknown")
            hostname = network.get("hostname", "unknown")

            return (
                f"Your laptop is currently at {cpu_usage} percent CPU usage "
                f"and {memory_usage} percent memory usage. "
                f"The battery is at {battery_percent} percent. "
                f"The computer name is {hostname}."
            )

        # Default behavior for tools that already return
        # a human-readable result.
        return result

        