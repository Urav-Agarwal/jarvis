import time

import numpy as np
import sounddevice as sd

from openwakeword.model import Model

from app.config import get as get_setting


class WakeWordDetector:
    def __init__(self):
        self.model = Model(
            wakeword_models=[
                get_setting("wake_word", "model") or "hey_jarvis"
            ]
        )

        # Pending score from the previous frame: short detections
        # must survive frame boundaries, and a single-frame spike can
        # be noise — averaging across frames rejects both.
        self._pending_score = 0.0
        self._pending_frames = 0

        self.threshold = (
            get_setting("wake_word", "threshold") or 0.35
        )

        self.sample_rate = (
            get_setting("audio", "sample_rate") or 16000
        )

        self.chunk_size = 1280

        # Transcript of the speech detected in the latest listen()
        # call (set by the orchestrator's filming-mode handler when
        # available). None when no transcript was captured.
        self.last_transcript = None

        print("Wake-word detector ready.")

    def listen(self, cooldown: float = 0.0):
        """
        Listen for 'Hey JARVIS'.

        cooldown: seconds to ignore detections after the stream opens.
        JARVIS's own voice ("...just say 'Hey JARVIS'") rings in the
        room right after a reply; without the cooldown the model
        detects JARVIS waking itself up.
        """

        print("Listening for 'Hey JARVIS'...")

        # Clear any wake-word state carried over from earlier audio.
        try:
            self.model.reset()

        except Exception:
            pass

        self._pending_frames = 0

        cooldown_until = time.time() + cooldown

        with sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="int16",
            blocksize=self.chunk_size,
        ) as stream:

            while True:
                audio, _ = stream.read(self.chunk_size)

                audio = np.squeeze(audio)

                # Keep the model's buffers fed during the cooldown so
                # its state stays continuous, but never trigger.
                prediction = self.model.predict(audio)

                if time.time() < cooldown_until:
                    continue

                score = prediction["hey_jarvis"]

                # Two-frame confirmation: the score must stay above
                # threshold twice in a row. A single loud frame (a
                # clap, a cough) is not a wake word, but a genuinely
                # spoken "Hey JARVIS" easily spans both frames.
                if score > self.threshold:
                    self._pending_frames += 1

                    if self._pending_frames >= 2:
                        self._pending_frames = 0
                        print("HEY JARVIS DETECTED!")
                        return True

                else:
                    self._pending_frames = 0

        return False


if __name__ == "__main__":
    detector = WakeWordDetector()

    if detector.listen():
        print("Wake word returned TRUE.")