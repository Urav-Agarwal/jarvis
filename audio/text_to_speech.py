import hashlib
import os
import threading

import numpy as np
import sounddevice as sd


_CACHE_DIR = os.path.join("data", "tts_cache")

# Classic deep-butler voices, override with ELEVENLABS_VOICE_ID using
# any voice from your ElevenLabs dashboard (or voice design).
_PRESET_VOICES = {
    "adam": "pNInz6obpgDQGcFmaJgB",
    "josh": "TX3LPaxmHKxFdv7VOQHJ",
    "antoni": "ErXwobaYiN019PkySvjV",
}


class TextToSpeech:
    """
    JARVIS voice with two providers and barge-in support.

    - elevenlabs (default when ELEVENLABS_API_KEY is set): streamed
      PCM playback, response cached to disk, any voice you choose.
    - piper (offline fallback): local neural voice, no network.

    speak() checks self.stop_event between audio chunks, so any thread
    can call stop_speaking() to cut off current speech ("stop" /
    "cancel" mid-sentence still works instantly).
    """

    def __init__(self):
        # Global stop flag shared across instances (barge-in).
        self.stop_event = threading.Event()

        # DUCK (v4): while set, playback volume drops to ~20%. The
        # barge-in watcher sets it the moment a mic burst is detected
        # during speech, so JARVIS's own voice stops masking the
        # user's "hey Jarvis" / "stop" — without killing playback
        # when the burst turns out to be background noise.
        self.duck_event = threading.Event()

        self._piper_voice = None
        self._http = None

        self.elevenlabs_key = os.getenv("ELEVENLABS_API_KEY") or ""

        requested = (
            os.getenv("ELEVENLABS_VOICE_ID")
            or os.getenv("JARVIS_TTS_VOICE")
            or "adam"
        ).strip()

        self.voice_id = _PRESET_VOICES.get(
            requested.lower(),
            requested,
        )

        self.elevenlabs_model = os.getenv(
            "ELEVENLABS_MODEL",
            "eleven_turbo_v2_5",
        )

        # Piper only when ElevenLabs is unavailable.
        self.use_elevenlabs = bool(
            self.elevenlabs_key and self.voice_id
        )

    # --------------------------------------------------
    # PUBLIC API
    # --------------------------------------------------

    def speak(self, text: str) -> bool:
        """
        Speak text. Returns True if it finished, False if interrupted
        by stop_speaking().

        DUCK SAFETY (audio_doctor found this): the duck flag is only
        valid DURING a barge-in judgement. Clear it on entry and on
        exit so a stuck flag can never leave every later reply at 20%
        volume — that was the "I cannot hear JARVIS" bug.
        """

        self.stop_event.clear()

        self.duck_event.clear()

        if not text:
            return True

        try:
            if self.use_elevenlabs:
                try:
                    return self._speak_elevenlabs(text)

                except Exception as error:
                    print(
                        f"ElevenLabs TTS failed ({error}); using Piper."
                    )

            return self._speak_piper(text)

        finally:
            # Never leave the duck engaged past the utterance.
            self.duck_event.clear()

    def stop_speaking(self):
        """Interrupt current speech from any thread."""

        self.stop_event.set()

    def _ducked(self, audio: np.ndarray) -> np.ndarray:
        """Apply the duck volume (int16-safe) when duck_event is set."""

        if self.duck_event.is_set() and audio.size:
            audio = (audio.astype(np.int32) * 2 // 10).astype(
                np.int16
            )

        return audio

    # --------------------------------------------------
    # ELEVENLABS
    # --------------------------------------------------

    def _http_client(self):
        if self._http is None:
            import httpx

            self._http = httpx.Client(timeout=30.0)

        return self._http

    def _cache_path(self, text: str) -> str:
        digest = hashlib.sha1(
            f"{self.voice_id}|{self.elevenlabs_model}|{text}".encode(
                "utf-8"
            )
        ).hexdigest()

        os.makedirs(_CACHE_DIR, exist_ok=True)

        return os.path.join(_CACHE_DIR, f"{digest}.pcm")

    def _speak_elevenlabs(self, text: str) -> bool:
        """Stream ElevenLabs PCM; cache responses for instant replay."""

        cache_path = self._cache_path(text)

        if os.path.exists(cache_path):
            with open(cache_path, "rb") as cached:
                pcm_bytes = cached.read()

            return self._play_pcm(
                pcm_bytes,
                sample_rate=22050,
                stop_event=self.stop_event,
            )

        url = (
            "https://api.elevenlabs.io/v1/text-to-speech/"
            f"{self.voice_id}?output_format=pcm_22050"
        )

        payload = {
            "text": text,
            "model_id": self.elevenlabs_model,
            "voice_settings": {
                "stability": 0.55,
                "similarity_boost": 0.8,
                "style": 0.25,
                "use_speaker_boost": True,
            },
        }

        headers = {
            "xi-api-key": self.elevenlabs_key,
            "Content-Type": "application/json",
            "accept": "audio/*",
        }

        collected = bytearray()

        finished = True

        with self._http_client().stream(
            "POST",
            url,
            headers=headers,
            json=payload,
            timeout=30.0,
        ) as response:
            if response.status_code != 200:
                body = response.read().decode(errors="ignore")[:200]

                raise RuntimeError(
                    f"HTTP {response.status_code}: {body}"
                )

            # ------------------------------------------------
            # PRE-BUFFER: hold ~190 ms of audio before starting
            # playback. Network jitter inside this cushion never
            # reaches the speaker — no stutters, no mid-word gaps.
            # ------------------------------------------------
            prebuffer_target = 8192  # bytes = ~186 ms at 22050 Hz/16-bit

            prebuffer = bytearray()

            stream = None

            try:
                for chunk in response.iter_bytes(4096):
                    if self.stop_event.is_set():
                        finished = False
                        break

                    collected.extend(chunk)

                    if stream is None:
                        prebuffer.extend(chunk)

                        if len(prebuffer) < prebuffer_target:
                            continue

                        stream = sd.OutputStream(
                            samplerate=22050,
                            channels=1,
                            dtype="int16",
                        )

                        stream.start()

                        audio = np.frombuffer(
                            bytes(prebuffer),
                            dtype=np.int16,
                        )

                        if audio.size:
                            stream.write(audio)

                        prebuffer = bytearray()
                        continue

                    audio = np.frombuffer(
                        chunk,
                        dtype=np.int16,
                    )

                    if audio.size:
                        stream.write(audio)

                # Short utterance: everything fit in the prebuffer
                # and playback never started — play it now.
                if stream is None and prebuffer and finished:
                    stream = sd.OutputStream(
                        samplerate=22050,
                        channels=1,
                        dtype="int16",
                    )

                    stream.start()

                    audio = np.frombuffer(
                        bytes(prebuffer),
                        dtype=np.int16,
                    )

                    if audio.size:
                        stream.write(audio)

            finally:
                if stream is not None:
                    stream.stop()
                    stream.close()

        if finished and not self.stop_event.is_set():
            try:
                with open(cache_path, "wb") as cache_file:
                    cache_file.write(bytes(collected))

            except OSError:
                pass

        interrupted = self.stop_event.is_set()
        self.stop_event.clear()

        return not interrupted

    @staticmethod
    def _play_pcm(
        pcm_bytes: bytes,
        sample_rate: int,
        stop_event: threading.Event,
    ) -> bool:
        """Play raw 16-bit mono PCM with interruption support."""

        stream = sd.OutputStream(
            samplerate=sample_rate,
            channels=1,
            dtype="int16",
        )

        stream.start()

        chunk_size = 4410  # ~100 ms at 22050 Hz

        interrupted = False

        try:
            for start in range(0, len(pcm_bytes), chunk_size):
                if stop_event.is_set():
                    interrupted = True
                    break

                audio = np.frombuffer(
                    pcm_bytes[start:start + chunk_size],
                    dtype=np.int16,
                )

                if audio.size:
                    stream.write(self._ducked(audio))

        finally:
            stream.stop()
            stream.close()

        return not interrupted

    # --------------------------------------------------
    # PIPER FALLBACK (offline)
    # --------------------------------------------------

    def _speak_piper(self, text: str) -> bool:
        if self._piper_voice is None:
            from piper import PiperVoice

            self._piper_voice = PiperVoice.load(
                "en_US-ryan-high.onnx"
            )

        voice = self._piper_voice

        stream = sd.OutputStream(
            samplerate=voice.config.sample_rate,
            channels=1,
            dtype="int16",
        )

        stream.start()

        interrupted = False

        try:
            for chunk in voice.synthesize(text):
                if self.stop_event.is_set():
                    interrupted = True
                    break

                audio = np.frombuffer(
                    chunk.audio_int16_bytes,
                    dtype=np.int16,
                )

                if audio.size:
                    stream.write(self._ducked(audio))

        finally:
            stream.stop()
            stream.close()

        if self.stop_event.is_set():
            interrupted = True

        self.stop_event.clear()

        return not interrupted