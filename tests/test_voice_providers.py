"""
Offline tests for the voice provider stack:

- STT: WAV encoding, provider selection, empty-audio handling
- TTS: ElevenLabs configuration, voice mapping, Piper fallback,
  barge-in on the PCM cache player, cache keys

No network calls, no audio hardware.

Run:
    PYTHONIOENCODING=utf-8 python -m tests.test_voice_providers
"""

import io
import os
import sys
import threading
import time
import wave

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audio.speech_to_text import SpeechToText
from audio.text_to_speech import TextToSpeech

failures = 0


def check(name, condition, detail=""):
    global failures

    if condition:
        print(f"[PASS] {name}")
    else:
        failures += 1
        print(f"[FAIL] {name} {detail}")


# ============================================================
# STT
# ============================================================

stt = SpeechToText()

check(
    "stt_default_provider_groq",
    stt.provider == "groq",
    stt.provider,
)

check(
    "stt_empty_audio",
    stt.transcribe([]) == "",
)

# Provider override via env.
os.environ["JARVIS_STT_PROVIDER"] = "local"

local_stt = SpeechToText()

check(
    "stt_provider_env_override",
    local_stt.provider == "local",
    local_stt.provider,
)

del os.environ["JARVIS_STT_PROVIDER"]

# WAV encoding produces a parseable, non-empty 16k mono file.
import numpy as np

tone = (0.1 * np.sin(2 * np.pi * 440 * np.linspace(0, 0.2, 3200))).astype(
    np.float32
)

wav_bytes = SpeechToText._encode_wav(tone, 16000)

with wave.open(io.BytesIO(wav_bytes), "rb") as wav_file:
    check(
        "stt_wav_valid",
        wav_file.getframerate() == 16000
        and wav_file.getnchannels() == 1
        and wav_file.getsampwidth() == 2
        and wav_file.getnframes() == 3200,
        (wav_file.getframerate(), wav_file.getnframes()),
    )

# No GROQ key -> _groq() returns None and code must fall back.
saved_key = os.environ.pop("GROQ_API_KEY", None)

check(
    "stt_groq_none_without_key",
    stt._groq() is None,
)

if saved_key is not None:
    os.environ["GROQ_API_KEY"] = saved_key

# ============================================================
# TTS CONFIGURATION
# ============================================================

saved_el = os.environ.pop("ELEVENLABS_API_KEY", None)
os.environ.pop("ELEVENLABS_VOICE_ID", None)
os.environ.pop("JARVIS_TTS_VOICE", None)

piper_tts = TextToSpeech()

check(
    "tts_piper_without_key",
    piper_tts.use_elevenlabs is False,
)

os.environ["ELEVENLABS_API_KEY"] = "test-key-123"

el_tts = TextToSpeech()

check(
    "tts_elevenlabs_with_key",
    el_tts.use_elevenlabs is True,
)

check(
    "tts_preset_voice_mapping",
    el_tts.voice_id == "pNInz6obpgDQGcFmaJgB",
    el_tts.voice_id,
)

os.environ["ELEVENLABS_VOICE_ID"] = "custom-voice-abc"

custom_tts = TextToSpeech()

check(
    "tts_custom_voice_passthrough",
    custom_tts.voice_id == "custom-voice-abc",
    custom_tts.voice_id,
)

del os.environ["ELEVENLABS_VOICE_ID"]
os.environ["ELEVENLABS_VOICE_ID"] = "custom-voice-abc"

check(
    "tts_cache_key_differs_by_text",
    custom_tts._cache_path("hello") != custom_tts._cache_path("goodbye"),
)

check(
    "tts_cache_key_stable",
    custom_tts._cache_path("hello") == custom_tts._cache_path("hello"),
)

# ============================================================
# BARGE-IN ON THE PCM PLAYER
# ============================================================

import audio.text_to_speech as tts_module


class FakeStream:
    def __init__(self, *args, **kwargs):
        pass

    def start(self):
        pass

    def write(self, data):
        time.sleep(0.015)

    def stop(self):
        pass

    def close(self):
        pass


original_output_stream = tts_module.sd.OutputStream
tts_module.sd.OutputStream = FakeStream

big_pcm = b"\x00\x00" * 220500  # 10 seconds at 22050 Hz

stop_flag = threading.Event()


def stop_soon():
    time.sleep(0.12)
    stop_flag.set()


stopper = threading.Thread(target=stop_soon)
stopper.start()

started = time.time()

result = TextToSpeech._play_pcm(
    big_pcm,
    sample_rate=22050,
    stop_event=stop_flag,
)

elapsed = time.time() - started
stopper.join()

tts_module.sd.OutputStream = original_output_stream

check(
    "tts_pcm_play_interrupted",
    result is False and elapsed < 2.0,
    (result, round(elapsed, 2)),
)

# Uninterrupted short playback completes with True.
check(
    "tts_pcm_play_completes",
    TextToSpeech._play_pcm(
        b"\x00\x00" * 4410,
        sample_rate=22050,
        stop_event=threading.Event(),
    )
    is True,
)

# Piper path: barge-in with a stubbed voice.
os.environ.pop("ELEVENLABS_API_KEY", None)
if saved_el is not None:
    os.environ["ELEVENLABS_API_KEY"] = saved_el

piper_tts2 = TextToSpeech()
piper_tts2._piper_voice = None


class FakeChunk:
    audio_int16_bytes = b"\x00\x00" * 160


class FakeVoice:
    config = type("Cfg", (), {"sample_rate": 22050})()

    def synthesize(self, text):
        for _ in range(60):
            if piper_tts2.stop_event.is_set():
                return

            time.sleep(0.01)

            yield FakeChunk()


piper_tts2._piper_voice = FakeVoice()

tts_module.sd.OutputStream = FakeStream

stop_flag2 = threading.Event()
threading.Timer(0.12, piper_tts2.stop_speaking).start()

piper_result = piper_tts2.speak("a long sentence that gets cut off")

tts_module.sd.OutputStream = original_output_stream

check(
    "tts_piper_barge_in",
    piper_result is False,
    piper_result,
)

# ============================================================
# SUMMARY
# ============================================================

print()

if failures:
    print(f"FAILED: {failures}")
    raise SystemExit(1)

print("ALL VOICE PROVIDER TESTS PASSED")
