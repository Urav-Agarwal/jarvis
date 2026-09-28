"""
Skill system for JARVIS.

A skill is a named, reusable sequence of tool steps saved by the user
("my study setup", "morning routine"). Skills are stored as JSON in
data/skills.json and executed through the standard tool runtime.

Security: steps whose tools require user confirmation are NEVER
auto-executed by skill execution; they are reported as skipped.
"""

import json
import os
import re
import threading
import time
from pathlib import Path


class SkillStore:
    """JSON-file-backed store of reusable JARVIS workflows."""

    def __init__(self, path=None, tool_validator=None):
        self.path = Path(
            path
            or os.path.join("data", "skills.json")
        )

        self._lock = threading.Lock()

        self.path.parent.mkdir(parents=True, exist_ok=True)

        # Callable(name) -> tool definition or None.
        self.tool_validator = tool_validator

        self._skills = []

        self._load()

    # ==================================================
    # PUBLIC API
    # ==================================================

    def create(
        self,
        name: str,
        description: str,
        steps: list,
        triggers=None,
    ) -> dict:
        """Create or replace (version-bump) a skill after validation."""

        skill_name = (name or "").strip().lower()

        if not isinstance(name, str) or not name.strip():
            return {
                "success": False,
                "error": "The skill needs a name.",
            }

        if not isinstance(steps, list) or not steps:
            return {
                "success": False,
                "error": "The skill needs at least one step.",
            }

        normalized_steps = []

        for index, step in enumerate(steps):
            if not isinstance(step, dict):
                return {
                    "success": False,
                    "error": f"Step {index} is not a valid step object.",
                }

            tool = step.get("tool")

            if not isinstance(tool, str) or not tool.strip():
                return {
                    "success": False,
                    "error": f"Step {index} is missing a tool name.",
                }

            validation = self._validate_tool(tool)

            if not validation["ok"]:
                return {
                    "success": False,
                    "error": f"Step {index}: {validation['error']}",
                }

            parameters = step.get("parameters", {})

            if not isinstance(parameters, dict):
                return {
                    "success": False,
                    "error": f"Step {index}: parameters must be an object.",
                }

            normalized_steps.append(
                {
                    "tool": tool.strip(),
                    "parameters": parameters,
                }
            )

        skill = {
            "name": skill_name,
            "display_name": name.strip(),
            "description": (description or "").strip(),
            "triggers": self._normalize_triggers(triggers),
            "steps": normalized_steps,
            "version": self._version_of(skill_name) + 1,
            "created_at": self._created_of(skill_name) or time.time(),
            "updated_at": time.time(),
        }

        with self._lock:
            existing = self._find(skill["name"])

            if existing is not None:
                existing.update(skill)
                message = f"Updated skill: {skill['display_name']}"
            else:
                self._skills.append(skill)
                message = f"Created skill: {skill['display_name']}"

            if skill["version"] > 1:
                message += f" (v{skill['version']})"

            self._save()

        return {
            "success": True,
            "skill": skill,
            "message": message,
        }

    def find_by_trigger(self, request: str):
        """
        Return the skill whose trigger phrase best matches the
        request, or None.

        Matching is INTENT-based, not word-for-word: stopwords and
        command scaffolding are ignored, so "get my study session
        ready", "start my study session", and "my study session
        please" all fire a skill saved as "my study session". Exact
        containment still wins, with a fuzzy word-overlap fallback
        that requires the CORE words of the trigger to all appear.
        """

        request = " ".join((request or "").lower().split())

        if not request:
            return None

        with self._lock:
            best = None
            best_len = 0

            for skill in self._skills:
                for trigger in skill.get("triggers", []):
                    trigger = " ".join(trigger.split())

                    if not trigger:
                        continue

                    if (
                        request == trigger
                        or request.startswith(trigger + " ")
                        or request.endswith(" " + trigger)
                        or trigger in request
                    ):
                        if len(trigger) > best_len:
                            best = skill
                            best_len = len(trigger)

        if best is not None:
            return best

        # ---------------------------------------------
        # FUZZY FALLBACK: strip command scaffolding from both sides
        # and require the trigger's core words to all appear in the
        # request. "get my study session ready" keeps "study session"
        # -> matches the "my study session" trigger.
        # ---------------------------------------------

        request_core = self._core_words(request)

        if not request_core:
            return None

        with self._lock:
            best = None
            best_score = 0

            for skill in self._skills:
                for trigger in skill.get("triggers", []):
                    trigger_core = self._core_words(trigger)

                    if not trigger_core:
                        continue

                    # Every core trigger word must appear in the
                    # request (order-independent)...
                    if not trigger_core <= request_core:
                        continue

                    # ...and the request must not carry a completely
                    # different core intent ("open chrome" must not
                    # fire "study session").
                    extra = request_core - trigger_core

                    allowed_extra = {
                        "get", "start", "run", "do", "execute",
                        "activate", "begin", "ready", "launch",
                        "please", "now", "skill", "routine",
                        "mode", "setup", "time", "my", "session",
                    }

                    if not extra <= allowed_extra:
                        continue

                    score = len(trigger_core)

                    if score > best_score:
                        best = skill
                        best_score = score

        return best

    @staticmethod
    def _core_words(text: str) -> set:
        """
        Meaning-bearing words of a phrase: stopwords, command verbs,
        and politeness scaffolding removed. "get my study session
        ready" -> {"study", "session"}.
        """

        stopwords = {
            "a", "an", "the", "my", "me", "mine", "i", "you",
            "your", "it", "that", "this", "for", "to", "of",
            "in", "on", "at", "with", "and", "or", "please",
            "hey", "jarvis", "could", "would", "can", "will",
            "get", "got", "give", "let", "make", "put", "set",
            "start", "begin", "run", "do", "execute", "activate",
            "ready", "up", "go", "now", "then", "just", "some",
            "time", "thing", "stuff", "mode", "skill", "routine",
            "command", "again", "back",
        }

        return {
            word
            for word in re.findall(r"[a-z0-9]+", (text or "").lower())
            if word not in stopwords and len(word) > 1
        }

    @staticmethod
    def _normalize_triggers(triggers) -> list:
        if isinstance(triggers, str):
            triggers = [triggers]

        if not isinstance(triggers, list):
            return []

        normalized = []

        for trigger in triggers:
            if isinstance(trigger, str) and trigger.strip():
                normalized.append(trigger.strip().lower())

        return normalized

    def _version_of(self, name: str) -> int:
        skill = self._find(name)

        return (
            skill.get("version", 1)
            if skill
            else 0
        )

    def _created_of(self, name: str):
        skill = self._find(name)

        return (
            skill.get("created_at")
            if skill
            else None
        )

    def discover(self, query: str = "") -> dict:
        """List skills, optionally filtered by keywords."""

        query = (query or "").strip().lower()

        with self._lock:
            if not query:
                matches = list(self._skills)
            else:
                keywords = re.findall(r"[a-z0-9]+", query)

                matches = [
                    skill
                    for skill in self._skills
                    if self._matches(skill, keywords)
                ]

        if not matches:
            return {
                "success": True,
                "skills": [],
                "message": "No matching skills saved yet.",
            }

        names = [
            skill["display_name"]
            + (f" ({skill['description']})" if skill["description"] else "")
            for skill in matches
        ]

        return {
            "success": True,
            "skills": matches,
            "message": "Saved skills: " + "; ".join(names),
        }

    def validate(self, skill: dict) -> dict:
        """Validate a skill object without saving it."""

        if not isinstance(skill, dict):
            return {
                "success": False,
                "error": "A skill must be an object.",
            }

        steps = skill.get("steps")

        if not isinstance(steps, list) or not steps:
            return {
                "success": False,
                "error": "A skill needs at least one step.",
            }

        for index, step in enumerate(steps):
            if not isinstance(step, dict) or not step.get("tool"):
                return {
                    "success": False,
                    "error": f"Step {index} is invalid.",
                }

            validation = self._validate_tool(step["tool"])

            if not validation["ok"]:
                return {
                    "success": False,
                    "error": f"Step {index}: {validation['error']}",
                }

        return {
            "success": True,
            "message": "The skill is valid.",
        }

    def get(self, name: str):
        with self._lock:
            return self._find((name or "").strip().lower())

    def delete(self, name: str) -> dict:
        with self._lock:
            skill = self._find((name or "").strip().lower())

            if skill is None:
                return {
                    "success": False,
                    "error": f"No skill named {name} was found.",
                }

            self._skills.remove(skill)
            self._save()

        return {
            "success": True,
            "message": f"Deleted skill: {skill['display_name']}",
        }

    # ==================================================
    # INTERNALS
    # ==================================================

    def _validate_tool(self, tool: str) -> dict:
        if self.tool_validator is None:
            return {"ok": True}

        definition = self.tool_validator(tool)

        if definition is None:
            return {
                "ok": False,
                "error": f"Unknown tool '{tool}'.",
            }

        return {"ok": True}

    def _requires_confirmation(self, tool: str) -> bool:
        if self.tool_validator is None:
            return False

        definition = self.tool_validator(tool)

        return bool(
            definition
            and getattr(definition, "confirmation_required", False)
        )

    @staticmethod
    def _matches(skill: dict, keywords: list) -> bool:
        text = " ".join(
            [
                skill.get("name", ""),
                skill.get("display_name", ""),
                skill.get("description", ""),
            ]
        ).lower()

        return any(keyword in text for keyword in keywords)

    def _find(self, name: str):
        for skill in self._skills:
            if skill["name"] == name:
                return skill

        return None

    def _load(self):
        if not self.path.exists():
            return

        try:
            with open(self.path, "r", encoding="utf-8") as file:
                data = json.load(file)

            if isinstance(data, list):
                self._skills = data

        except (json.JSONDecodeError, OSError):
            self._skills = []

    def _save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as file:
                json.dump(self._skills, file, indent=2)

        except OSError:
            pass
