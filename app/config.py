"""
Runtime configuration for JARVIS.

Loads config/settings.yaml and exposes typed accessor helpers with
sane defaults, so components never hardcode tunable values.
"""

import os
from pathlib import Path

import yaml

_DEFAULTS = {
    "audio": {
        "input_device": None,
        "sample_rate": 16000,
        "silence_threshold": 0.03,
        "silence_duration": 0.8,
        "max_utterance_seconds": 10,
    },
    "wake_word": {
        "model": "hey_jarvis",
        "threshold": 0.35,
    },
    "speech": {
        "whisper_model": "base",
        "tts_voice": "en_US-ryan-high.onnx",
    },
    "agent": {
        "context_turns": 4,
        "max_consecutive_failures": 3,
        "tone": "balanced",
        "proactive_mode": True,
    },
    "memory": {
        "path": "data/memory.json",
    },
    "skills": {
        "path": "data/skills.json",
    },
}

_SETTINGS = None


def _load() -> dict:
    global _SETTINGS

    if _SETTINGS is not None:
        return _SETTINGS

    settings = _DEFAULTS

    settings_path = Path("config") / "settings.yaml"

    if settings_path.exists():
        try:
            with open(settings_path, "r", encoding="utf-8") as file:
                data = yaml.safe_load(file) or {}

            if isinstance(data, dict):
                for section, values in data.items():
                    if isinstance(values, dict) and isinstance(
                        settings.get(section), dict
                    ):
                        settings[section].update(values)
                    else:
                        settings[section] = values

        except (OSError, yaml.YAMLError):
            # Malformed settings: keep defaults.
            pass

    _SETTINGS = settings

    return _SETTINGS


def get(section: str, key: str):
    """Return a setting value, falling back to built-in defaults."""

    return _load().get(section, {}).get(key, _DEFAULTS.get(section, {}).get(key))


def section(name: str) -> dict:
    """Return a whole settings section."""

    return dict(_load().get(name, {}))
