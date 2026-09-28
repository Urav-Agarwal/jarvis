"""
Kill switch: one switch to halt EVERYTHING JARVIS is doing.

Triggered by:
  - the global hotkey Ctrl+Alt+Shift+J (registered via the `keyboard`
    library; silently unavailable if the OS refuses the hook)
  - the voice phrase "Jarvis, emergency stop" / "emergency stop"

On trigger:
  - the abort Event is set -> mouse glides/clicks/drag in flight bail
    out, the LLM provider poll aborts the in-flight call
  - every registered callback runs (orchestrator: cut speech, clear
    runtime state, cancel confirmations and the recorder)
  - the Event is auto-cleared after a short grace period so normal
    operation can resume without a restart
"""

import re
import threading
import time


class KillSwitch:
    def __init__(self, grace_seconds: float = 1.5):
        self.abort_event = threading.Event()
        self.grace_seconds = float(grace_seconds)
        self._callbacks = []
        self._last_triggered = 0.0
        self._lock = threading.Lock()

    # ----------------------------------------------------------
    # CALLBACKS
    # ----------------------------------------------------------

    def on_trigger(self, callback):
        """Register callback() run on every trigger (never raises)."""

        with self._lock:
            self._callbacks.append(callback)

    # ----------------------------------------------------------
    # TRIGGER
    # ----------------------------------------------------------

    def trigger(self, reason: str = "manual"):
        with self._lock:
            callbacks = list(self._callbacks)

        self.abort_event.set()

        self._last_triggered = time.time()

        for callback in callbacks:
            try:
                callback(reason)

            except Exception:
                pass

        # Auto-release so the next task is not strangled by a stale
        # abort flag.
        timer = threading.Timer(
            self.grace_seconds,
            self.abort_event.clear,
        )

        timer.daemon = True

        timer.start()

    def is_active(self) -> bool:
        return self.abort_event.is_set()

    # ----------------------------------------------------------
    # GLOBAL HOTKEY
    # ----------------------------------------------------------

    def install_hotkey(self, combination: str = "ctrl+alt+shift+j"):
        """
        Best effort: returns True when the OS accepted the hook.
        Must run in the main process; never raises.
        """

        try:
            import keyboard

            keyboard.add_hotkey(
                combination,
                lambda: self.trigger("hotkey"),
                suppress=False,
            )

            return True

        except Exception:
            return False


_DEFAULT = None


def get_kill_switch() -> KillSwitch:
    global _DEFAULT

    if _DEFAULT is None:
        _DEFAULT = KillSwitch()

    return _DEFAULT


# Voice-phrase pattern shared with the reflex layer.
EMERGENCY_PATTERN = re.compile(
    r"\bemergency\s+stop\b|\bstop\s+everything\b"
    r"|\babort\s+(?:all\s+)?(?:tasks|everything)\b"
    r"|\bkill\s+switch\b",
    re.IGNORECASE,
)
