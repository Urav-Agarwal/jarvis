"""
Persistent memory for JARVIS.

Stores durable user facts ("remember that I prefer dark mode") as a
JSON file in data/. Deliberately deterministic — no LLM in the loop.
"""

import json
import os
import re
import threading
import time
from pathlib import Path


class MemoryStore:
    """JSON-file-backed persistent memory with keyword search."""

    def __init__(self, path=None):
        self.path = Path(path or os.path.join("data", "memory.json"))

        self._lock = threading.Lock()

        self.path.parent.mkdir(parents=True, exist_ok=True)

        self._entries = []

        self._load()

    # ==================================================
    # PUBLIC API
    # ==================================================

    def remember(self, information: str) -> dict:
        """Store a new durable fact (updates in place if restated)."""

        if not isinstance(information, str) or not information.strip():
            return {
                "success": False,
                "error": "Nothing to remember.",
            }

        # Strip conversational prefixes ("remember that ...").
        information = re.sub(
            r"^remember(?: that| this)?[,: ]+",
            "",
            information.strip(),
            flags=re.IGNORECASE,
        )

        with self._lock:
            existing = self._find_exact(information)

            if existing is not None:
                existing["updated_at"] = time.time()
                self._save()

                return {
                    "success": True,
                    "updated": True,
                    "information": information,
                    "message": "I already had that stored.",
                }

            self._entries.append(
                {
                    "information": information,
                    "created_at": time.time(),
                }
            )

            self._save()

        return {
            "success": True,
            "updated": False,
            "information": information,
            "message": f"Remembered: {information}",
        }

    def recall(self, query: str) -> dict:
        """Search stored facts by keyword overlap."""

        query = (query or "").strip()

        with self._lock:
            matches = self._search(query)

        if not matches:
            # Keyword search found nothing: fall back to the most
            # recent facts so conversational recall still works.
            if self._entries:
                recent = [
                    entry["information"]
                    for entry in self._entries[-3:]
                ]

                return {
                    "success": True,
                    "results": recent,
                    "message": "Here is what I remember: "
                    + "; ".join(recent),
                }

            return {
                "success": True,
                "results": [],
                "message": "I don't have anything stored yet.",
            }

        informations = [entry["information"] for entry in matches]

        return {
            "success": True,
            "results": informations,
            "message": "; ".join(informations),
        }

    def update(self, query: str, information: str) -> dict:
        """Update the best-matching stored fact, or store anew."""

        if not isinstance(information, str) or not information.strip():
            return {
                "success": False,
                "error": "Nothing to update with.",
            }

        with self._lock:
            matches = self._search(query)

        if not matches:
            return self.remember(information)

        best = matches[0]
        best["information"] = information.strip()
        best["updated_at"] = time.time()

        with self._lock:
            self._save()

        return {
            "success": True,
            "updated": True,
            "information": best["information"],
            "message": f"Updated: {best['information']}",
        }

    def forget(self, query: str) -> dict:
        """Remove the best-matching stored fact."""

        with self._lock:
            matches = self._search(query)

        if not matches:
            return {
                "success": False,
                "error": "I don't have anything stored about that.",
            }

        best = matches[0]

        with self._lock:
            self._entries.remove(best)
            self._save()

        return {
            "success": True,
            "information": best["information"],
            "message": f"Forgotten: {best['information']}",
        }

    def all_facts(self) -> list:
        with self._lock:
            return [dict(entry) for entry in self._entries]

    # ==================================================
    # INTERNALS
    # ==================================================

    def _find_exact(self, information: str):
        normalized = information.lower().strip()

        for entry in self._entries:
            if entry["information"].lower().strip() == normalized:
                return entry

        return None

    def _search(self, query: str) -> list:
        keywords = self._keywords(query)

        if not keywords:
            return []

        scored = []

        for entry in self._entries:
            text = entry["information"].lower()
            score = sum(1 for keyword in keywords if keyword in text)

            if score > 0:
                scored.append((score, entry))

        scored.sort(key=lambda pair: pair[0], reverse=True)

        return [entry for _, entry in scored]

    @staticmethod
    def _keywords(query: str) -> list:
        words = re.findall(r"[a-z0-9]+", query.lower())

        stopwords = {
            "what", "do", "you", "about", "my", "me", "the", "a",
            "an", "is", "are", "that", "this", "it", "i", "am",
            "remember", "recall", "forget", "tell", "of", "on",
        }

        return [word for word in words if word not in stopwords]

    def _load(self):
        if not self.path.exists():
            return

        try:
            with open(self.path, "r", encoding="utf-8") as file:
                data = json.load(file)

            if isinstance(data, list):
                self._entries = data

        except (json.JSONDecodeError, OSError):
            # Corrupt memory file: start empty rather than crash.
            self._entries = []

    def _save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as file:
                json.dump(self._entries, file, indent=2)

        except OSError:
            pass
