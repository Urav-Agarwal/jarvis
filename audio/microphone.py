import time

import numpy as np
import sounddevice as sd

from app.config import get as get_setting


class Microphone:
    def __init__(self, device=None, sample_rate=None, channels=1):
        self.device = (
            device
            if device is not None
            else get_setting("audio", "input_device")
        )

        self.sample_rate = (
            sample_rate
            if sample_rate is not None
            else get_setting("audio", "sample_rate") or 16000
        )

        self.channels = channels

    def measure_noise(self, duration=3):
        print("Measuring background noise... stay silent.")

        audio = sd.rec(
            int(duration * self.sample_rate),
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="float32",
            device=self.device,
        )

        sd.wait()

        audio = np.squeeze(audio)

        print("Background max:", np.max(np.abs(audio)))
        print("Background mean:", np.mean(np.abs(audio)))

    def record_until_silence(
        self,
        max_duration=10,
        silence_duration=0.8,
        threshold=0.03,
        start_timeout=3,
    ):
        """
        Record until speech ends. v4.1: the speech threshold ADAPTS
        to this mic's noise floor — the audio doctor measured raw mic
        RMS ~0.0002 on this machine, where a fixed 0.03 threshold
        made normal speech inaudible (the "I have to shout" bug).
        Noise floor is sampled from the first ~0.4 s and the speech
        gate rides above it (floor + max(0.004, 8x floor)), clamped
        to a sane range. Whisper also gets a louder signal because
        quiet frames below a fixed floor are amplified before STT.
        """

        print("Listening...")

        chunk_duration = 0.1
        chunk_size = int(self.sample_rate * chunk_duration)

        audio_chunks = []
        speech_started = False
        silence_start = None

        start_time = time.time()
        speech_wait_start = time.time()

        noise_floor = None  # measured while waiting for speech
        # Adaptive gate: above the measured floor, but never below a
        # small absolute floor (protects against a perfect 0.0 floor)
        # and never so high that normal speech cannot cross it.

        with sd.InputStream(
            device=self.device,
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="float32",
            blocksize=chunk_size,
        ) as stream:

            while time.time() - start_time < max_duration:
                audio, _ = stream.read(chunk_size)

                audio = np.squeeze(audio)
                audio_chunks.append(audio.copy())

                volume = float(np.max(np.abs(audio)))

                if not speech_started:
                    # NOISE FLOOR = the MINIMUM of the first ~0.5 s of
                    # frames, then LOCKED. Max-tracking ratchets raced
                    # the voice and choked on DC-noise rooms (both
                    # caught by the fake-mic unit tests); min-tracking
                    # converges to the true room level.
                    if noise_floor is None:
                        noise_floor = [volume]

                    elif len(noise_floor) < 5:
                        noise_floor.append(volume)

                    if len(noise_floor) >= 5:
                        floor_value = min(noise_floor)

                    else:
                        floor_value = min(noise_floor)

                    effective_threshold = max(
                        threshold * 0.2,  # never below 0.006
                        min(
                            threshold,          # never above 0.03
                            floor_value * 8 + 0.004,
                        ),
                    )

                if not speech_started and time.time() - speech_wait_start >= start_timeout:
                    print("No speech started.")
                    return np.array([], dtype="float32")

                if volume > effective_threshold:
                    speech_started = True
                    silence_start = None

                elif speech_started:
                    if silence_start is None:
                        silence_start = time.time()

                    elif time.time() - silence_start >= silence_duration:
                        break

                elif not speech_started:
                    # Ignore background noise until actual speech is detected.
                    continue

        if not speech_started:
            print("No speech detected.")
            return np.array([], dtype="float32")

        recorded = np.concatenate(audio_chunks)

        # NORMALIZE for STT: a mic this quiet produces whisper-quiet
        # audio that Whisper struggles with. Bring speech peaks to a
        # healthy level without clipping.
        peak = float(np.max(np.abs(recorded)))

        if 0.0 < peak < 0.05:
            recorded = recorded * min(8.0, 0.30 / peak)

            recorded = np.clip(recorded, -1.0, 1.0)

        return recorded.astype("float32")


if __name__ == "__main__":
    mic = Microphone()

    audio = mic.record_until_silence()

    print("Recorded samples:", len(audio))
    print("Recording complete.")

if __name__ == "__main__":
    mic = Microphone()
    mic.measure_noise()