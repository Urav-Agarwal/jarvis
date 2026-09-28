"""
Reminder store and background checker for JARVIS.

Supports "remind me to X at 8 PM" and recurring routines
("every evening at 9 remind me to ..."). Checked by a daemon thread
in the Orchestrator; due reminders are spoken and marked done.
"""

import json
import os
import re
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path


class ReminderStore:
    """JSON-file-backed reminders with a background due-checker."""

    def __init__(self, path=None, on_due=None):
        self.path = Path(path or os.path.join("data", "reminders.json"))

        self.on_due = on_due

        self._lock = threading.Lock()

        self.path.parent.mkdir(parents=True, exist_ok=True)

        self._reminders = []

        self._load()

        self._thread = threading.Thread(
            target=self._loop,
            daemon=True,
        )

        self._thread.start()

    # ==================================================
    # PUBLIC API
    # ==================================================

    def add(self, text: str, when: datetime, recurring=None) -> dict:
        """Add a reminder. recurring='daily' repeats every day."""

        reminder = {
            "id": f"rem_{int(time.time() * 1000)}",
            "text": text.strip(),
            "due": when.isoformat(),
            "recurring": recurring,
            "created_at": time.time(),
            "done": False,
        }

        with self._lock:
            self._reminders.append(reminder)
            self._save()

        return {
            "success": True,
            "reminder": reminder,
            "message": (
                f"Reminder set for {when.strftime('%I:%M %p')}: {text.strip()}"
            ),
        }

    def pending(self) -> list:
        with self._lock:
            return [
                dict(reminder)
                for reminder in self._reminders
                if not reminder.get("done")
            ]

    def cancel(self, query: str) -> dict:
        """Cancel the best-matching pending reminder."""

        with self._lock:
            best = None

            for reminder in self._reminders:
                if reminder.get("done"):
                    continue

                text = reminder["text"].lower()

                if query.lower().strip() in text:
                    best = reminder
                    break

            if best is None:
                return {
                    "success": False,
                    "error": "No matching reminder was found.",
                }

            best["done"] = True
            self._save()

        return {
            "success": True,
            "message": f"Cancelled reminder: {best['text']}",
        }

    # ==================================================
    # NATURAL LANGUAGE PARSING
    # ==================================================

    _WEEKDAYS = {
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
        "friday": 4, "saturday": 5, "sunday": 6,
    }

    def parse_and_add(self, request: str) -> dict:
        """
        Parse "remind me to X at 8 PM", "in 20 minutes", "tomorrow at 7",
        "every evening at 9 remind me to X", weekday names.
        """

        request = (request or "").strip()

        if not request:
            return {
                "success": False,
                "error": "Nothing to remember to do.",
            }

        now = datetime.now()

        recurring = None

        if re.search(r"\bevery\s+(day|morning|evening|night)\b", request, re.I):
            recurring = "daily"

        request_lower = request.lower()

        # Extract the task text.
        task_match = re.search(
            r"remind me (?:to |about |that )?(.+?)(?:\s+(?:at|in|every|tomorrow|on)\b|$)",
            request,
            re.IGNORECASE,
        )

        task = task_match.group(1).strip(" .") if task_match else request

        due = None

        # "in N minutes/hours"
        rel = re.search(
            r"\bin\s+(\d+)\s+(minute|minutes|min|hour|hours|hrs)\b",
            request_lower,
        )

        if rel:
            amount = int(rel.group(1))

            if rel.group(2).startswith(("hour", "hrs")):
                due = now + timedelta(hours=amount)
            else:
                due = now + timedelta(minutes=amount)

        # "at 8 PM", "at 8:30 pm", "at 20:00"
        if due is None:
            at = re.search(
                r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b",
                request_lower,
            )

            if at:
                hour = int(at.group(1))
                minute = int(at.group(2) or 0)

                meridiem = at.group(3)

                if meridiem == "pm" and hour < 12:
                    hour += 12
                elif meridiem == "am" and hour == 12:
                    hour = 0
                elif (
                    meridiem is None
                    and hour < 12
                    and re.search(
                        r"\b(?:evening|night|tonight)\b",
                        request_lower,
                    )
                ):
                    # "every evening at 9" means 9 PM.
                    hour += 12

                due = now.replace(
                    hour=hour,
                    minute=minute,
                    second=0,
                    microsecond=0,
                )

                if due <= now:
                    due += timedelta(days=1)

        # "tomorrow"
        if due is not None and re.search(r"\btomorrow\b", request_lower):
            due += timedelta(days=1)

        # Weekday names: "on friday at 6"
        if due is None:
            for name, number in self._WEEKDAYS.items():
                if re.search(rf"\b{name}\b", request_lower):
                    days_ahead = (number - now.weekday()) % 7

                    if days_ahead == 0:
                        days_ahead = 7

                    due = (now + timedelta(days=days_ahead)).replace(
                        hour=18,
                        minute=0,
                        second=0,
                        microsecond=0,
                    )

                    at = re.search(
                        r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b",
                        request_lower,
                    )

                    if at:
                        hour = int(at.group(1))
                        minute = int(at.group(2) or 0)
                        meridiem = at.group(3)

                        if meridiem == "pm" and hour < 12:
                            hour += 12
                        elif meridiem == "am" and hour == 12:
                            hour = 0

                        due = due.replace(hour=hour, minute=minute)

                    break

        if due is None:
            return {
                "success": False,
                "error": (
                    "I couldn't work out when to remind you. "
                    "Try 'at 8 PM' or 'in 20 minutes'."
                ),
            }

        return self.add(task, due, recurring)

    # ==================================================
    # BACKGROUND CHECKER
    # ==================================================

    def _loop(self):
        while True:
            try:
                self._check_due()
            except Exception:
                pass

            time.sleep(10)

    def _check_due(self):
        now = datetime.now()

        with self._lock:
            due_now = []

            for reminder in self._reminders:
                if reminder.get("done"):
                    continue

                try:
                    due = datetime.fromisoformat(reminder["due"])
                except (ValueError, KeyError):
                    continue

                if due <= now:
                    due_now.append(reminder)

            for reminder in due_now:
                if reminder.get("recurring") == "daily":
                    reminder["due"] = (
                        datetime.fromisoformat(reminder["due"])
                        + timedelta(days=1)
                    ).isoformat()
                else:
                    reminder["done"] = True

            if due_now:
                self._save()

        if self.on_due and due_now:
            for reminder in due_now:
                try:
                    self.on_due(
                        f"Reminder: {reminder['text']}"
                    )
                except Exception:
                    pass

    # ==================================================
    # INTERNALS
    # ==================================================

    def _load(self):
        if not self.path.exists():
            return

        try:
            with open(self.path, "r", encoding="utf-8") as file:
                data = json.load(file)

            if isinstance(data, list):
                self._reminders = data

        except (json.JSONDecodeError, OSError):
            self._reminders = []

    def _save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as file:
                json.dump(self._reminders, file, indent=2)

        except OSError:
            pass
