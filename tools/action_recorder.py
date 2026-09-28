"""
Screen-observation action recorder for JARVIS.

The user performs a task manually while JARVIS watches the SCREEN —
not mouse coordinates or raw keystrokes. Every few seconds a
screenshot is taken and interpreted by the vision model into a
semantic observation: which application is open, which site or
document is visible, what changed since the last observation.

On stop, the observation timeline is converted into concrete tool
steps (open app, navigate browser, open file) and stored as a
reusable skill — so saying the trigger replays the same ACTIONS.

Computer-level actions (mouse/keyboard steps) are only recorded when
the observation explicitly names them (e.g. a form field the cursor
fills), never as raw coordinates.
"""

import os
import re
import threading
import time


class ActionRecorder:
    """
    Watch-the-screen learning mode: start -> observe -> stop ->
    replayable skill. Runs a background thread while active.
    """

    def __init__(self, vision=None, interval: float = 6.0):
        self.vision = vision
        self.interval = interval

        self.active = False
        self.observations = []

        self._thread = None
        self._lock = threading.Lock()

    # ==================================================
    # PUBLIC API
    # ==================================================

    def is_active(self) -> bool:
        return self.active

    def start(self) -> dict:
        with self._lock:
            if self.active:
                return {
                    "success": True,
                    "already_recording": True,
                    "message": "I'm already watching and learning.",
                }

            self.active = True
            self.observations = []

        self._thread = threading.Thread(
            target=self._observe_loop,
            daemon=True,
        )

        self._thread.start()

        return {
            "success": True,
            "message": (
                "Watching. Do the task on your screen now — I'm seeing "
                "which apps and sites you use, not your mouse. Say "
                "'stop learning' when you're done and I'll save it."
            ),
        }

    def stop(self) -> dict:
        with self._lock:
            was_active = self.active

            self.active = False
            observations = list(self.observations)
            self.observations = []

        if not was_active:
            return {
                "success": False,
                "error": "I wasn't recording anything.",
            }

        steps = self.build_steps(observations)

        return {
            "success": True,
            "observation_count": len(observations),
            "steps": steps,
            "observations": [
                observation.get("summary", "")
                for observation in observations
            ],
            "message": self._summarize(steps),
        }

    def cancel(self) -> dict:
        with self._lock:
            was_active = self.active

            self.active = False
            self.observations = []

        if not was_active:
            return {"success": False, "error": "Nothing was recording."}

        return {
            "success": True,
            "message": "Cancelled. Nothing was saved.",
        }

    # ==================================================
    # OBSERVATION LOOP
    # ==================================================

    def _observe_loop(self):
        while self.active:
            try:
                observation = self._observe_once()

                if observation:
                    with self._lock:
                        self.observations.append(observation)

            except Exception:
                pass

            # Sleep in short slices so stop reacts quickly.
            slept = 0.0

            while slept < self.interval and self.active:
                time.sleep(0.5)
                slept += 0.5

    def _observe_once(self) -> dict | None:
        """
        One screen sample: active window (process + title) always,
        plus a vision summary of what is visible when the vision
        provider is available.
        """

        from tools.computer_observer import ComputerObserver

        try:
            window = ComputerObserver().get_active_window()

        except Exception:
            window = {}

        if not window.get("success"):
            return None

        process = (window.get("process") or "").strip()
        title = (window.get("title") or "").strip()

        observation = {
            "time": time.time(),
            "app": process,
            "title": title,
            "summary": "",
        }

        if self.vision is not None:
            try:
                analysis = self.vision.analyze(
                    "In ONE short sentence: which app/site/file is on "
                    "screen and what is being done? Skip mouse or "
                    "keyboard details."
                )

                observation["summary"] = str(
                    analysis.get("result") or analysis.get("analysis") or ""
                )[:220]

            except Exception:
                observation["summary"] = ""

        return observation

    # ==================================================
    # OBSERVATIONS -> TOOL STEPS
    # ==================================================

    _BROWSER_PROCESSES = {
        "chrome.exe": "chrome",
        "msedge.exe": "edge",
        "firefox.exe": "firefox",
        "brave.exe": "brave",
        "opera.exe": "opera",
        "comet.exe": "comet",
    }

    _TOOL_EXES = {
        "notepad.exe": "notepad",
        "calc.exe": "calculator",
        "mspaint.exe": "paint",
        "code.exe": "vscode",
        "winword.exe": "word",
        "excel.exe": "excel",
        "powerpnt.exe": "powerpoint",
        "spotify.exe": "spotify",
        "discord.exe": "discord",
        "whatsapp.exe": "whatsapp",
        "explorer.exe": "file explorer",
    }

    # Sections of a window title that are just app branding —
    # stripping them keeps the real document/site name.
    _TITLE_SUFFIXES = (
        " - google chrome", " - mozilla firefox",
        " - microsoft edge", " - brave", " - opera",
        " - visual studio code", " - notepad",
        " - word", " - excel", " - powerpoint",
    )

    def build_steps(self, observations) -> list:
        """
        Collapse the observation timeline into ordered tool steps:
        application.open for each distinct app, browser.navigate for
        each distinct URL/site seen in a browser window title.
        """

        steps = []
        seen_apps = set()
        seen_sites = set()

        for observation in observations:
            app = (observation.get("app") or "").lower()

            if not app:
                continue

            # ---------------------------------------------
            # Browser observation -> navigation step.
            # ---------------------------------------------
            browser = self._BROWSER_PROCESSES.get(app)

            if browser:
                site = self._site_from_title(
                    observation.get("title") or ""
                )

                if site and site not in seen_sites:
                    seen_sites.add(site)

                    steps.append(
                        {
                            "tool": "browser.navigate",
                            "parameters": {"url": site},
                        }
                    )

                if browser not in seen_apps:
                    seen_apps.add(browser)

                    steps.insert(
                        0,
                        {
                            "tool": "application.open",
                            "parameters": {"application": browser},
                        },
                    )

                continue

            # ---------------------------------------------
            # Desktop application observation -> open step.
            # ---------------------------------------------
            tool_app = self._TOOL_EXES.get(app)

            if tool_app and tool_app not in seen_apps:
                seen_apps.add(tool_app)

                steps.append(
                    {
                        "tool": "application.open",
                        "parameters": {"application": tool_app},
                    }
                )

        return steps

    def _site_from_title(self, title: str) -> str | None:
        """
        Best-effort site URL from a browser window title: tab titles
        rarely contain the domain, so produce a search URL for the
        document/site name instead of a wrong deep link.
        """

        cleaned = (title or "").strip().lower()

        for suffix in self._TITLE_SUFFIXES:
            if cleaned.endswith(suffix):
                cleaned = cleaned[: -len(suffix)].strip(" -|")

        cleaned = re.sub(
            r"\s*[-|\u2013]\s*(?:\d+\s+)?(?:new\s+)?"
            r"(?:tab|incognito|window)\s*$",
            "",
            cleaned,
        ).strip()

        if not cleaned or cleaned in {"new tab", "untitled"}:
            return None

        # An explicit domain in the title -> real URL.
        domain = re.search(
            r"([a-z0-9-]+\.(?:com|org|net|edu|in|io|co|dev))",
            cleaned,
        )

        if domain:
            return "https://" + domain.group(1)

        from urllib.parse import quote

        return (
            "https://www.google.com/search?q=" + quote(cleaned)
        )

    def _summarize(self, steps) -> str:
        if not steps:
            return (
                "I watched, but couldn't identify stable steps to "
                "save — the task may have been too visual."
            )

        parts = []

        for step in steps:
            tool = step["tool"]
            parameters = step.get("parameters", {})

            if tool == "application.open":
                parts.append(
                    f"open {parameters.get('application', 'the app')}"
                )

            elif tool == "browser.navigate":
                parts.append(
                    f"go to {parameters.get('url', 'the site')}"
                )

            else:
                parts.append(tool)

        return (
            "I saw these steps: "
            + "; ".join(parts[:6])
            + "."
        )
