import os
import re
import subprocess
import sys
import time
from threading import Thread, Event

from PySide6.QtWidgets import QApplication

from ai.agent_runtime import AgentRuntime
from ai.provider import GroqProvider
from app.activity_log import log_event
from audio.microphone import Microphone
from audio.speech_to_text import SpeechToText
from audio.text_to_speech import TextToSpeech
from audio.wake_word import WakeWordDetector


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Marker file left behind right before a self-restart so the fresh
# instance can greet with "I've restarted myself".
_RESTART_FLAG = os.path.join(ROOT, "data", ".restarting")

class Orchestrator:
    def __init__(
        self,
        on_user_message=None,
        on_jarvis_message=None,
        on_state_change=None,
    ):
        self.on_user_message = on_user_message
        self.on_jarvis_message = on_jarvis_message
        self.on_state_change = on_state_change
        self.has_greeted = False
        self.ai = GroqProvider()

        # Barge-in flag shared with the agent runtime (set by the
        # interrupt watcher; checked between plan steps).
        self.interrupt_requested = False

        # Abort event for the reasoning LLM call itself: set the
        # moment the watcher hears "stop" / "hey jarvis", so a
        # mid-thought request dies within a fraction of a second
        # instead of after the provider finishes.
        self.thinking_abort = Event()

        self.agent = AgentRuntime(
            self.ai,
            interrupt_check=lambda: self.interrupt_requested,
        )

        # KILL SWITCH (v4): one switch halts speech, mouse motion,
        # LLM calls, plans and confirmations. Wired into the mouse
        # controller and the provider; callbacks cut speech and
        # clear pending state. Global hotkey Ctrl+Alt+Shift+J.
        from security.kill_switch import get_kill_switch

        self.kill_switch = get_kill_switch()

        self.kill_switch.on_trigger(self._on_kill_switch)

        self.kill_switch.install_hotkey()

        try:
            from tools.computer_controller import ComputerController

            ComputerController.abort_event = self.kill_switch.abort_event

        except Exception:
            pass

        self.ai.abort_events = [self.kill_switch.abort_event]

        # Give the runtime and the brain direct access to the same
        # abort event (checked inside provider.generate).
        self.agent.abort_event = self.thinking_abort
        self.agent.brain.abort_event = self.thinking_abort
        self.microphone = Microphone()
        self.speech_to_text = SpeechToText()
        self.text_to_speech = TextToSpeech()
        self.wake_word = WakeWordDetector()
        self.history = []

        # ------------------------------------------------------
        # INTERRUPTION + SELF-LIFECYCLE STATE
        # ------------------------------------------------------

        # Stop phrases that interrupt JARVIS mid-speech or mid-task.
        self.cancel_pattern = re.compile(
            r"\b(stop|cancel|abort|nevermind|never mind|"
            r"don'?t do (?:it|that)|do not do (?:it|that)|"
            r"forget it|leave it|shut up|be quiet|"
            r"that'?s enough|skip it|hold on)\b",
            re.IGNORECASE,
        )

        # Set to "shutdown" / "restart" by process(); honored right
        # after the farewell has been spoken.
        self.pending_self_command = None

        # Barge-in during processing: the watcher thread lives only
        # while a request is being handled (see listen_and_process).
        self._processing_done = True

        # One-time "I've restarted myself" greeting after a relaunch.
        self.restart_acknowledged = os.path.exists(_RESTART_FLAG)

        # Set when the user says "hey jarvis" while JARVIS is speaking
        # or thinking: the speech is cut and the NEXT wake check is
        # bypassed so the command right after is heard immediately.
        self.pending_wake_interrupt = False

        # Filming mode: wake word disabled, direct address only.
        # Mirrored from the agent's hard voice toggle.
        self.filming_mode = False

        # Self-wake guard: after speaking, JARVIS's own voice is in
        # the room; the wake-word detector gets a cooldown before it
        # may trigger again (tuned past the tail of spoken replies).
        self.wake_cooldown = 2.2

        # ------------------------------------------------------
        # v4 SESSION: the conversation does NOT end with a task.
        # DORMANT -> ACTIVE -> (LISTENING | THINKING | ACTING |
        # SPEAKING) -> ACTIVE ... -> DORMANT. Sleep happens ONLY on
        # an explicit dismissal or the idle timeout (5 min default,
        # settings.yaml: session.idle_timeout_seconds) — never on an
        # exchange count, never after 6 s of silence, never while a
        # confirmation/draft/task is pending.
        # ------------------------------------------------------
        from assistant.session import ConversationSession

        def _busy():
            return (
                self.agent.confirmations.has_pending()
                or getattr(self.agent, "_pending_send", None) is not None
                or getattr(self.agent, "_pending_draft", None) is not None
                or getattr(self.agent, "_teaching_pending_save", None)
                is not None
                or getattr(self.agent, "_recorder_pending_save", None)
                is not None
                or self.speaking
            )

        idle_timeout = 300.0

        try:
            from app.config import get as get_setting

            idle_timeout = float(
                get_setting(
                    "session",
                    "idle_timeout_seconds",
                )
                or 300
            )

        except Exception:
            pass

        self.session = ConversationSession(
            idle_timeout_seconds=idle_timeout,
            busy_check=_busy,
        )

        # CHIME instead of spoken acks on re-wake: JARVIS acknowledges
        # without contributing to the "greeting many times" problem.
        self.wake_chime = True

        # Wake-word refractory period (seconds): re-triggers inside
        # this window after a handled wake are ignored as echoes.
        self._wake_refractory = 1.2
        self._last_wake_handled = 0.0

    def _on_kill_switch(self, reason: str = ""):
        """
        Kill-switch callback: cut speech, clear pending state, cancel
        every queued confirmation. Safe to run from the hotkey thread.
        """

        try:
            self.interrupt_speech()

        except Exception:
            pass

        try:
            self.interrupt_requested = True

            self.thinking_abort.set()

        except Exception:
            pass

        try:
            self.agent.confirmations.cancel()

            self.agent._clear_transient_state()

            if self.agent.recorder.is_active():
                self.agent.recorder.cancel()

        except Exception:
            pass

        try:
            log_event("kill_switch", reason=reason)

        except Exception:
            pass

        # CONVERSATION HOLD: after a command, JARVIS stays in the
        # exchange for a short window waiting for follow-ups like
        # "yes, send it" — no fresh "Hey JARVIS" needed.
        self.conversation_hold_seconds = 12.0
        self.conversation_max_exchanges = 4

        if self.restart_acknowledged:
            try:
                os.remove(_RESTART_FLAG)
            except OSError:
                pass

        self.speaking = False
        self.stop_listener_enabled = True

        # Greeting window: the boot moment. The first "hey JARVIS"
        # after startup earns the full briefing; later wakes within
        # the TTL get a brief "Yes, sir?" instead (see
        # _wakeup_greeting).
        self._last_activity = time.time()

    def clean_for_speech(self, text: str) -> str:
        # 1. Markdown links: keep visible text, drop the URL.
        text = re.sub(
            r"\[([^\]]+)\]\([^)]+\)",
            r"\1",
            text,
        )

        # 2. Bare URLs: describe them naturally, never spelled out.
        #    Known domains get friendly descriptions ("a YouTube
        #    video link"), everything else becomes "a website link".
        _link_names = {
            "youtube.com": "a YouTube video link",
            "youtu.be": "a YouTube video link",
            "github.com": "a GitHub repository link",
            "google.com": "a Google search link",
            "wikipedia.org": "a Wikipedia article link",
            "reddit.com": "a Reddit post link",
            "x.com": "a social media post link",
            "twitter.com": "a social media post link",
            "amazon.in": "a shopping page link",
            "amazon.com": "a shopping page link",
            "flipkart.com": "a shopping page link",
            "stackoverflow.com": "a Stack Overflow page link",
        }

        def _describe_url(match):
            url = match.group(0).lower()

            for domain, description in _link_names.items():
                if domain in url:
                    return description

            return "a website link"

        text = re.sub(r"https?://\S+", _describe_url, text)

        # 3. www domains with paths: same treatment.
        text = re.sub(
            r"\bwww\.\S+",
            _describe_url,
            text,
        )

        # 4. Windows paths (back- or forward-slash): never spoken.
        text = re.sub(
            r"\b[A-Za-z]:[\\/](?:[^\\/\s]+[\\/]?)+",
            "that file",
            text,
        )

        # 5. IP addresses: never read digit groups aloud.
        text = re.sub(
            r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
            "a local address",
            text,
        )

        # 6. Underscores inside names become spaces so "my_notes"
        #    is not glued into one unpronounceable blob.
        text = re.sub(r"_(?=[a-zA-Z0-9])", " ", text)

        # 7. SPEECH FLOW SMOOTHING: spoken text flows differently
        #    than written text. Heavy punctuation is lightened and
        #    filler/hesitation is removed so the voice glides.
        text = re.sub(
            r"\b(?:um+|uh+|uhm+|erm+|er+|hm+|hmm+|mm+)\b[,.]?",
            " ",
            text,
            flags=re.IGNORECASE,
        )

        # Ellipses / long dashes become commas (soft pause, no break).
        text = re.sub(r"\.{2,}|\u2026|\s--[\s]?|\s\u2014\s", ", ", text)

        # Multiple exclamations/questions collapse to one.
        text = re.sub(r"!{2,}", "!", text)
        text = re.sub(r"\?{2,}", "?", text)

        # Parenthetical asides keep the words, drop the brackets.
        text = re.sub(r"[\(\)]", " ", text)

        # Remove Markdown formatting markers
        text = re.sub(r"[*~`]+", "", text)

        # Remove emojis and other Unicode symbols
        text = re.sub(
            r"[\U0001F300-\U0001FAFF"
            r"\U00002700-\U000027BF"
            r"\U000024C2-\U0001F251]+",
            "",
            text,
        )

        # Remove Markdown headings
        text = re.sub(r"^\s*#+\s*", "", text, flags=re.MULTILINE)

        # List rows: convert bullets/numbered markers to commas so
        # spoken choices ("1. Physics notes / 2. Chemistry notes")
        # read as a natural list instead of colliding words.
        text = re.sub(
            r"^\s*[-•]\s*",
            ", ",
            text,
            flags=re.MULTILINE,
        )

        text = re.sub(
            r"^\s*\d+[.)]\s*",
            ", ",
            text,
            flags=re.MULTILINE,
        )

        # Remove blockquote markers
        text = re.sub(r"^\s*>\s*", "", text, flags=re.MULTILINE)

        # 7. Special characters that TTS reads aloud as garbage
        #    ("at the rate", "hash", "caret"...). Keep sentence
        #    punctuation, percent, currency and plain ampersand.
        text = re.sub(
            r"[\^~|{}<>\[\]=+;@#`]",
            " ",
            text,
        )

        # Collapse excessive whitespace
        text = re.sub(r"\s+", " ", text)

        # Punctuation spacing polish after list conversion.
        text = re.sub(r"\s+([,.!?;:])", r"\1", text)
        text = re.sub(r",\s*,+", ",", text)
        text = re.sub(r"([?.!])\s*,\s*", r"\1 ", text)
        text = text.strip(", ")

        return text.strip()

    def _emit_state(self, state: str):
        if self.on_state_change:
            try:
                self.on_state_change(state)
            except Exception:
                pass

    def _is_stop_request(self, text: str) -> bool:
        return bool(text and self.cancel_pattern.search(text))

    def interrupt_speech(self):
        """Cut off current speech from any thread (barge-in)."""

        self.text_to_speech.stop_speaking()

    def _announce_silent(self):
        """
        Last-resort path when speech synthesis fails: show the message
        on screen and log it, so JARVIS never dies mid-answer.
        """

        notice = (
            "My speech output failed just now, so I'll stay in text "
            "mode for this. I'm still here and listening."
        )

        print(notice)
        log_event("tts_failed")

        if self.on_jarvis_message:
            try:
                self.on_jarvis_message(notice)
            except Exception:
                pass

    def _start_stop_listener(self, armed=True):
        """
        Continuous barge-in listener for the WHOLE duration of speech:
        short mic bursts in a loop until the speech ends. The old
        single 2-second window meant a "stop" said 5 seconds into a
        20-second reply landed while NOBODY was listening.

        Interrupts on stop phrases AND on "hey jarvis" (which stops
        the speech and re-arms the exchange without another wake).

        "armed" is False when the response itself contains a stop
        word or its own name (e.g. "...just say 'Hey JARVIS'") so
        speaker echo cannot self-trigger the interruption.
        """

        if not self.stop_listener_enabled or not armed:
            return

        def watch():
            deadline = time.time() + 120  # bounded safety

            duck = getattr(self.text_to_speech, "duck_event", None)

            while self.speaking and time.time() < deadline:
                try:
                    # SHORT bursts (0.7 s): the user's "hey Jarvis" /
                    # "stop" must be caught fast, and ducking makes
                    # JARVIS's own voice stop masking the mic while
                    # the burst is judged.
                    audio = self.microphone.record_until_silence(
                        max_duration=0.7,
                        silence_duration=0.25,
                        threshold=0.05,
                        start_timeout=1.0,
                    )

                    if len(audio) == 0:
                        if duck is not None:
                            duck.clear()

                        continue

                    # DUCK NOW: something is happening in the room —
                    # drop JARVIS's volume while we decide whether it
                    # is a command (echo self-masking was the v3 bug:
                    # "hey Jarvis" while speaking did nothing).
                    if duck is not None:
                        duck.set()

                    text = self.speech_to_text.transcribe(audio)

                except Exception:
                    if duck is not None:
                        duck.clear()

                    continue

                finally:
                    if duck is not None:
                        duck.clear()

                if not self.speaking:
                    break

                print("BARGE-IN CHECK:", text)

                if not text or len(text.split()) > 4:
                    continue

                normalized = text.lower()

                if self._is_stop_request(normalized):
                    self.interrupt_speech()
                    return

                if (
                    "jarvis" in normalized
                    or "jamvis" in normalized
                    or "jarvis" in normalized.replace(" ", "")
                ):
                    # Wake phrase mid-speech: silence JARVIS and arm
                    # an immediate re-listen (no new wake word needed).
                    self.pending_wake_interrupt = True
                    self.interrupt_speech()
                    return

        Thread(target=watch, daemon=True).start()

    # ------------------------------------------------------
    # THE JUDGE (reflexes pack): a spoken answer that claims an
    # action ("I've sent it") must be backed by a tool receipt from
    # this turn. Pure code — no external model — so it can never
    # fail open or add latency beyond a regex pass.
    # ------------------------------------------------------

    _CLAIM_PATTERN = re.compile(
        r"\b(?:i(?:'ve| have|'d| had)?\s+(?:just\s+)?)?"
        r"(?:sent|called|booked|posted|paid|deleted|emailed|"
        r"transferred|messed|texted)\b",
        re.IGNORECASE,
    )

    def _judge_answer(self, question: str, answer: str) -> str:
        """
        Downgrade unverifiable action claims to honest phrasing.
        Returns the (possibly corrected) answer text.
        """

        if not answer:
            return answer

        # Scan the last tool receipt this turn.
        receipt = getattr(self.agent, "last_tool_receipt", None)

        if receipt:
            return answer

        if self._CLAIM_PATTERN.search(answer):
            # No receipt but the answer claims an action happened.
            # Replace the claim with the honest past/future form.
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
                r"\b(sent|booked|posted|deleted|emailed|texted)\b",
                "ready to go",
                corrected,
                flags=re.IGNORECASE,
            )

            log_event("judge_corrected", answer=answer[:120])

            return corrected

        return answer

    def _speak_until_done(self, text: str):
        """
        Speak a response; if the user interrupts with a stop phrase,
        the speech cuts off and JARVIS listens again.
        """

        if not text:
            return

        self.speaking = True

        # Echo guard: if the reply itself mentions the wake word (e.g.
        # "...just say 'Hey JARVIS'"), the speaker would arm the
        # wake-interrupt; strip the name before checking.
        echo_safe = "jarvis" not in text.lower()

        self._start_stop_listener(
            armed=(
                not self._is_stop_request(text)
                and echo_safe
            )
        )

        try:
            finished = self.text_to_speech.speak(text)

        except Exception as exc:
            print(f"TTS error: {exc}")
            self._announce_silent()
            return

        finally:
            self.speaking = False

        if not finished:
            print("Speech was interrupted by the user.")
            log_event("speech_interrupted")

            # Interrupted by STOP (not wake): acknowledge so the user
            # knows JARVIS registered the barge-in instead of feeling
            # ignored. Wake interrupts arm a fresh listen instead.
            if not self.pending_wake_interrupt:
                try:
                    self.speak("Stopped, sir.")

                except Exception:
                    pass

    def speak(self, text: str):
        """Speak with interruption support and a safe failure path."""

        if not text:
            return

        self.speaking = True

        try:
            self.text_to_speech.speak(text)
        except Exception as exc:
            print(f"TTS error: {exc}")
            self._announce_silent()
        finally:
            self.speaking = False

    def process(self, user_input: str) -> str:
        self._emit_state("THINKING")

        # Fresh turn: the honesty judge only trusts receipts from
        # THIS turn's tool executions.
        self.agent.last_tool_receipt = None

        # Pending confirmations are handled inside the agent runtime.
        agent_result = self.agent.process(user_input, context=self._context())

        if isinstance(agent_result, dict) and agent_result.get("success"):
            result = agent_result["result"]

            # THE JUDGE: an action claim with no tool receipt gets
            # downgraded to honest phrasing before it is spoken.
            result = self._judge_answer(user_input, result)
        else:
            result = (
                agent_result.get("result", "I couldn't process that request.")
                if isinstance(agent_result, dict)
                else "I couldn't process that request."
            )

            self._emit_state("ERROR")

        if (
            isinstance(agent_result, dict)
            and agent_result.get("confirmation_required")
        ):
            self._emit_state("WAITING_FOR_CONFIRMATION")

        # Action recorder running: surface its state so the UI shows
        # JARVIS is watching (and follow-ups keep the mic live).
        if getattr(self.agent, "recorder", None) is not None and (
            self.agent.recorder.is_active()
            or self.agent._recorder_pending_save is not None
        ):
            self._emit_state("LISTENING")

        self._remember_turn(user_input, result)

        # v4: tell listen_and_process whether THIS utterance ended the
        # session (explicit goodbye / self shutdown-restart).
        self._session_end_requested = bool(
            isinstance(agent_result, dict)
            and (
                agent_result.get("go_to_sleep")
                or agent_result.get("self_shutdown")
                or agent_result.get("self_restart")
            )
        )

        if isinstance(agent_result, dict) and agent_result.get(
            "self_shutdown"
        ):
            self.pending_self_command = "shutdown"

        elif isinstance(agent_result, dict) and agent_result.get(
            "self_restart"
        ):
            self.pending_self_command = "restart"

        elif isinstance(agent_result, dict) and agent_result.get(
            "go_to_sleep"
        ):
            # Reset the greeting so the next 'Hey JARVIS' after sleep
            # gets a fresh acknowledgment instead of nothing.
            self.has_greeted = False

        self._emit_state("IDLE")

        return result

    # ------------------------------------------------------
    # CONVERSATION CONTEXT
    # ------------------------------------------------------

    def _context(self) -> str:
        """Render the last few turns as prompt context."""

        from app.config import get as get_setting

        turns = get_setting("agent", "context_turns") or 4

        return "\n".join(
            f"User: {user}\nJARVIS: {response}"
            for user, response in self.history[-turns:]
        )

    def _remember_turn(self, user_input: str, response: str):
        self.history.append((user_input, response))

        if len(self.history) > 20:
            self.history = self.history[-20:]

    def _proactive_note(self) -> str:
        """
        Proactive mode (config: agent.proactive_mode): surface one
        useful observation before the user asks — low battery, high
        CPU, very high RAM. Returned between exchanges so it never
        interrupts a task. Empty string = nothing worth saying.
        """

        from app.config import get as get_setting

        if not get_setting("agent", "proactive_mode"):
            return ""

        # At most once per 10 minutes.
        now = time.time()

        if now - getattr(self, "_last_proactive", 0) < 600:
            return ""

        try:
            import psutil

            battery = psutil.sensors_battery()

            if (
                battery is not None
                and not battery.power_plugged
                and battery.percent <= 15
            ):
                self._last_proactive = now

                return (
                    f"Pardon the intrusion, sir — battery's at "
                    f"{int(battery.percent)} percent. A charger "
                    "wouldn't go amiss."
                )

            cpu = psutil.cpu_percent(interval=0.5)

            if cpu >= 92:
                self._last_proactive = now

                return (
                    f"CPU is running at {cpu:.0f} percent, sir — "
                    "something's working rather hard. Shall I see "
                    "what?"
                )

        except Exception:
            pass

        return ""

    def listen(self) -> str:
        start = time.time()

        # Post-wake mute window: the tail of the spoken wake phrase is
        # still in the room when recording starts; without this pause
        # it gets recorded as an "utterance" and JARVIS starts
        # THINKING about a word of nothing.
        time.sleep(0.25)

        audio = self.microphone.record_until_silence(
            max_duration=10,
            silence_duration=0.8,
            threshold=0.03,
            start_timeout=5,
        )

        print(f"Recording time: {time.time() - start:.2f}s")

        if len(audio) == 0:
            return ""

        # SILENCE GUARD: peak loudness below the speech threshold
        # means the recorder caught room noise / a breath, not
        # speech. Skipping the transcription keeps a 1-2 second
        # silence from ever reaching the brain as a fake command.
        try:
            import numpy as _np

            peak = float(_np.max(_np.abs(audio)))

            if peak < 0.03:
                print(
                    "Silence/noise only (peak "
                    f"{peak:.4f}) — not thinking."
                )

                return ""

        except Exception:
            pass

        start = time.time()

        text = self.speech_to_text.transcribe(audio)

        print(f"Whisper time: {time.time() - start:.2f}s")
        print("YOU SAID:", text)

        if text and self.on_user_message:
            self.on_user_message(text)

        return text

    def listen_and_process(
        self,
        max_followups: int = 0,
        hold_seconds: float = 0.0,
    ) -> str:
        """
        ONE SESSION, many exchanges (v4).

        The session stays ACTIVE until an explicit dismissal, the
        idle timeout (session.idle_timeout_seconds, default 5 min)
        with NOTHING pending, or the user walks away mid-task (which
        only ends the hold when the mic times out and nothing is
        pending). max_followups/hold_seconds are accepted for
        backward compatibility but no longer cap anything.
        """

        self.session.activate()

        self._session_end_requested = False

        response = ""

        round_index = 0

        while True:
            self.session.set_substate("LISTENING")

            if round_index == 0:
                text = self.listen()

            else:
                # An expected answer ("yes", a contact pick, a skill
                # name) gets a patient mic; a conversational hold is
                # shorter — silence ends the ROUND, not the session.
                expecting = (
                    self.agent.confirmations.has_pending()
                    or getattr(self.agent, "_pending_send", None) is not None
                    or getattr(self.agent, "_recorder_pending_save", None)
                    is not None
                    or getattr(self.agent, "_teaching_pending_save", None)
                    is not None
                    or getattr(self.agent, "_pending_draft", None) is not None
                )

                text = self._listen_followup(
                    start_timeout=(
                        12 if expecting
                        else 30 if self.filming_mode
                        else 6
                    ),
                )

            round_index += 1

            if not text:
                # Silence in the hold. The session only truly ends
                # when nothing is pending (the busy_check would have
                # held the mic patient) AND the idle timeout has run;
                # otherwise we simply loop back to listening. To keep
                # the voice loop responsive we re-check: idle timeout
                # + nothing pending -> DORMANT.
                if (
                    not self.session.is_busy()
                    and self.session.idle_seconds()
                    >= self.session.idle_timeout_seconds
                ):
                    self._say_session_farewell()

                    break

                if round_index == 1:
                    # First listen found nothing (wake-word echo or
                    # silence): end the exchange politely.
                    break

                # Short silence mid-conversation: keep the session,
                # loop straight back to the mic.
                continue

            self.session.touch()

            # UTTERANCE GUARD: a wake-word echo, a cough, or a
            # transcribed breath must never reach the brain. Strip
            # the wake word; what remains must look like speech.
            core = re.sub(
                r"\b(?:hey\s+)?(?:jarvis|jamvis)\b",
                " ",
                text.strip(),
                flags=re.IGNORECASE,
            )

            core = core.strip(" ,.!?\n")

            if (
                len(core) < 3
                or not re.search(r"[a-z0-9]", core, re.IGNORECASE)
            ):
                print(
                    "Utterance below brain threshold — ignored: "
                    f"{text!r}"
                )

                return ""

            # Arm the interrupt watcher: while JARVIS thinks/acts, the
            # user can say "stop" (or "hey Jarvis") to cancel the task.
            self.interrupt_requested = False
            self.thinking_abort.clear()
            self._processing_done = False

            watcher = Thread(
                target=self._interrupt_watcher,
                daemon=True,
            )

            watcher.start()

            self.session.set_substate("THINKING")

            try:
                response = self.process(text)

            except InterruptedError:
                # "stop"/"hey Jarvis" landed while JARVIS was
                # thinking: the exchange is dead, the fallback line
                # must never be spoken. Acknowledge ONLY when the
                # interrupt came from the wake word, then listen
                # again immediately (pending_wake_interrupt makes the
                # next wake check a bypass).
                print("Thinking interrupted by the user.")

                log_event("thinking_interrupted")

                self.session.touch()

                if self.pending_wake_interrupt:
                    self.speak("Stopped, sir. Go ahead.")

                continue

            finally:
                self._processing_done = True

            if self.interrupt_requested:
                self.interrupt_requested = False

                print("Task interrupted by the user mid-processing.")

                log_event("task_interrupted")

                self.session.touch()

                if self.pending_wake_interrupt:
                    self.speak("Stopped, sir. Go ahead.")

                continue

            if self.on_jarvis_message:
                self.on_jarvis_message(response)

            # SPEAKING while the reply is spoken (the orb shows its
            # waveform state), then a brief DONE flash before the
            # follow-up hold.
            self._emit_state("SPEAKING")

            self.session.set_substate("SPEAKING")

            speech_text = self.clean_for_speech(response)

            start = time.time()

            self._speak_until_done(speech_text)

            print(f"TTS time: {time.time() - start:.2f}s")

            self._emit_state("DONE")

            # Let the checkmark flash read before the next state.
            time.sleep(0.9)

            # Proactive mode: surface one useful observation between
            # exchanges (never mid-task), then return to the hold.
            proactive = self._proactive_note()

            if proactive:
                if self.on_jarvis_message:
                    self.on_jarvis_message(proactive)

                self._speak_until_done(
                    self.clean_for_speech(proactive)
                )

            if self.pending_self_command:
                command = self.pending_self_command
                self.pending_self_command = None

                if command == "restart":
                    self.restart()
                else:
                    self.shutdown_now()

            # ------------------------------------------------
            # v4 SESSION RULE: the task ended; the conversation did
            # NOT. Keep holding unless the user explicitly said
            # goodbye (or shut JARVIS down/restarted him).
            # ------------------------------------------------
            if self._session_end_requested:
                self._session_end_requested = False

                self.session.end("dismissed")

                break

            self.session.touch()

        return response

    def _say_session_farewell(self):
        """
        Spoken once when the session drops to wake-word mode from the
        idle timeout — short, and never mid-task (the caller only
        reaches here when nothing is pending).
        """

        self.session.end("idle")

        self.has_greeted = False

        try:
            if self.on_jarvis_message:
                self.on_jarvis_message(
                    "I'll be here if you need me, sir."
                )

            self._speak_until_done(
                "I'll be here if you need me, sir."
            )

        except Exception:
            pass

    def _listen_followup(self, start_timeout: float = 6) -> str:
        """
        Short follow-up capture inside an open exchange: silence is
        normal here (the user simply has nothing to add), so a quiet
        mic ends the hold instead of being an error.
        """

        print("Awaiting follow-up...")

        audio = self.microphone.record_until_silence(
            max_duration=8,
            silence_duration=1.0,
            threshold=0.03,
            start_timeout=start_timeout,
        )

        if len(audio) == 0:
            return ""

        # Same silence guard as listen(): a breath or room noise in
        # the hold must never become a fake follow-up command.
        try:
            import numpy as _np

            peak = float(_np.max(_np.abs(audio)))

            if peak < 0.03:
                print(
                    "Follow-up window: silence/noise only (peak "
                    f"{peak:.4f})."
                )

                return ""

        except Exception:
            pass

        text = self.speech_to_text.transcribe(audio)

        print("FOLLOW-UP:", text)

        if text and self.on_user_message:
            self.on_user_message(text)

        return text

    def _interrupt_watcher(self):
        """
        While JARVIS is busy (thinking/executing), listen in short
        bursts for a stop phrase or the wake word. On detection, set
        the interrupt flag (checked at tool boundaries) and cut speech.
        """

        while not self._processing_done:
            try:
                audio = self.microphone.record_until_silence(
                    max_duration=1.2,
                    silence_duration=0.35,
                    threshold=0.05,
                    start_timeout=1.0,
                )

                if len(audio) == 0:
                    continue

                text = self.speech_to_text.transcribe(audio)

            except Exception:
                continue

            if not text:
                continue

            print("INTERRUPT CHECK:", text)

            normalized = text.lower()

            if (
                self.cancel_pattern.search(normalized)
                or "jarvis" in normalized
                or "jamvis" in normalized
            ):
                self.interrupt_requested = True

                # Kill the in-flight reasoning call immediately.
                try:
                    self.thinking_abort.set()
                except Exception:
                    pass

                # Wake-word interrupt: the next wake check must be
                # bypassed so "hey jarvis" + command works in one go.
                if "jarvis" in normalized or "jamvis" in normalized:
                    self.pending_wake_interrupt = True

                self.interrupt_speech()
                return

    # ------------------------------------------------------
    # SELF LIFECYCLE: SHUTDOWN / RESTART
    # ------------------------------------------------------

    def restart(self) -> bool:
        """
        Spawn a fresh detached JARVIS instance, then exit this one.
        The single-instance guard port is released BEFORE the new
        process starts so it can bind it. The fresh instance greets
        with "I've restarted myself" (marker file).
        """

        log_event("restart_requested")

        self._emit_state("SHUTTING_DOWN")

        print("JARVIS is restarting itself...")

        try:
            os.makedirs(os.path.dirname(_RESTART_FLAG), exist_ok=True)

            with open(_RESTART_FLAG, "w", encoding="utf-8") as file:
                file.write("restart pending\n")

        except OSError:
            pass

        pythonw = sys.executable.replace("python.exe", "pythonw.exe")

        if not os.path.exists(pythonw):
            pythonw = sys.executable

        main_py = os.path.join(ROOT, "app", "main.py")

        # Release the guard port so the new instance can bind it.
        try:
            from app.main import release_instance_guard

            release_instance_guard()

        except Exception:
            pass

        time.sleep(0.3)

        try:
            # DETACHED_PROCESS: survives the death of this process.
            subprocess.Popen(
                [pythonw, main_py],
                cwd=ROOT,
                creationflags=0x00000008,
                close_fds=True,
            )

        except OSError as exc:
            print(f"Restart spawn failed: {exc}")
            log_event("restart_spawn_failed", error=str(exc))

            try:
                os.remove(_RESTART_FLAG)
            except OSError:
                pass

            return False

        self.shutdown_now()

        return True

    def shutdown_now(self):
        """Exit the whole JARVIS process (window, tray, listener)."""

        log_event("shutdown")

        print("JARVIS is shutting down.")

        self._emit_state("SHUTTING_DOWN")

        # Quit the Qt event loop from the GUI thread itself (QUIT_APP
        # is handled via the state signal). Hard-exiting from THIS
        # listener thread while the GUI sits in a Win32 call is what
        # made Windows show "Not Responding" on restart.
        app = QApplication.instance()

        if app is not None:
            self._emit_state("QUIT_APP")

            # Give the GUI thread time to hide the tray and unwind.
            time.sleep(1.2)

        # Fallback: hard exit even without a Qt event loop.
        os._exit(0)

    def request_shutdown(self):
        """Tray/menu quit path: stop speech and exit immediately."""

        log_event("shutdown")

        self.interrupt_speech()

        self.shutdown_now()

    # ------------------------------------------------------
    # FILMING MODE (reflexes pack): "we're filming" disables the
    # wake word; JARVIS answers only clearly-addressed commands.
    # Hard code rule, never model-dependent.
    # ------------------------------------------------------

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

    def wait_for_wake_word(self, cooldown: float = 0.0):
        # A "hey jarvis" spoken DURING speech/thinking already armed
        # the exchange: skip the detector and cooldown entirely and
        # drop straight into listening — the user should never have
        # to say the wake word twice.
        if self.pending_wake_interrupt:
            self.pending_wake_interrupt = False

            return True

        detected = self.wake_word.listen(cooldown=cooldown)

        # Sync the toggle the agent may have flipped this turn.
        self.filming_mode = getattr(self.agent, "_filming_mode", False)

        if self.filming_mode:
            # Wake word is off. The detector's transcript is checked
            # for a direct address instead: speaking to JARVIS (his
            # name, a question aimed at him) still wakes him; camera
            # narration does not.
            addressed = self.wake_word.last_transcript

            if addressed and (
                "jarvis" in addressed.lower()
                or "jamvis" in addressed.lower()
                or addressed.strip().endswith("?")
                or re.match(
                    r"\b(?:hey|ok|okay|so|what|how|when|who|jarvis)\b",
                    addressed.strip(),
                    re.IGNORECASE,
                )
            ):
                detected = True

            else:
                detected = False

        if detected:
            # v4 DEBOUNCE: a trigger inside the refractory window is
            # the detector re-firing on the tail of the same word (or
            # JARVIS's own reply) — never a real second "hey JARVIS".
            now = time.time()

            if now - self._last_wake_handled < self._wake_refractory:
                print("Wake refractory: ignoring echo trigger.")

                return False

            self._last_wake_handled = now

            self.session.activate()

            # Wake immediately (orb switches to LISTENING as soon as
            # this returns, before the greeting) — see app/main.py.
            greeting = self._wakeup_greeting()

            if greeting:
                if self.on_jarvis_message:
                    self.on_jarvis_message(greeting)

                # Barge-in: a wake word during speech also silences it.
                self.interrupt_speech()
                self._speak_until_done(greeting)

            elif self.wake_chime:
                # v4: a short non-verbal chime acknowledges the wake
                # without adding another spoken greeting — the orb
                # lights up, the chime plays, JARVIS listens.
                if self.on_jarvis_message:
                    self.on_jarvis_message("Yes, sir?")

                self.interrupt_speech()
                self._play_chime()

            else:
                # Brief acknowledgment so JARVIS never seems deaf, but
                # no repetition of the greeting: a two-word "Yes, sir?"
                # keeps the exchange moving.
                if self.on_jarvis_message:
                    self.on_jarvis_message("Yes, sir?")

                self.interrupt_speech()
                self._speak_until_done("Yes, sir?")

        return detected

    def _play_chime(self):
        """
        Two-note acknowledgment chime (~0.3 s). Cosmetic only: if the
        audio device refuses, silence is the correct fallback.
        """

        try:
            import numpy as _np
            import sounddevice as _sd

            rate = 44100

            duration = 0.28

            t = _np.linspace(0, duration, int(rate * duration), False)

            # E6 -> A6, two quick soft notes.
            wave = _np.zeros_like(t)

            split = int(len(t) * 0.55)

            wave[:split] = 0.20 * _np.sin(
                2 * _np.pi * 1318.5 * t[:split]
            )

            wave[split:] = 0.20 * _np.sin(
                2 * _np.pi * 1760.0 * t[split:]
            )

            # Fade edges so the chime never clicks.
            fade = int(rate * 0.01)

            wave[:fade] *= _np.linspace(0, 1, fade)

            wave[-fade:] *= _np.linspace(1, 0, fade)

            audio = (wave * 32767).astype(_np.int16)

            stream = _sd.OutputStream(
                samplerate=rate,
                channels=1,
                dtype="int16",
            )

            stream.start()
            stream.write(audio)
            stream.stop()
            stream.close()

        except Exception:
            pass

    # A long briefing is welcome ONCE per boot (or after 4+ hours of
    # idle — a fresh day). After that, every wake gets a chime: the
    # user said "hey JARVIS" to give a command, not to hear a speech.
    _GREETING_TTL_SECONDS = 4 * 3600.0

    def _daily_briefing(self) -> str:
        """
        Morning-briefing greeting, JARVIS-style: the first wake of the
        session opens with time, battery, and any reminder due —
        delivered like a butler, not a status dump.
        Failures degrade to a plain "Yes, sir?" silently.
        """

        from datetime import datetime

        now = datetime.now()

        hour = now.hour

        if 5 <= hour < 12:
            opening = "Good morning, sir."

        elif 12 <= hour < 17:
            opening = "Good afternoon, sir."

        elif 17 <= hour < 22:
            opening = "Good evening, sir."

        else:
            opening = "Working late, sir?"

        pieces = [opening]

        # Time.
        time_str = now.strftime("%I:%M %p").lstrip("0")

        pieces.append(f"It's {time_str}.")

        # Battery (never blocks the greeting).
        try:
            import psutil

            battery = psutil.sensors_battery()

            if battery is not None:
                percent = int(battery.percent)

                if battery.power_plugged:
                    pieces.append(
                        f"Battery's at {percent} percent and charging."
                    )

                elif percent <= 20:
                    pieces.append(
                        f"Battery's at {percent} percent — I'd find a "
                        "charger soon, sir."
                    )

                else:
                    pieces.append(
                        f"Battery's at {percent} percent."
                    )

        except Exception:
            pass

        # Memory size — the pack's "N notes indexed, all present and
        # accounted for" flavor.
        try:
            fact_count = len(self.agent.tools.memory.all_facts())

            if fact_count:
                pieces.append(
                    f"{fact_count} fact{'s' if fact_count != 1 else ''} "
                    "in memory, all present and accounted for."
                )

        except Exception:
            pass

        # "What needs me" — pending reminders plus anything urgent in
        # the activity log (tool failures worth mentioning).
        try:
            needs = []

            pending = self.agent.tools.reminders.pending()

            if pending:
                needs.append(
                    f"a reminder pending: '{pending[0].get('text', '')}'"
                )

            drafts = getattr(self.agent, "_pending_draft", None)

            if drafts:
                needs.append("a draft waiting for your go-ahead")

            if needs:
                pieces.append(
                    "Needs your attention: " + "; ".join(needs) + "."
                )

        except Exception:
            pass

        # The next reminder due within 12 hours.
        try:
            pending = self.agent.tools.reminders.pending()

            if pending:
                first = pending[0]

                due_text = ""

                try:
                    from datetime import datetime as _dt

                    due = _dt.fromisoformat(
                        str(first.get("due", ""))
                    )

                    today = now.date()

                    if due.date() == today:
                        due_text = due.strftime("today at %I:%M %p")
                        due_text = due_text.replace(" 0", " ")

                    elif due.date() == (
                        now.fromtimestamp(
                            now.timestamp() + 86400
                        ).date()
                    ):
                        due_text = due.strftime("tomorrow at %I:%M %p")
                        due_text = due_text.replace(" 0", " ")

                    else:
                        due_text = due.strftime("%B %d at %I:%M %p")
                        due_text = due_text.replace(" 0", " ").replace(
                            " 0", " ", 1
                        )

                except Exception:
                    due_text = ""

                reminder_bit = (
                    f" coming up {due_text}"
                    if due_text
                    else " coming up"
                )

                pieces.append(
                    f"You have '{first.get('text', 'a reminder')}'"
                    f"{reminder_bit}."
                )

        except Exception:
            pass

        return " ".join(pieces) + " How can I help?"

    def _wakeup_greeting(self):
        """
        v3 greeting rules (user request: no long greeting on every
        wake):

        - A self-restart is acknowledged exactly once.
        - The FULL briefing is spoken once per session, and only if
          this wake is the "greeting window" (first wake after boot,
          or after an explicit go-to-sleep) AND nothing has been
          said for at least GREETING_TTL_SECONDS.
        - Every other wake gets NO greeting here; wait_for_wake_word
          answers with a two-word "Yes, sir?" instead.
        """

        if self.restart_acknowledged:
            self.restart_acknowledged = False
            self._last_activity = time.time()

            return "I've restarted myself. All systems are back online, sir."

        # Explicit sleep resets the greeting flag; honor it only when
        # the user has actually been away a while.
        if self.has_greeted:
            idle = time.time() - getattr(self, "_last_activity", 0.0)

            if idle < self._GREETING_TTL_SECONDS:
                return None

            self.has_greeted = False

        # The briefing only deserves its slot when the user has been
        # away: right after a restart acknowledgment (fresh boot) or
        # a long silence. A rapid second "hey JARVIS" gets nothing.
        idle = time.time() - getattr(self, "_last_activity", 0.0)

        if 0 < idle < self._GREETING_TTL_SECONDS:
            self.has_greeted = True
            self._last_activity = time.time()

            return None

        self.has_greeted = True
        self._last_activity = time.time()

        return self._daily_briefing()


if __name__ == "__main__":
    orchestrator = Orchestrator()

    print("JARVIS is ready.")

    while True:
        print("\nJARVIS is waiting...")

        if orchestrator.wait_for_wake_word():
            print("JARVIS IS AWAKE!")

            response = orchestrator.listen_and_process()

            if response:
                print("JARVIS:", response)