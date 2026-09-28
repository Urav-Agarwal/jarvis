"""
Speech-to-text for JARVIS.

Two providers, selected via JARVIS_STT_PROVIDER (default: groq):

- "groq"  : Groq-hosted whisper-large-v3-turbo. Far more accurate than
            the local model at similar latency, included in the same
            Groq API key. Wispr-Flow-class quality.
- "local" : faster-whisper on CPU (offline fallback).

Any hosted failure automatically falls back to the local model, so
voice never dies when the network or quota does.
"""

import io
import os
import re
import wave

from dotenv import load_dotenv

# Secrets (GROQ_API_KEY) live in .env; this module must work even
# when imported before ai.provider.
load_dotenv()

# Filler words removed from transcripts (Wispr-Flow-style cleanup):
# spoken hesitations carry no command meaning.
_FILLER_PATTERN = re.compile(
    r"\b(?:um+|uh+|uhm+|erm+|er+|hm+|hmm+|mm+|nn+|ugh+|uh+\s*huh+)\b[,.]?",
    re.IGNORECASE,
)

# Fragment gate: ultra-short transcriptions of noise/breath would
# otherwise trigger random actions.
_MIN_TRANSCRIPT_LEN = 2


class SpeechToText:
    def __init__(self):
        self.provider = (
            os.getenv("JARVIS_STT_PROVIDER") or "groq"
        ).lower()

        self._local_model = None
        self._groq_client = None

    # --------------------------------------------------
    # PROVIDERS (lazy: nothing heavy loads until first use)
    # --------------------------------------------------

    def _local(self):
        if self._local_model is None:
            from faster_whisper import WhisperModel

            from app.config import get as get_setting

            self._local_model = WhisperModel(
                get_setting("speech", "whisper_model") or "base",
                device="cpu",
                compute_type="int8",
            )

        return self._local_model

    def _groq(self):
        if self._groq_client is None:
            api_key = os.getenv("GROQ_API_KEY")

            if not api_key:
                return None

            from openai import OpenAI

            self._groq_client = OpenAI(
                base_url="https://api.groq.com/openai/v1",
                api_key=api_key,
                timeout=15.0,
                max_retries=1,
            )

        return self._groq_client

    # --------------------------------------------------
    # TRANSCRIPTION
    # --------------------------------------------------

    @staticmethod
    def _encode_wav(audio, sample_rate: int = 16000) -> bytes:
        """Float32 mono audio -> 16-bit WAV bytes (in memory)."""

        import numpy as np

        pcm = np.clip(np.asarray(audio, dtype=np.float32), -1.0, 1.0)
        pcm = (pcm * 32767.0).astype("<i2")

        buffer = io.BytesIO()

        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm.tobytes())

        return buffer.getvalue()

    def transcribe(self, audio, sample_rate: int = 16000) -> str:
        if len(audio) == 0:
            return ""

        text = ""

        if self.provider == "groq":
            client = self._groq()

            if client is not None:
                try:
                    wav_bytes = self._encode_wav(audio, sample_rate)

                    result = client.audio.transcriptions.create(
                        model="whisper-large-v3-turbo",
                        file=("speech.wav", wav_bytes, "audio/wav"),
                        response_format="text",
                        language="en",
                        temperature=0.0,
                    )

                    if isinstance(result, str):
                        text = result.strip()
                    else:
                        text = str(
                            getattr(result, "text", "") or result
                        ).strip()

                except Exception as error:
                    print(
                        "Groq STT failed, falling back to local "
                        f"whisper: {error}"
                    )

        if not text:
            try:
                segments, _info = self._local().transcribe(
                    audio,
                    language="en",
                )

                text = " ".join(
                    segment.text
                    for segment in segments
                ).strip()

            except Exception as error:
                print(f"Local STT failed: {error}")
                return ""

        return self._clean(text)

    @staticmethod
    def _clean(text: str) -> str:
        """Strip filler words and whitespace (Wispr-Flow-style)."""

        text = _FILLER_PATTERN.sub(" ", text)
        text = re.sub(r"\s+", " ", text).strip(
            " \t,."
        )

        if len(text.replace(" ", "")) < _MIN_TRANSCRIPT_LEN:
            return ""

        return text