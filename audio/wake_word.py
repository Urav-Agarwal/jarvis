import time

import numpy as np
import sounddevice as sd

from openwakeword.model import Model

from app.config import get as get_setting


# Sensitivity presets (v4.1 A3): the user had to SHOUT because the
# raw mic level at normal volume never crossed the fixed threshold.
# "high" = wakes from a quiet voice (more false-positive risk, but
# two-frame + refractory guard against storms).
_SENSITIVITY_THRESHOLDS = {
    "low": 0.50,
    "medium": 0.35,
    "high": 0.22,
}


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

        sensitivity = (
            str(get_setting("wake_word", "sensitivity") or "medium")
            .lower()
            .strip()
        )

        self.sensitivity = sensitivity

        self.threshold = _SENSITIVITY_THRESHOLDS.get(
            sensitivity,
            float(get_setting("wake_word", "threshold") or 0.35),
        )

        self.sample_rate = (
            get_setting("audio", "sample_rate") or 16000
        )

        self.chunk_size = 1280

        # ----------------------------------------------------
        # AGC (automatic gain control): normalise each frame's RMS
        # to a target level before the model sees it. The audio
        # doctor measured mic RMS ~0.0001 idle — at that level a
        # normal spoken "hey Jarvis" scores far below threshold,
        # which is exactly the "I have to shout" symptom.
        # NOTE: YAML "true" can arrive as bool True or str "true"
        # depending on the loader; handle BOTH explicitly.
        # ----------------------------------------------------
        agc_setting = get_setting("wake_word", "agc")

        self.agc_enabled = not (
            agc_setting is False
            or (isinstance(agc_setting, str)
                and agc_setting.strip().lower() in {"false", "0", "no"})
        )  # default ON

        self._agc_target_rms = 0.05

        # v4.1.2: the user fixed the mic at the Windows level — raw
        # speech peaks are now 0.2-0.3 (was ~0.003). A 25x gain on a
        # healthy mic would amplify ROOM NOISE into the wake model's
        # range and pump false triggers. Cap the gain low: a good mic
        # needs none; a quiet one still gets a gentle boost.
        self._agc_max_gain = 2.0

        self._agc_gain = 1.0

        # Live meters (read by the UI mic meter and wake_doctor).
        self.last_rms = 0.0
        self.last_score = 0.0
        self.last_gain = 1.0

        # Transcript of the speech detected in the latest listen()
        # call (set by the orchestrator's filming-mode handler when
        # available). None when no transcript was captured.
        self.last_transcript = None

        print(
            f"Wake-word detector ready "
            f"(sensitivity={self.sensitivity}, "
            f"threshold={self.threshold:.2f}, "
            f"agc={'on' if self.agc_enabled else 'off'})."
        )

    def _agc(self, audio: np.ndarray) -> np.ndarray:
        """
        Amplify the frame towards the target RMS with a SMOOTHED gain
        (fast attacks would pump noise up into words). Works on the
        int16 frame; output stays in int16 range.
        """

        if not self.agc_enabled:
            self.last_gain = 1.0

            return audio

        # RMS in FLOAT scale (0..1) — the target is float-scale too.
        # (Int16-unit RMS made `wanted` always < 1 and the AGC a
        # no-op; caught by the wake doctor's synthetic-frame check.)
        # caught by the wake doctor's synthetic-frame check.)
        frame_rms = float(
            np.sqrt(
                np.mean(audio.astype(np.float64) ** 2)
            )
            / 32767.0
        )

        self.last_rms = frame_rms

        if frame_rms < 1e-6:
            # Digital silence: keep the last gain, do not divide.
            self.last_gain = self._agc_gain

            return audio

        # NO-NOISE AMPLIFICATION (v4.1.2): when the frame is at/below
        # the room level, hold the gain at 1.0 (do NOT boost room
        # noise towards the speech target). Gain may only RISE while
        # frames already look speech-like (rms >= 0.01).
        if frame_rms < 0.01:
            self._agc_gain = 1.0

            self.last_gain = 1.0

            return audio

        wanted = self._agc_target_rms / frame_rms

        wanted = max(1.0, min(self._agc_max_gain, wanted))

        # Smooth: 80% previous gain, 20% new demand.
        self._agc_gain = 0.8 * self._agc_gain + 0.2 * wanted

        self.last_gain = self._agc_gain

        # Amplify in int16 units (frame is int16, gain is a factor).
        amplified = audio.astype(np.float64) * self._agc_gain

        return np.clip(amplified, -32767, 32767).astype(np.int16)

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

                # AGC before the model: normal-volume speech reaches
                # the model at a usable level (v4.1 A3).
                audio = self._agc(audio)

                # Keep the model's buffers fed during the cooldown so
                # its state stays continuous, but never trigger.
                prediction = self.model.predict(audio)

                if time.time() < cooldown_until:
                    continue

                score = prediction["hey_jarvis"]

                self.last_score = score

                # Two-frame confirmation: the score must stay above
                # threshold twice in a row. A single loud frame (a
                # clap, a cough) is not a wake word, but a genuinely
                # spoken "Hey JARVIS" easily spans both frames.
                if score > self.threshold:
                    self._pending_frames += 1

                    if self._pending_frames >= 2:
                        self._pending_frames = 0
                        print(
                            "HEY JARVIS DETECTED! "
                            f"(score={score:.2f}, "
                            f"rms={self.last_rms:.4f}, "
                            f"gain={self.last_gain:.1f})"
                        )

                        return True

                else:
                    self._pending_frames = 0

        return False


if __name__ == "__main__":
    detector = WakeWordDetector()

    if detector.listen():
        print("Wake word returned TRUE.")