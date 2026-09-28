"""
Conversation Session state machine (v4 Phase 1).

    DORMANT -> ACTIVE -> (LISTENING | THINKING | ACTING | SPEAKING)
            -> ACTIVE ... -> DORMANT

Rules (from the v4 master brief):

- A task ENDS when complete, but the CONVERSATION does not. JARVIS
  stays ACTIVE for follow-ups without the wake word.
- ACTIVE persists until: an explicit dismissal ("that's all", "go to
  sleep", "bye"), OR the idle timeout (default 5 minutes from
  config/settings.yaml: session.idle_timeout_seconds).
- NEVER sleeps while: a task is running, a confirmation/draft/contact
  pick/teaching save is pending, or speech is mid-flight.
- No maximum number of exchanges (the v3 four-exchange cap and the
  6-second follow-up drop are gone).
"""

import os
import time
from datetime import datetime


# Session transition audit: data/logs/session.log. Every state change
# lands here with a timestamp and reason so "why did he sleep" is
# always answerable from evidence (v4.1 Session A2).
_LOG_PATH = os.path.join("data", "logs", "session.log")


def _log_transition(old, new, reason):
    try:
        os.makedirs(os.path.dirname(_LOG_PATH), exist_ok=True)

        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with open(_LOG_PATH, "a", encoding="utf-8") as handle:
            handle.write(
                f"{stamp} {old} -> {new} ({reason})\n"
            )

    except Exception:
        pass


class SessionState:
    DORMANT = "DORMANT"
    ACTIVE = "ACTIVE"
    LISTENING = "LISTENING"
    THINKING = "THINKING"
    ACTING = "ACTING"
    SPEAKING = "SPEAKING"


# Substates that count as "inside an active exchange".
_SUBSTATES = {
    SessionState.LISTENING,
    SessionState.THINKING,
    SessionState.ACTING,
    SessionState.SPEAKING,
}


class ConversationSession:
    def __init__(
        self,
        idle_timeout_seconds: float = 300.0,
        busy_check=None,
    ):
        """
        busy_check: optional callable -> bool. True means "something
        is pending/running" (confirmations, drafts, a live task) and
        blocks the idle sleep no matter how long the silence.
        """

        self.idle_timeout_seconds = max(30.0, float(idle_timeout_seconds))
        self.busy_check = busy_check

        self.state = SessionState.DORMANT

        self._last_activity = time.time()

        self._running_tasks = 0

        self._end_reason = None

    # ----------------------------------------------------------
    # LIFECYCLE
    # ----------------------------------------------------------

    def activate(self, reason: str = "wake"):
        """DORMANT -> ACTIVE (a wake word or a direct command)."""

        if self.state == SessionState.DORMANT:
            _log_transition("DORMANT", "ACTIVE", reason)

            self.state = SessionState.ACTIVE

        self._end_reason = None

        self.touch()

    def touch(self):
        """Any user activity refreshes the idle clock."""

        self._last_activity = time.time()

    def set_substate(self, substate: str):
        """
        Track what JARVIS is doing inside the ACTIVE session
        (LISTENING / THINKING / ACTING / SPEAKING).
        """

        if substate in _SUBSTATES and self.state != SessionState.DORMANT:
            if self.state != substate:
                _log_transition(self.state, substate, "activity")

            self.state = substate

        elif substate == SessionState.ACTIVE:
            if self.state != SessionState.ACTIVE:
                _log_transition(self.state, "ACTIVE", "activity")

            self.state = SessionState.ACTIVE

        self.touch()

    def end(self, reason: str = "dismissed"):
        """Explicit end: goodbye, emergency stop, self-shutdown."""

        if self.state != SessionState.DORMANT:
            _log_transition(
                self.state,
                "DORMANT",
                f"{reason} (idle {self.idle_seconds():.0f}s, "
                f"busy={self.is_busy()})",
            )

        self.state = SessionState.DORMANT

        self._end_reason = reason

        self._running_tasks = 0

    # ----------------------------------------------------------
    # TASK TRACKING
    # ----------------------------------------------------------

    def begin_task(self):
        self._running_tasks += 1

        self.touch()

    def end_task(self):
        self._running_tasks = max(0, self._running_tasks - 1)

        self.touch()

    # ----------------------------------------------------------
    # QUERIES
    # ----------------------------------------------------------

    def idle_seconds(self) -> float:
        return time.time() - self._last_activity

    def is_busy(self) -> bool:
        if self._running_tasks > 0:
            return True

        if self.busy_check is not None:
            try:
                return bool(self.busy_check())

            except Exception:
                return True  # fail SAFE: never sleep mid-anything

        return False

    def should_sleep(self) -> bool:
        """
        True only when: ACTIVE (or a substate), silence has exceeded
        the timeout, and nothing is pending or running.
        """

        if self.state == SessionState.DORMANT:
            return False

        if self.is_busy():
            return False

        return self.idle_seconds() >= self.idle_timeout_seconds

    def should_hold(self) -> bool:
        """
        Keep the follow-up mic open: ACTIVE session, not dismissed,
        nothing pending that WE must answer, and the idle timeout has
        not elapsed. (Pending confirmations keep the hold alive via
        busy_check in the caller's listen loop — silence while a
        confirmation pends is handled by its own longer timeout.)
        """

        if self.state == SessionState.DORMANT:
            return False

        if self._end_reason:
            return False

        return self.idle_seconds() < self.idle_timeout_seconds

    def end_reason(self):
        return self._end_reason
