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
        print("Listening...")

        chunk_duration = 0.1
        chunk_size = int(self.sample_rate * chunk_duration)

        audio_chunks = []
        speech_started = False
        silence_start = None

        start_time = time.time()
        speech_wait_start = time.time()

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

                volume = np.max(np.abs(audio))
                
                if not speech_started and time.time() - speech_wait_start >= start_timeout:
                    print("No speech started.")
                    return np.array([], dtype="float32")

                if volume > threshold:
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

        return np.concatenate(audio_chunks)


if __name__ == "__main__":
    mic = Microphone()

    audio = mic.record_until_silence()

    print("Recorded samples:", len(audio))
    print("Recording complete.")

if __name__ == "__main__":
    mic = Microphone()
    mic.measure_noise()