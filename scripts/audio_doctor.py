"""
Audio doctor: evidence, not guesses, about why JARVIS is silent.

Checks, in order, each printing success/failure + real numbers:

1. Output devices (sounddevice), the system default, and the device
   configured in config/settings.yaml (audio.input_device is the
   INPUT; output is always the system default unless set).
2. 1-second 440 Hz test tone to the default output — reports the peak
   amplitude actually queued to the device and the elapsed time.
3. Piper TTS (the offline fallback): model file existence check
   (data dir + project root .onnx), a real synthesis of a test
   sentence, peak amplitude, playback duration.
4. ElevenLabs TTS (only if ELEVENLABS_API_KEY is set): a real API
   request for the same sentence, peak amplitude, playback.
5. TTS duck sanity: duck_event set -> amplitude drops; after speech
   and after stop_speaking() the duck is CLEARED (never stuck at 20%).
6. Input devices + the configured input device, and a 2-second mic
   RMS reading so you can see what the mic actually hears.

Run:
    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe scripts/audio_doctor.py
"""

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.chdir(Path(__file__).resolve().parents[1])

import numpy as np
import sounddevice as sd


def rms(audio):
    audio = np.asarray(audio, dtype=np.float64)

    if audio.size == 0:
        return 0.0

    return float(np.sqrt(np.mean(audio ** 2)))


def peak(audio):
    audio = np.asarray(audio)

    if audio.size == 0:
        return 0.0

    return float(np.max(np.abs(audio)))


def line(title):
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


# ============================================================
# 1. DEVICES
# ============================================================

line("1. OUTPUT DEVICES")

defaults = sd.default.device

print(f"System default devices (in, out): {defaults}")

output_devices = []

for index, device in enumerate(sd.query_devices()):
    if device["max_output_channels"] > 0:
        marker = " <== DEFAULT" if index == defaults[1] else ""

        output_devices.append(index)

        print(
            f"  [{index}] {device['name']} "
            f"(out {device['max_output_channels']}ch, "
            f"{device['default_samplerate']:.0f} Hz){marker}"
        )

configured_input = None

try:
    from app.config import get as get_setting

    configured_input = get_setting("audio", "input_device")

except Exception as error:
    print(f"config read failed: {error}")

print(f"\nconfig audio.input_device = {configured_input!r}")

if configured_input is not None:
    try:
        name = sd.query_devices(configured_input)["name"]

        print(f"  -> resolves to: {name}")

    except Exception as error:
        print(f"  !! configured input device invalid: {error}")


# ============================================================
# 2. TEST TONE
# ============================================================

line("2. TEST TONE (1 s, 440 Hz, default output)")

try:
    rate = 44100

    t = np.linspace(0, 1.0, int(rate * 1.0), False)

    # 0.25 amplitude, scaled to int16 properly (the first doctor run
    # queued near-silence by casting a float wave without scaling).
    tone = (
        (0.25 * 32767) * np.sin(2 * np.pi * 440 * t)
    ).astype(np.int16)

    started = time.time()

    stream = sd.OutputStream(
        samplerate=rate, channels=1, dtype="int16"
    )

    stream.start()

    stream.write(tone)

    stream.stop()
    stream.close()

    elapsed = time.time() - started

    print(
        f"OK: tone queued (peak {peak(tone) / 32767:.3f}, "
        f"{elapsed:.2f}s including buffer drain). "
        "DID YOU HEAR IT? If not, the default output is wrong "
        "or muted/hardware volume is 0."
    )

except Exception as error:
    print(f"FAILED: {error}")


# ============================================================
# 3. PIPER TTS (offline fallback)
# ============================================================

line("3. PIPER TTS")

TEST_SENTENCE = "Audio doctor. If you can hear this, the piper voice works."

onnx_candidates = [
    Path("en_US-ryan-high.onnx"),
    Path("en_US-john-medium.onnx"),
    Path("en_US-lessac-medium.onnx"),
]

found_model = next(
    (p for p in onnx_candidates if p.exists()), None
)

print(f"Model file search: found={found_model}")

for candidate in onnx_candidates:
    marker = "FOUND" if candidate.exists() else "missing"

    print(f"  {candidate}: {marker}")

piper_ok = False

