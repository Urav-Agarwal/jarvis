"""
Wake doctor: what does the wake-word model actually HEAR?

Records 12 seconds from the configured mic and prints, per 100 ms
frame, a live level meter (raw RMS -> after AGC), the rolling wake
score, and a verdict. Say "Hey Jarvis" a few times at NORMAL volume
during the recording; the script reports the peak score per utterance
window so threshold tuning is evidence-based.

Run:
    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe scripts/wake_doctor.py
"""

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.chdir(Path(__file__).resolve().parents[1])

import numpy as np
import sounddevice as sd

from audio.wake_word import WakeWordDetector
from app.config import get as get_setting


def rms(audio):
    """RMS in FLOAT scale (0..1) so meters and thresholds agree with
    the detector's AGC (which targets a float-scale RMS)."""

    audio = np.asarray(audio, dtype=np.float64)

    if audio.size == 0:
        return 0.0

    return float(np.sqrt(np.mean(audio ** 2))) / 32767.0


def bar(level, width=40):
    filled = int(min(1.0, level) * width)

    return "|" + "#" * filled + "-" * (width - filled) + "|"


DURATION = 12.0

detector = WakeWordDetector()

rate = detector.sample_rate

chunk = detector.chunk_size

n_chunks = int(DURATION * rate / chunk)

print(f"\nRecording {DURATION:.0f}s — say 'Hey Jarvis' 2-3 times at "
      "NORMAL volume, ~1.5 m from the laptop.\n")

frames = []

raw_rms_values = []
gained_rms_values = []
scores = []

started = time.time()


def record_loop():
    global frames

    recorded = sd.rec(
        int(DURATION * rate),
        samplerate=rate,
        channels=1,
        dtype="int16",
        device=get_setting("audio", "input_device"),
    )

    sd.wait()

    return np.squeeze(recorded)


audio = record_loop()

# Sanity: a DC-offset or mirror device shows a huge idle RMS. Warn
# instead of reporting nonsense AGC numbers.
idle_probe = np.abs(audio[: rate // 4]).mean()

print("\nAnalysing...\n")

peak_score = 0.0

peak_score_window = 0.0

utterance_peaks = []

in_utterance = False

for index in range(0, len(audio) - chunk, chunk):
    frame = audio[index:index + chunk]

    raw = rms(frame)

    amplified = detector._agc(frame)

    gained = rms(amplified.astype(np.float64))

    prediction = detector.model.predict(amplified)

    score = prediction["hey_jarvis"]

    raw_rms_values.append(raw)
    gained_rms_values.append(gained)
    scores.append(score)

    peak_score = max(peak_score, score)

    # An "utterance" = any frame above a quiet-voice RMS floor; track
    # the peak score within each such window.
    if gained > 0.02:
        in_utterance = True

        peak_score_window = max(peak_score_window, score)

    elif in_utterance:
        in_utterance = False

        if peak_score_window > 0:
            utterance_peaks.append(peak_score_window)

        peak_score_window = 0.0

    # Live meter, printed every 10 frames (~0.8 s) to stay readable.
    if (index // chunk) % 10 == 0:
        seconds = index / rate

        print(
            f"{seconds:5.1f}s raw {bar(raw, 24)} {raw:.4f}  "
            f"agc {bar(gained, 24)} x{detector.last_gain:4.1f}  "
            f"score {score:.2f} "
            f"{'<== WAKE' if score > detector.threshold else ''}"
        )

if in_utterance and peak_score_window > 0:
    utterance_peaks.append(peak_score_window)

print(f"\n{'=' * 60}")

raw_peak = max(raw_rms_values)

if raw_peak > 0.4:
    print(
        "!! WARNING: raw RMS ~0.5 with no speech usually means the "
        "device index resolves to a LOOPBACK/mirror or a saturated "
        "input. Check config audio.input_device and Windows input "
        "settings — AGC and score numbers below are unreliable "
        "for that device."
    )

if raw_peak < 0.002:
    print(
        "!! NOTE: raw peak RMS is near zero — this run captured only "
        "room noise. Speak DURING the recording to measure your "
        "voice's actual score."
    )

gained_peak = max(gained_rms_values)

print(f"raw mic peak RMS:      {raw_peak:.4f}")
print(f"after-AGC peak RMS:    {gained_peak:.4f}")
print(f"AGC gain range:        {min(detector.last_gain, 1.0):.1f} "
      f"-> {detector._agc_max_gain:.1f} (target RMS "
      f"{detector._agc_target_rms})")
print(f"peak wake score:       {peak_score:.2f} "
      f"(threshold {detector.threshold:.2f})")

if utterance_peaks:
    print("peak score per sound burst:")
    for number, value in enumerate(utterance_peaks, start=1):
        verdict = (
            "WOULD WAKE"
            if value > detector.threshold
            else "below threshold"
        )

        print(f"  burst {number}: {value:.2f} -> {verdict}")

print()

if peak_score > detector.threshold:
    print(
        "VERDICT: the detector hears you at this volume. If waking "
        "still feels unreliable, raise wake_word.sensitivity or "
        "check Windows mic level (Settings > Sound > Input)."
    )

else:
    print(
        "VERDICT: the score never crossed the threshold. Either the "
        "mic gain is still too low (Windows Settings > Sound > Input "
        "> microphone level to 100, disable 'audio enhancements') or "
        "sensitivity must go higher."
    )
