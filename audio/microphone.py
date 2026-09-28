import time

import numpy as np
import sounddevice as sd

from app.config import get as get_setting


# v4.1.2 DEBUG: per-frame mic decisions go to data/logs/mic_debug.log
# (level, floor, gate, decision, end reason). Kept small: 100 ms per
# line only while recording.
_LOG_PATH = "data/logs/mic_debug.log"


def _mic_log(line):
    try:
        import os

        os.makedirs("data/logs", exist_ok=True)

        with open(_LOG_PATH, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    except Exception:
        pass

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
        Record until speech ends.

        v4.1.2 RECALIBRATION (the user fixed the mic at the Windows
        level: raw peaks are now ~0.2-0.3, ~100x the old level the
        previous gate was tuned for):

        - NOISE FLOOR: median of the first ~0.5 s of frames (robust
          against a single spike), then LOCKED.
        - SPEECH GATE: floor * 3, clamped to
          [absolute_min, absolute_max] (defaults 0.012 / 0.045).
          A strong mic clears floor*3 easily; the absolute max keeps
          a bad floor measurement from deafening JARVIS.
        - END OF UTTERANCE: silence_duration below the gate; the
          tail frames are trimmed so STT does not get dead air.
        - NORMALIZATION: only when the capture is genuinely quiet
          (peak < 0.05); a healthy 0.2-0.3 capture passes through
          untouched.

        Every decision is logged to data/logs/mic_debug.log.
        """

        print("Listening...")

        chunk_duration = 0.1
        chunk_size = int(self.sample_rate * chunk_duration)

        # Absolute clamp for the adaptive gate. Configurable for
        # future mic changes; these defaults suit the CURRENT mic
        # (raw speech peaks 0.2-0.3, room floor ~0.002-0.01).
        try:
            from app.config import get as _cfg

            gate_min = float(
                _cfg("audio", "speech_gate_min") or 0.012
            )

            gate_max = float(
                _cfg("audio", "speech_gate_max") or 0.045
            )

        except Exception:
            gate_min = 0.012

            gate_max = 0.045

        audio_chunks = []
        speech_started = False
        silence_start = None

        start_time = time.time()
        speech_wait_start = time.time()

        floor_frames = []          # first 0.5 s -> noise floor
        noise_floor = 0.0
        floor_locked = False
        effective_threshold = gate_min
        end_reason = "max_duration"

        _mic_log(
            f"--- record start {time.strftime('%H:%M:%S')} "
            f"gate_min={gate_min:.4f} gate_max={gate_max:.4f} "
            f"silence_duration={silence_duration}" 
        )

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

                # RMS (not peak): speech RMS vs peak-to-floor is a
                # stabler gate on a strong mic.
                volume = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))

                if not speech_started:
                    if not floor_locked:
                        floor_frames.append(volume)

                        if (
                            len(floor_frames) >= 5
                            or time.time() - speech_wait_start >= 0.5
                        ):
                            # Median: one cough/spike at boot must
                            # not raise the floor.
                            sorted_frames = sorted(floor_frames)

                            noise_floor = sorted_frames[
                                len(sorted_frames) // 2
                            ]

                            floor_locked = True

                            effective_threshold = max(
                                gate_min,
                                min(gate_max, noise_floor * 3),
                            )

                            _mic_log(
                                f"floor locked: floor={noise_floor:.5f} "
                                f"gate={effective_threshold:.4f} "
                                f"(frames={len(floor_frames)})"
                            )

                    if (
                        not floor_locked
                        and time.time() - speech_wait_start
                        >= start_timeout
                    ):
                        _mic_log(
                            "end: start_timeout (floor never locked)"
                        )

                        print("No speech started.")

                        return np.array([], dtype="float32")

                    if (
                        floor_locked
                        and time.time() - speech_wait_start
                        >= start_timeout
                    ):
                        _mic_log(
                            f"end: start_timeout, floor={noise_floor:.5f} "
                            f"gate={effective_threshold:.4f} "
                            f"max_frame_rms={max(floor_frames):.5f}"
                        )

                        print("No speech started.")

                        return np.array([], dtype="float32")

                    speech = volume > effective_threshold

                    _mic_log(
                        f"wait rms={volume:.5f} "
                        f"floor={noise_floor:.5f} "
                        f"gate={effective_threshold:.4f} "
                        f"speech={speech}"
                    )

                    if speech:
                        speech_started = True
                        silence_start = None

                        _mic_log(
                            f"speech START rms={volume:.5f} "
                            f"gate={effective_threshold:.4f}"
                        )

                    continue

                # --- speech_started: watch for the trailing silence.
                speech = volume > effective_threshold

                _mic_log(
                    f"capt rms={volume:.5f} "
                    f"gate={effective_threshold:.4f} speech={speech}"
                )

                if speech:
                    silence_start = None

                else:
                    if silence_start is None:
                        silence_start = time.time()

                    elif (
                        time.time() - silence_start >= silence_duration
                    ):
                        end_reason = "silence"

                        _mic_log(
                            f"end: silence after utterance "
                            f"({silence_duration:.2f}s below gate)"
                        )

                        break

        recorded = np.concatenate(audio_chunks)

        if not speech_started:
            _mic_log(
                f"end: max_duration without speech "
                f"({len(recorded)} samples)"
            )

            print("No speech detected.")

            return np.array([], dtype="float32")

        _mic_log(
            f"recorded: {len(recorded)} samples "
            f"({len(recorded) / self.sample_rate:.2f}s), "
            f"end_reason={end_reason}"
        )

        # NORMALIZE for STT only when the capture is genuinely quiet
        # (the old quiet mic). A healthy 0.2-0.3 capture is passed
        # through untouched — no pointless gain, no clipping risk.
        peak = float(np.max(np.abs(recorded)))

        if 0.0 < peak < 0.05:
            gain = min(8.0, 0.30 / peak)

            recorded = np.clip(recorded * gain, -1.0, 1.0)

            _mic_log(
                f"normalized: peak {peak:.4f} -> "
                f"{float(np.max(np.abs(recorded))):.4f} "
                f"(gain {gain:.1f})"
            )

        else:
            _mic_log(f"no normalization needed (peak {peak:.4f})")

        return recorded.astype("float32")


if __name__ == "__main__":
    mic = Microphone()

    audio = mic.record_until_silence()

    print("Recorded samples:", len(audio))
    print("Recording complete.")

if __name__ == "__main__":
    mic = Microphone()
    mic.measure_noise()