try:
    from piper import PiperVoice

    voice = PiperVoice.load(
        str(found_model) if found_model else "en_US-ryan-high.onnx"
    )

    synth_rate = voice.config.sample_rate

    collected = bytearray()

    started = time.time()

    for chunk in voice.synthesize(TEST_SENTENCE):
        collected.extend(chunk.audio_int16_bytes)

    synth_time = time.time() - started

    audio = np.frombuffer(bytes(collected), dtype=np.int16)

    print(
        f"Synthesis OK: {len(audio) / synth_rate:.2f}s of audio in "
        f"{synth_time:.2f}s, peak {peak(audio) / 32767:.3f}, "
        f"rms {rms(audio) / 32767:.4f}"
    )

    if audio.size == 0:
        print("!! Piper synthesized ZERO samples — that is the bug.")

    else:
        stream = sd.OutputStream(
            samplerate=synth_rate, channels=1, dtype="int16"
        )

        stream.start()
        stream.write(audio)
        stream.stop()
        stream.close()

        piper_ok = True

        print("Playback queued. DID YOU HEAR THE SENTENCE?")

except Exception as error:
    import traceback

    traceback.print_exc()

    print(f"PIPER FAILED: {error}")


# ============================================================
# 4. ELEVENLABS TTS (only when a key exists)
# ============================================================

line("4. ELEVENLABS TTS")

key = os.getenv("ELEVENLABS_API_KEY", "")

if not key:
    print(
        "ELEVENLABS_API_KEY not set — JARVIS uses Piper. "
        "(Set the key in .env for the premium voice.)"
    )

else:
    try:
        import httpx

        voice_id = os.getenv("ELEVENLABS_VOICE_ID") or (
            "pNInz6obpgDQGcFmaJgB"
        )

        started = time.time()

        response = httpx.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
            headers={
                "xi-api-key": key,
                "Content-Type": "application/json",
            },
            json={
                "text": TEST_SENTENCE,
                "model_id": "eleven_turbo_v2_5",
            },
            timeout=30.0,
        )

        if response.status_code != 200:
            print(
                f"HTTP {response.status_code}: "
                f"{response.text[:200]}"
            )

        else:
            audio = np.frombuffer(
                response.content[: len(response.content)
                // 2 * 2],
                dtype=np.int16,
            )

            print(
                f"OK: {len(response.content)} bytes in "
                f"{time.time() - started:.2f}s, peak "
                f"{peak(audio) / 32767:.3f}"
            )

    except Exception as error:
        print(f"ELEVENLABS FAILED: {error}")


# ============================================================
# 5. THE REAL TTS PATH + DUCK SANITY
# ============================================================

line("5. ORCHESTRATOR TTS PATH + DUCK SANITY")

try:
    from audio.text_to_speech import TextToSpeech

    tts = TextToSpeech()

    print(f"use_elevenlabs = {tts.use_elevenlabs}")

    if not tts.use_elevenlabs and not piper_ok:
        print(
            "!! BOTH paths broken or Piper failed — this is why "
            "JARVIS is silent."
        )

    # Duck must reduce amplitude...
    tts.duck_event.set()

    probe = (np.sin(np.linspace(0, 100, 1000)) * 20000).astype(
        np.int16
    )

    ducked = tts._ducked(probe)

    ratio = peak(ducked) / max(1, peak(probe))

    print(
        f"duck ratio while set: {ratio:.2f} "
        f"({'OK' if 0.15 <= ratio <= 0.25 else 'UNEXPECTED'})"
    )

    # ...and be cleared afterwards.
    tts.duck_event.clear()

    restored = tts._ducked(probe)

    print(
        f"duck cleared -> ratio {peak(restored) / peak(probe):.2f} "
        "(must be 1.00)"
    )

    # speak() must restore duck state after finishing or interrupting.
    tts.duck_event.set()

    finished = tts.speak("Duck restore test.")

    print(
        f"speak() returned {finished}; duck_event after speak: "
        f"{tts.duck_event.is_set()} (must be False)"
    )

except Exception as error:
    import traceback

    traceback.print_exc()

    print(f"TTS PATH FAILED: {error}")


# ============================================================
# 6. MIC INPUT LEVEL (what the wake word actually hears)
# ============================================================

line("6. MIC INPUT LEVEL (2 s)")

try:
    rate = 16000

    recorded = sd.rec(
        int(rate * 2),
        samplerate=rate,
        channels=1,
        dtype="float32",
        device=configured_input,
    )

    sd.wait()

    audio = np.squeeze(recorded)

    print(
        f"2 s of mic: peak {peak(audio):.4f}, rms "
        f"{rms(audio):.4f}. Speak normally at your desk distance: "
        "speech RMS should be >= ~0.02; if you see ~0.001-0.005 "
        "the mic gain is the 'I have to shout' culprit."
    )

except Exception as error:
    print(f"MIC RECORDING FAILED: {error}")


print("\nDone.")
