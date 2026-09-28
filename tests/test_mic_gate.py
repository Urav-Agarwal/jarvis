"""
v4.1.2 MIC GATE + WAKE FLOW regression tests (synthetic audio):

- noisy room + short phrase: recording ends ~silence_duration after
  the phrase (never runs to max_duration)
- phrase followed by silence: same
- noise-only room: nothing captured, no false speech
- a strong mic (raw peaks 0.2-0.3) is NOT normalized (no pointless
  gain) while a quiet capture still gets a gentle boost
- wake AGC: room noise is never amplified towards the speech target
  (gain stays 1.0 below the speech floor)
- chime-only wake: wait_for_wake_word never SPEAKS "Yes, sir?" and
  never greets inside an active session

Run with:
    PYTHONIOENCODING=utf-8 python -m tests.test_mic_gate
"""

import os
import sys
import time
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from audio.microphone import Microphone
from audio.wake_word import WakeWordDetector

failures = 0


def check(name, condition, detail=""):
    global failures

    if condition:
        print(f"[PASS] {name}")
    else:
        failures += 1
        print(f"[FAIL] {name} {detail}")


class FakeStream:
    """Feeds pre-rendered frames through the Microphone InputStream."""

    def __init__(self, frames):
        self.frames = frames
        self.i = 0

    def read(self, n):
        frame = (
            self.frames[self.i]
            if self.i < len(self.frames)
            else np.zeros(n, dtype="float32")
        )

        self.i += 1

        return frame.reshape(-1, 1), None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def render(noise_amp, speech_frames, sr=16000):
    """
    frames: list of (kind, value). kind 'n' = noise chunk at noise_amp,
    's' = speech chunk at value amplitude.
    """
    frames = []

    for kind, value in speech_frames:
        if kind == "n":
            frames.append(
                (np.random.rand(sr // 10) * 2 - 1) * noise_amp
            )

        else:
            # Speech-ish: sine burst at the given peak amplitude.
            t = np.linspace(0, 0.1, sr // 10, False)

            frames.append(
                (np.sin(2 * np.pi * 220 * t) * value).astype("float32")
            )

    return [f.astype("float32") for f in frames]


def run_mic(frames, **kwargs):
    mic = Microphone()

    with patch(
        "audio.microphone.sd.InputStream",
        return_value=FakeStream(frames),
    ):
        started = time.time()

        audio = mic.record_until_silence(
            max_duration=kwargs.pop("max_duration", 10),
            silence_duration=kwargs.pop("silence_duration", 0.7),
            threshold=kwargs.pop("threshold", 0.03),
            start_timeout=kwargs.pop("start_timeout", 5),
        )

        elapsed = time.time() - started

    return audio, elapsed


# ============================================================
# 1. NOISY ROOM + SHORT PHRASE -> ends soon after the phrase
# ============================================================

# Room noise RMS ~0.008; speech chunks peak 0.25 (the user's current
# mic: raw peaks 0.2-0.3).
noise = 0.008

frames = render(noise, [("n", 0)] * 5)          # 0.5 s of room tone

frames += render(noise, [("s", 0.25)] * 6)      # 0.6 s phrase

frames += render(noise, [("n", 0)] * 30)        # 3 s silence after

audio, elapsed = run_mic(frames, max_duration=10)

captured_s = len(audio) / 16000

check(
    "gate: phrase captured from a noisy room",
    captured_s > 0.3,
    f"captured={captured_s:.2f}s",
)

check(
    "gate: ends ~1s after the phrase, not at max_duration",
    elapsed < 2.5,
    f"elapsed={elapsed:.2f}s (max_duration was 10)",
)

check(
    "gate: strong capture NOT normalized",
    float(np.max(np.abs(audio))) > 0.15,
    f"peak={float(np.max(np.abs(audio))):.3f}",
)

# ============================================================
# 2. PHRASE THEN SILENCE must not run to max_duration
# ============================================================

frames = render(0.003, [("n", 0)] * 5)
frames += render(0.003, [("s", 0.2)] * 8)
frames += render(0.003, [("n", 0)] * 40)

audio, elapsed = run_mic(frames, max_duration=10)

check(
    "gate: trailing silence ends the capture (< 3 s)",
    0 < len(audio) and elapsed < 3.0,
    f"elapsed={elapsed:.2f}s",
)

# ============================================================
# 3. NOISE-ONLY room: nothing captured
# ============================================================

frames = render(0.006, [("n", 0)] * 40)  # 4 s pure room noise

audio, elapsed = run_mic(frames, max_duration=4)

check(
    "gate: noise-only room captures nothing",
    len(audio) == 0,
    f"captured={len(audio)} samples",
)

# ============================================================
# 4. QUIET mic still works (the previous 100x-quieter mic)
# ============================================================

frames = render(0.0004, [("n", 0)] * 5)
frames += render(0.0004, [("s", 0.02)] * 8)
frames += render(0.0004, [("n", 0)] * 30)

audio, elapsed = run_mic(frames, max_duration=10)

peak = float(np.max(np.abs(audio))) if len(audio) else 0.0

check(
    "gate: quiet-mic phrase still captured",
    captured_s := len(audio) / 16000 > 0.3,
    f"captured={len(audio) / 16000:.2f}s",
)

check(
    "gate: quiet capture IS normalized for STT",
    0.1 <= peak <= 1.0,
    f"peak={peak:.3f}",
)

# ============================================================
# 5. WAKE AGC: room noise is NOT amplified into speech range
# ============================================================

detector = WakeWordDetector()

quiet_frame = (
    (np.random.rand(1280) * 2 - 1) * 0.006 * 32767
).astype(np.int16)

out = detector._agc(quiet_frame)

out_rms = float(np.sqrt(np.mean(out.astype(np.float64) ** 2))) / 32767

check(
    "wake AGC: gain stays 1.0 on room noise (no noise amplification)",
    detector.last_gain == 1.0 and out_rms < 0.02,
    f"gain={detector.last_gain} out_rms={out_rms:.4f}",
)

speech_frame = (
    (np.sin(np.linspace(0, 100, 1280)) * 0.2 * 32767)
).astype(np.int16)

out2 = detector._agc(speech_frame)

check(
    "wake AGC: speech on a strong mic passes ~untouched (gain <= 2)",
    detector.last_gain <= 2.0,
    f"gain={detector.last_gain}",
)

# ============================================================
# 6. CHIME-ONLY WAKE: no spoken "Yes, sir?" on wake
# ============================================================

from threading import Event

from assistant.orchestrator import Orchestrator
from assistant.session import ConversationSession, SessionState
from security.kill_switch import KillSwitch

orch = Orchestrator.__new__(Orchestrator)

orch.pending_wake_interrupt = False
orch.wake_chime = True
orch.wake_cooldown = 0.0
orch.filming_mode = False
orch.has_greeted = True
orch.restart_acknowledged = False
orch._last_activity = time.time()
orch._last_wake_handled = 0.0
orch._wake_refractory = 1.2
orch.speaking = False
orch.on_jarvis_message = None
orch.on_user_message = None
orch.kill_switch = KillSwitch()
orch.thinking_abort = Event()
orch.session = ConversationSession(idle_timeout_seconds=60)


class _Agent:
    _filming_mode = False


orch.agent = _Agent()

spoken = []
chimes = []

orch._play_chime = lambda: chimes.append(1)
orch._speak_until_done = lambda text: spoken.append(text)
orch._wakeup_greeting = lambda: None
orch.interrupt_speech = lambda: None
orch._emit_state = lambda state: None


class _Detector:
    def __init__(self, fire):
        self.fire = fire
        self.last_transcript = ""

    def listen(self, cooldown=0.0):
        return self.fire


orch.wake_word = _Detector(fire=True)

orch.wait_for_wake_word(cooldown=0)

check(
    "wake: chime plays, nothing is spoken",
    len(chimes) == 1 and not spoken,
    f"chimes={chimes} spoken={spoken}",
)

# Active session: a second wake NEVER greets (chime only again).
orch._last_wake_handled -= 5

orch.session.activate()

orch.wait_for_wake_word(cooldown=0)

check(
    "wake: active session re-wake is chime-only (no greeting)",
    len(chimes) == 2 and not spoken,
    f"chimes={chimes} spoken={spoken}",
)

# Wake while SPEAKING is ignored entirely.
orch._last_wake_handled -= 5

orch.speaking = True

woke = orch.wait_for_wake_word(cooldown=0)

orch.speaking = False

check(
    "wake: ignored while JARVIS is speaking",
    woke is False and len(chimes) == 2,
    f"woke={woke} chimes={chimes}",
)

print()

if failures:
    print(f"FAILED: {failures} check(s)")
    sys.exit(1)

print("ALL MIC-GATE TESTS PASSED")
sys.exit(0)
