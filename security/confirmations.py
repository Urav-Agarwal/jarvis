"""
ConfirmationManager v4 (upgrade of the v3 single-slot manager).

Contracts (tested in tests/test_phase0.py):

- EXPIRY: a pending action expires after 30 seconds (configurable);
  an expired confirmation is dropped and must NEVER execute.
- QUEUE: several gated actions may stack; each "yes" executes the
  OLDEST pending action (fairness), each "no"/"cancel" clears it.
- STRICT YES: only whole-utterance clear phrases confirm ("yes",
  "yes do it", "go ahead", "confirm"). Sentences that merely start
  with "ok" / "sure" / "right" do NOT confirm anything.
- STRICT NO: any clear no ("no", "cancel", "don't", "stop",
  "nevermind") cancels the oldest pending action.
- READ-BACK: the confirmation question names the tool, recipient /
  path etc., so the user always knows exactly what a "yes" will do.
"""

import re
import time


DEFAULT_EXPIRY_SECONDS = 30.0


_YES_PATTERN = re.compile(
    r"^\s*(?:hey\s+)?(?:jarvis|jamvis)?[\s,]*"
    r"(?:yes|yep|yeah|yup|sure thing|do it|go ahead|"
    r"please do|confirm|affirmative|ok do it|okay do it|go on)\b"
    r"(?:[\s,]+(?:do|it|please|sir|go|on|ahead|now|then|"
    r"thanks|thank|you|jarvis|jamvis|ok|okay|yes|indeed))*"
    r"[^a-z]*\s*$",
    re.IGNORECASE,
)

_NO_PATTERN = re.compile(
    r"\b(?:no|nope|cancel|stop|don'?t|do not|nevermind|"
    r"never mind|forget it|abort)\b",
    re.IGNORECASE,
)


def is_clear_yes(text: str) -> bool:
    return bool(_YES_PATTERN.match((text or "").strip()))


def is_clear_no(text: str) -> bool:
    text = (text or "").strip()

    if is_clear_yes(text):
        return False

    return bool(_NO_PATTERN.search(text))


class ConfirmationManager:
    def __init__(self, expiry_seconds: float = DEFAULT_EXPIRY_SECONDS):
        self.expiry_seconds = float(expiry_seconds)
        self._queue = []

    # ----------------------------------------------------------
    # QUEUE INTERNALS
    # ----------------------------------------------------------

    def _expire_stale(self):
        now = time.time()

        still_pending = []

        for action in self._queue:
            if now - action["requested_at"] > self.expiry_seconds:
                action["expired"] = True

            else:
                still_pending.append(action)

        self._queue = still_pending

    # ----------------------------------------------------------
    # PUBLIC API (superset of the v3 API — old callers keep working)
    # ----------------------------------------------------------

    def request_confirmation(
        self,
        tool_name: str,
        parameters: dict,
        description: str,
    ) -> str:
        """
        Queue one action and return the spoken read-back. The
        description MUST name the concrete target ("send 'see you
        tomorrow' to Vishwa") — the executor builds it.
        """

        self._expire_stale()

        self._queue.append(
            {
                "tool": tool_name,
                "parameters": parameters or {},
                "description": description,
                "requested_at": time.time(),
            }
        )

        oldest = self._queue[0]

        extra = ""

        if len(self._queue) > 1:
            extra = (
                f" ({len(self._queue) - 1} more waiting after that)"
            )

        return (
            f"Please confirm: {oldest['description']}.{extra}"
        )

    def has_pending(self) -> bool:
        self._expire_stale()

        return bool(self._queue)

    def get_pending(self):
        """Oldest pending action (v3 compat: returns dict or None)."""

        self._expire_stale()

        if not self._queue:
            return None

        return self._queue[0]

    def pending_count(self) -> int:
        self._expire_stale()

        return len(self._queue)

    def confirm(self) -> bool:
        """True when a clear yes can execute the oldest action now."""

        self._expire_stale()

        return bool(self._queue)

    def consume(self):
        """
        Pop and return the oldest pending action, or None.
        The executor executes immediately after consume().
        """

        self._expire_stale()

        if self._queue:
            return self._queue.pop(0)

        return None

    def cancel(self) -> int:
        """
        Clear the queue (v3 compat: clears everything). Returns how
        many actions were dropped.
        """

        dropped = len(self._queue)

        self._queue = []

        return dropped

    def cancel_oldest(self) -> bool:
        self._expire_stale()

        if self._queue:
            self._queue.pop(0)

            return True

        return False