import inspect
import os

from typing import Callable
from tools.registry import ToolRegistry
from tools.filesystem_search import FileSystemSearcher
from tools.filesystem_observer import FileSystemObserver
from tools.computer_observer import ComputerObserver
from tools.applications import ApplicationManager
from tools.computer_controller import ComputerController
from tools.system_observer import SystemObserver
from tools.screen import ScreenController
from tools.screen_vision import ScreenVision
from assistant.memory import MemoryStore
from tools.web_search import WebSearcher
from tools.browser_control import BrowserController
from tools.skill_store import SkillStore
from tools.reminders import ReminderStore
from ai.tool_catalogue import ToolCatalogue

class ToolRuntime:
    def __init__(self):
        self._handlers: dict[str, Callable] = {}

        self.tools = ToolRegistry()
        self.filesystem_searcher = FileSystemSearcher()
        self.filesystem_observer = FileSystemObserver()
        self.computer_observer = ComputerObserver()
        self.application_manager = ApplicationManager()
        self.computer_controller = ComputerController()
        self.system_observer = SystemObserver()
        self.screen_vision = ScreenVision()
        self.memory = MemoryStore()
        self.web_searcher = WebSearcher()
        self.browser_controller = BrowserController()

        self.catalogue = ToolCatalogue()

        self.skills = SkillStore(
            tool_validator=self.catalogue.get_tool,
        )

        self.reminders = ReminderStore()

        self.register("system.cpu", self._system_cpu)
        self.register("system.memory", self._system_memory)
        self.register("system.storage", self._system_storage)
        self.register("system.battery", self._system_battery)
        self.register("system.network", self._system_network)
        self.register("system.wifi", self._system_wifi)
        self.register("system.wifi_speed", self._system_wifi_speed)
        self.register("system.bluetooth", self._system_bluetooth)
        self.register("system.gpu", self._system_gpu)
        self.register("system.laptop", self._system_laptop)

        self.register("system.lock", self._system_lock)
        self.register("system.sleep", self._system_sleep)
        self.register("system.restart", self._system_restart)
        self.register("system.shutdown", self._system_shutdown)

        self.register("system.volume", self._system_volume)
        self.register("system.app_volume", self._system_app_volume)
        self.register("system.brightness", self._system_brightness)
        self.register("system.time", self._system_time)

        self.register("memory.remember", self._memory_remember)
        self.register("memory.recall", self._memory_recall)
        self.register("memory.update", self._memory_update)
        self.register("memory.forget", self._memory_forget)

        self.register("memory.remind", self._memory_remind)
        self.register("memory.reminders", self._memory_reminders)
        self.register(
            "memory.cancel_reminder",
            self._memory_cancel_reminder,
        )

        self.register("web.search", self._web_search)
        self.register("web.fetch", self._web_fetch)

        self.register("skill.create", self._skill_create)
        self.register("skill.discover", self._skill_discover)
        self.register("skill.validate", self._skill_validate)
        self.register("skill.execute", self._skill_execute)

        self.register("screen.screenshot", self._take_screenshot)
        self.register("screen.analyze", self._analyze_screen)

        self.register(
            "computer.mouse_move",
            self._mouse_move,
        )

        self.register(
            "computer.mouse_click",
            self._mouse_click,
        )

        self.register(
            "computer.mouse_scroll",
            self._mouse_scroll,
        )

        self.register(
            "computer.keyboard_type",
            self._keyboard_type,
        )

        self.register(
            "computer.keyboard_press",
            self._keyboard_press,
        )

        self.register(
            "browser.state",
            self._get_browser_state,
        )

        self.register(
            "application.state",
            self._get_application_state,
        )

        self.register(
            "application.whatsapp_message",
            self._whatsapp_message,
        )

        self.register(
            "application.whatsapp_search",
            self._whatsapp_search,
        )

        self.register(
            "application.send_message",
            self._app_send_message,
        )

        self.register(
            "browser.close_tabs",
            self._browser_close_tabs,
        )

        self.register(
            "application.close",
            self._close_application,
        )

        self.register(
            "application.close_all",
            self._close_all_applications,
        )

        self.register(
            "computer.active_window",
            self._get_active_window,
        )

        self.register(
            "computer.running_apps",
            self._get_running_apps,
        )

        self.register(
            "computer.history",
            self._computer_history,
        )

        self.register("screen.pointer", self._screen_pointer)
        self.register("computer.driver", self._computer_driver)

        self.register("media.playback", self._media_playback)
        self.register("computer.window", self._computer_window)
        self.register("computer.clipboard", self._computer_clipboard)

        self.register("browser.open", self._open_browser)

        self.register(
            "browser.navigate",
            self._browser_navigate,
        )

        self.register("browser.refresh", self._browser_refresh)
        self.register("browser.back", self._browser_back)
        self.register("browser.forward", self._browser_forward)
        self.register("browser.read", self._browser_read)
        self.register("browser.tab_state", self._browser_tab_state)
        self.register("browser.type", self._browser_type)
        self.register("browser.scroll", self._browser_scroll)
        self.register("browser.search", self._browser_search)
        self.register("browser.click", self._browser_click)
        self.register("browser.copy", self._browser_copy)
        self.register("browser.inspect", self._browser_inspect)
        self.register("browser.media_state", self._browser_media_state)

        self.register("browser.discover", self._browser_discover)
        self.register("browser.profiles", self._browser_profiles)
        self.register("application.discover", self._application_discover)
        self.register(
            "filesystem.search_all",
            self._filesystem_search_all,
        )

        self.register(
            "system.diagnostics",
            self._system_diagnostics,
        )
        self.register(
            "computer.background_apps",
            self._computer_background_apps,
        )

        self.register("application.open", self._open_application)

        self.register(
            "filesystem.search",
            self._search_filesystem,
        )

        self.register(
            "filesystem.read",
            self._read_filesystem,
        )

        self.register(
            "filesystem.create",
            self._create_filesystem,
        )

        self.register(
            "filesystem.copy",
            self._copy_filesystem,
        )

        self.register(
            "filesystem.move",
            self._move_filesystem,
        )

        self.register(
            "filesystem.delete",
            self._delete_filesystem,
        )

        self.register(
            "filesystem.info",
            self._get_filesystem_info,
        )

        self.register(
            "filesystem.type",
            self._get_filesystem_type,
        )

        self.register(
            "filesystem.state",
            self._get_filesystem_state,
        )

        self.register(
            "filesystem.open",
            self._open_filesystem,
        )

    def _read_filesystem(
        self,
        path: str,
        max_chars: int = 100_000,
    ):
        extension = os.path.splitext(path or "")[1].lower()

        if extension == ".pdf":
            return self._read_pdf(path, max_chars)

        if extension == ".docx":
            return self._read_docx(path, max_chars)

        return self.filesystem_observer.read_file(
            path=path,
            max_chars=max_chars,
        )

    @staticmethod
    def _read_pdf(path: str, max_chars: int):
        """Extract PDF text; pypdf is an optional dependency."""

        try:
            from pypdf import PdfReader

        except ImportError:
            return {
                "success": False,
                "error": (
                    "Reading PDFs needs the optional 'pypdf' package. "
                    "Install it with: pip install pypdf"
                ),
            }

        try:
            reader = PdfReader(path)

            text = "\n".join(
                (page.extract_text() or "")
                for page in reader.pages[:50]
            )

            return {
                "success": bool(text.strip()),
                "pages": len(reader.pages),
                "text": text[:max_chars],
                "message": (
                    f"A {len(reader.pages)}-page PDF. "
                    f"It begins: {text[:200]}"
                    if text.strip()
                    else "The PDF has no extractable text."
                ),
            }

        except Exception as error:
            return {
                "success": False,
                "error": f"Could not read the PDF: {error}",
            }

    @staticmethod
    def _read_docx(path: str, max_chars: int):
        """Extract Word document text; python-docx is optional."""

        try:
            import docx

        except ImportError:
            return {
                "success": False,
                "error": (
                    "Reading .docx files needs the optional "
                    "'python-docx' package: pip install python-docx"
                ),
            }

        try:
            document = docx.Document(path)

            text = "\n".join(
                paragraph.text
                for paragraph in document.paragraphs
                if paragraph.text.strip()
            )

            return {
                "success": bool(text.strip()),
                "text": text[:max_chars],
                "message": (
                    f"The document begins: {text[:200]}"
                    if text.strip()
                    else "The document appears to be empty."
                ),
            }

        except Exception as error:
            return {
                "success": False,
                "error": f"Could not read the document: {error}",
            }


    def _create_filesystem(
        self,
        path: str,
        content: str = "",
        directory: bool = False,
        overwrite: bool = False,
    ):
        return self.filesystem_observer.create(
            path=path,
            content=content,
            directory=directory,
            overwrite=overwrite,
        )


    def _copy_filesystem(
        self,
        source: str,
        destination: str,
    ):
        return self.filesystem_observer.copy(
            source=source,
            destination=destination,
        )


    def _move_filesystem(
        self,
        source: str,
        destination: str,
    ):
        return self.filesystem_observer.move(
            source=source,
            destination=destination,
        )


    def _delete_filesystem(self, path: str):
        return self.filesystem_observer.delete(path)


    def _get_filesystem_type(self, path: str):
        return self.filesystem_observer.get_type(path)


    def _get_filesystem_state(
        self,
        path: str | None = None,
    ):
        return self.filesystem_observer.get_state(path)


    def _open_filesystem(self, path: str):
        return self.filesystem_observer.open_path(path)

    def _system_lock(self):
        return self.tools.lock()

    def _system_volume(self, action: str = "get", amount: int | None = None):
        system = self.tools.system

        if action == "set" and amount is not None:
            return system.set_volume(amount)

        if action == "increase":
            return system.increase_volume(amount or 10)

        if action == "decrease":
            return system.decrease_volume(amount or 10)

        if action == "mute":
            return system.mute()

        if action == "unmute":
            return system.unmute()

        volume = system.get_volume()

        return {
            "success": True,
            "volume_percent": volume,
            "message": f"The volume is at {volume} percent.",
        }

    def _system_app_volume(
        self,
        application: str = "",
        action: str = "get",
        amount: int | None = None,
    ):
        """Per-application volume (Windows Volume Mixer session)."""

        system = self.tools.system

        application = (application or "").strip()

        if not application:
            return {
                "success": False,
                "error": (
                    "I need to know which application's volume to "
                    "adjust, like Chrome or Spotify."
                ),
            }

        # 'chrome' -> the app that owns the YouTube video.
        if action == "get":
            return system.get_app_volume(application)

        if action == "set" and amount is not None:
            return system.set_app_volume(application, amount)

        if action == "increase":
            return system.adjust_app_volume(application, amount or 10)

        if action == "decrease":
            return system.adjust_app_volume(application, -(amount or 10))

        return system.get_app_volume(application)

    def _system_brightness(
        self,
        action: str = "get",
        amount: int | None = None,
    ):
        system = self.tools.system

        if action == "set" and amount is not None:
            return system.set_brightness(amount)

        if action == "increase":
            return system.increase_brightness(amount or 10)

        if action == "decrease":
            return system.decrease_brightness(amount or 10)

        brightness = system.get_brightness()

        return {
            "success": True,
            "brightness_percent": brightness,
            "message": f"The brightness is at {brightness} percent.",
        }

    def _memory_remember(self, information: str):
        return self.memory.remember(information)

    def _memory_recall(self, query: str):
        return self.memory.recall(query)

    def _memory_update(self, query: str, information: str):
        return self.memory.update(query, information)

    def _memory_forget(self, query: str):
        return self.memory.forget(query)

    def _memory_remind(self, request: str):
        return self.reminders.parse_and_add(request)

    def _memory_reminders(self):
        pending = self.reminders.pending()

        if not pending:
            return {
                "success": True,
                "reminders": [],
                "message": "You have no pending reminders.",
            }

        lines = [
            f"{reminder['text']} at {reminder['due'][:16].replace('T', ' ')}"
            for reminder in pending
        ]

        return {
            "success": True,
            "reminders": pending,
            "message": "Pending reminders: " + "; ".join(lines),
        }

    def _memory_cancel_reminder(self, query: str):
        return self.reminders.cancel(query or "")

    def _web_search(self, query: str):
        return self.web_searcher.search(query)

    def _web_fetch(self, url: str):
        return self.web_searcher.fetch(url)


    def _system_sleep(self):
        return self.tools.sleep()


    def _system_restart(self):
        return self.tools.system.restart()


    def _system_shutdown(self):
        return self.tools.system.shutdown()

    def _analyze_screen(self, question: str):
        return self.screen_vision.analyze(question)

    def _application_discover(self):
        applications = sorted(self.application_manager.applications)

        return {
            "success": True,
            "applications": applications,
            "count": len(applications),
            "message": (
                f"I found {len(applications)} installed applications."
            ),
        }

    def _computer_background_apps(self):
        import psutil

        seen = set()

        for process in psutil.process_iter(["name"]):
            try:
                name = (process.info["name"] or "").lower()

                if name:
                    seen.add(name)

            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        return {
            "success": True,
            "count": len(seen),
            "applications": sorted(seen)[:60],
            "message": (
                f"There are about {len(seen)} distinct background "
                "processes running."
            ),
        }

    def _browser_discover(self):
        self.tools.browsers.refresh_browsers()

        names = [
            browser["name"]
            for browser in self.tools.browsers.browsers.values()
        ]

        if not names:
            return {
                "success": True,
                "browsers": [],
                "message": "I couldn't find any installed browsers.",
            }

        return {
            "success": True,
            "browsers": names,
            "message": "Installed browsers: " + ", ".join(names) + ".",
        }

    def _browser_profiles(self, browser: str):
        profiles = self.tools.browsers.get_profiles(browser)

        names = []

        for profile in profiles:
            names.append(
                getattr(profile, "name", None)
                or str(profile)
            )

        if not names:
            return {
                "success": False,
                "error": (
                    f"I couldn't find any profiles for {browser}."
                ),
            }

        return {
            "success": True,
            "profiles": names,
            "message": (
                f"{browser} profiles: " + ", ".join(names) + "."
            ),
        }

    def _skill_create(self, name: str, description: str = "", steps=None):
        return self.skills.create(
            name,
            description,
            steps or [],
        )

    def _skill_discover(self, query: str = ""):
        return self.skills.discover(query)
    
    def _skill_validate(self, skill: dict):
        return self.skills.validate(skill)

    def _skill_execute(self, name: str):
        skill = self.skills.get(name)

        if skill is None:
            return {
                "success": False,
                "error": f"No skill named {name} is saved.",
            }

        return self._run_skill_steps(skill)

    def _run_skill_steps(self, skill: dict) -> dict:
        """
        Execute a skill's steps sequentially. Confirmation-required
        tools are never auto-executed; they are reported as skipped.
        """

        executed = []
        skipped = []
        failures = []

        # Gated steps as (tool, parameters) tuples, surfaced for the
        # confirmation flow instead of being silently dropped.
        skipped_steps = []

        catalogue = self.catalogue

        for step in skill["steps"]:
            tool = step["tool"]
            parameters = step.get("parameters", {})

            definition = catalogue.get_tool(tool)

            if definition is not None and definition.confirmation_required:
                skipped.append(tool)
                skipped_steps.append((tool, parameters))
                continue
            
            result = self.execute(tool, parameters)

            if not result.get("success"):
                failures.append(f"{tool}: {result.get('result', 'error')}")
                break

            executed.append(tool)

        if failures:
            message = (
                f"Ran {len(executed)} steps of {skill['display_name']} "
                f"but stopped at a failure: {failures[0]}"
            )
        elif skipped:
            message = (
                f"Ran {skill['display_name']}: completed "
                f"{len(executed)} steps; skipped {', '.join(skipped)} "
                "(confirmation required)."
            )
        else:
            message = (
                f"Ran {skill['display_name']}: "
                f"all {len(executed)} steps completed."
            )

        return {
            "success": not failures,
            "executed": executed,
            "skipped": skipped,
            "skipped_steps": skipped_steps,
            "message": message,
        }

    def _take_screenshot(self):
        return self.tools.take_screenshot()

    def _system_cpu(self):
        return self.system_observer.get_cpu()


    def _system_memory(self):
        return self.system_observer.get_memory()


    def _system_storage(self):
        return self.system_observer.get_storage()


    def _system_battery(self):
        return self.system_observer.get_battery()


    def _system_network(self):
        return self.system_observer.get_network()


    def _system_wifi(self):
        return self.system_observer.get_wifi()


    def _system_wifi_speed(self):
        return self.system_observer.get_wifi_speed()


    def _system_bluetooth(self):
        return self.system_observer.get_bluetooth()


    def _system_gpu(self):
        return self.system_observer.get_gpu()


    def _system_time(self):
        from datetime import datetime

        now = datetime.now()

        return {
            "success": True,
            "time": now.strftime("%I:%M %p").lstrip("0"),
            "date": now.strftime("%A, %d %B %Y"),
            "message": (
                f"It's {now.strftime('%I:%M %p').lstrip('0')} on "
                f"{now.strftime('%A, %d %B %Y')}."
            ),
        }

    def _system_laptop(self):
        return self.system_observer.get_laptop_state()

    def _mouse_move(self, x: int, y: int):
        return self.computer_controller.move_mouse(x, y)


    def _mouse_click(self, button: str = "left", clicks: int = 1):
        # `clicks` is declared in the catalogue; the controller API
        # only supports single clicks, so it is accepted and ignored.
        return self.computer_controller.click_mouse(button)


    def _mouse_scroll(self, amount: int):
        return self.computer_controller.scroll_mouse(amount)


    def _keyboard_type(self, text: str, interval: float = 0.01):
        return self.computer_controller.type_text(text, interval)


    def _keyboard_press(self, key: str):
        return self.computer_controller.press_key(key)

    def _get_browser_state(self, name: str):
        return self.tools.browsers.get_browser_state(name)

    def _get_application_state(self, name: str):
        return self.application_manager.get_application_state(name)

    def _close_application(self, application: str):
        # Parameter name matches the catalogue's "application" key:
        # execute() calls handlers with keyword arguments, so a name
        # drift here surfaces as a raw TypeError to the user.
        return self.application_manager.close_application(
            (application or "").strip()
        )

    def _close_all_applications(self):
        """
        Gracefully close every visible running app, one at a time.
        The Windows shell (explorer) and JARVIS itself are protected.
        """

        running = self.computer_observer.get_running_applications()

        if not running.get("success"):
            return running

        protected = {
            "explorer.exe", "python.exe", "pythonw.exe",
            "code.exe", "cmd.exe", "powershell.exe",
            "windowsterminal.exe", "textinputhost.exe",
            "searchhost.exe", "shellexperiencehost.exe",
            "startmenuexperiencehost.exe",
            "applicationframehost.exe",
            "systemsettings.exe",
        }

        closed = []
        refused = []

        for app in running.get("applications", []):
            name = (app.get("name") or "").strip()

            if not name or name.lower() in protected:
                continue

            result = self.application_manager.close_application(
                name.removesuffix(".exe")
            )

            if result.get("success") or result.get("closed"):
                closed.append(name.removesuffix(".exe"))

            else:
                refused.append(name.removesuffix(".exe"))

        if not closed and not refused:
            return {
                "success": True,
                "message": "No user applications were running.",
            }

        parts = []

        if closed:
            parts.append(
                "Closed: " + ", ".join(sorted(set(closed)))
            )

        if refused:
            parts.append(
                "Could not close (may need saving first): "
                + ", ".join(sorted(set(refused)))
            )

        return {
            "success": True,
            "closed": closed,
            "refused": refused,
            "message": ". ".join(parts) + ".",
        }

    def _computer_history(self, period: str = "today"):
        """
        Time Machine: what was the user doing during a past period?
        Reconstructs the timeline from the activity log — commands,
        apps opened, tools run.
        """

        import json as _json

        from datetime import datetime, timedelta

        period = (period or "today").lower().strip()

        now = datetime.now()

        weekdays = {
            "monday": 0, "tuesday": 1, "wednesday": 2,
            "thursday": 3, "friday": 4, "saturday": 5,
            "sunday": 6,
        }

        if period in weekdays:
            days_back = (now.weekday() - weekdays[period]) % 7

            if days_back == 0:
                days_back = 7  # "last tuesday" on a tuesday

            day_start = (
                now - timedelta(days=days_back)
            ).replace(hour=0, minute=0, second=0, microsecond=0)

            day_end = day_start + timedelta(days=1)

            label = f"last {period.title()}"

        elif period == "yesterday":
            day_start = (
                now - timedelta(days=1)
            ).replace(hour=0, minute=0, second=0, microsecond=0)

            day_end = day_start + timedelta(days=1)

            label = "yesterday"

        else:
            day_start = now.replace(
                hour=0, minute=0, second=0, microsecond=0
            )

            day_end = day_start + timedelta(days=1)

            label = "today"

        records = []

        try:
            path = os.path.join("data", "activity.jsonl")

            with open(path, "r", encoding="utf-8") as file:
                for line in file:
                    try:
                        record = _json.loads(line)

                    except _json.JSONDecodeError:
                        continue

                    ts = record.get("ts")

                    if not ts:
                        continue

                    when = datetime.fromtimestamp(ts)

                    if day_start <= when < day_end:
                        records.append((when, record))

        except OSError:
            return {
                "success": False,
                "error": "I couldn't read my activity history.",
            }

        if not records:
            return {
                "success": True,
                "message": (
                    f"I have no record of {label} — my log starts "
                    "relatively recently, sir."
                ),
            }

        requests = [
            str(record.get("request", "")).strip()
            for when, record in records
            if record.get("kind") == "request"
            and record.get("request")
        ]

        tools_run = [
            str(record.get("tool", "")).strip()
            for when, record in records
            if record.get("kind") == "tool_executed"
            and record.get("tool")
        ]

        parts = []

        if requests:
            shown = requests[:6]

            parts.append(
                "you asked me to: "
                + "; ".join(shown)
            )

        if tools_run:
            from collections import Counter

            counts = Counter(tools_run)

            top = ", ".join(
                f"{name} x{count}"
                for name, count in counts.most_common(4)
            )

            parts.append(f"I ran: {top}")

        if not parts:
            return {
                "success": True,
                "message": f"Nothing eventful happened {label}, sir.",
            }

        first = records[0][0].strftime("%I:%M %p").lstrip("0")
        last = records[-1][0].strftime("%I:%M %p").lstrip("0")

        return {
            "success": True,
            "requests": requests,
            "tools": tools_run,
            "message": (
                f"On {label} between {first} and {last}, "
                + ". ".join(parts)
                + "."
            ),
        }

    _DRIVER_REFUSALS = (
        "payment", "pay", "checkout", "card", "bank", "password",
        "delete", "transfer", "purchase", "buy",
    )

    def _screen_pointer(self, target: str):
        """
        The Pointer: locate a control on screen via vision and report
        its position as screen coordinates plus a spoken location.
        """

        target = (target or "").strip()

        if not target:
            return {
                "success": False,
                "error": "What should I look for on screen, sir?",
            }

        vision = self.screen_vision

        if vision is None:
            return {
                "success": False,
                "error": "My vision system is unavailable right now.",
            }

        analysis = vision.analyze(
            f"Locate '{target}' on this screen. Reply in EXACTLY this "
            "format: POSITION: <x-percent>, <y-percent> | NAME: <the "
            "control's visible label> | SAY: <one short butler-style "
            "line telling the user where it is, like 'top right, next "
            "to the address bar'>. If it is not visible, reply exactly "
            "NOTVISIBLE."
        )

        text = ""

        if isinstance(analysis, dict):
            text = str(
                analysis.get("result") or analysis.get("analysis") or ""
            )

        elif isinstance(analysis, str):
            text = analysis

        if "NOTVISIBLE" in text.upper():
            return {
                "success": False,
                "error": (
                    f"I can't see '{target}' on the current screen, sir. "
                    "Perhaps open the right window first?"
                ),
            }

        import re as _re

        pos = _re.search(
            r"POSITION:\s*(\d{1,3})\s*%?\s*,\s*(\d{1,3})\s*%?",
            text,
        )

        say = ""

        say_match = _re.search(
            r"SAY:\s*(.+)",
            text,
            _re.IGNORECASE,
        )

        if say_match:
            say = say_match.group(1).strip()

        if pos:
            x_pct = int(pos.group(1))
            y_pct = int(pos.group(2))

            # Describe location in natural terms.
            horizontal = (
                "left" if x_pct < 35
                else "right" if x_pct > 65
                else "middle"
            )

            vertical = (
                "top" if y_pct < 35
                else "bottom" if y_pct > 65
                else "middle"
            )

            location = (
                f"{vertical} {horizontal}".replace("middle middle", "center")
            )

            spoken = say or (
                f"{location} of the screen, sir — right there."
            )

            return {
                "success": True,
                "x_percent": x_pct,
                "y_percent": y_pct,
                "location": location,
                "message": spoken,
            }

        # No coordinates parsed: still return the raw description.
        return {
            "success": True,
            "message": (
                text[:200] or "I found something, but I couldn't pin the "
                "exact position, sir."
            ),
        }

    def _computer_driver(self, task: str, confirmed: bool = False):
        """
        The Careful Driver: perform a UI task step by step with the
        mouse/keyboard, narrating. The packs' laws, verbatim in spirit:
        plan first, one step at a time, stop on command, hard refusals.
        """

        task = (task or "").strip().lower()

        if not task:
            return {
                "success": False,
                "error": "What should I take over and do, sir?",
            }

        # HARD REFUSALS — no exceptions (the packs are explicit).
        for banned in self._DRIVER_REFUSALS:
            if banned in task:
                return {
                    "success": False,
                    "error": (
                        "That one I won't drive, sir — payments, passwords, "
                        "and deletions stay in human hands. "
                        "I can draft or open the page instead."
                    ),
                }

        # The vision model produces the plan; execution is bounded.
        vision = self.screen_vision

        plan_text = ""

        if vision is not None:
            analysis = vision.analyze(
                f"The user wants me to: {task}. Look at the screen and "
                "produce a short ordered plan of 2-5 concrete UI steps "
                "(click what, type what). Reply with the plan as "
                "numbered lines only."
            )

            if isinstance(analysis, dict):
                plan_text = str(
                    analysis.get("result") or analysis.get("analysis") or ""
                )

            elif isinstance(analysis, str):
                plan_text = analysis

        plan_steps = [
            line.strip()
            for line in (plan_text or "").splitlines()
            if line.strip() and line.strip()[0].isdigit()
        ][:5]

        if not confirmed:
            return {
                "success": True,
                "plan": plan_steps
                or [
                    "I couldn't see a clear path on screen, sir — "
                    "describe the target a little more?"
                ],
                "message": (
                    "Here's my plan: "
                    + "; ".join(plan_steps[:4])
                    + ". Say 'go' and I'll drive."
                ),
            }

        # Confirmed: execute with bounded, narrated steps using the
        # existing computer controller (click/type via automation).
        performed = []

        controller = self.computer_controller

        for index, step in enumerate(plan_steps, start=1):
            # Bounded tool budget: at most 5 steps, never re-planned.
            try:
                result = self.execute(
                    "screen.analyze",
                    {
                        "question": (
                            f"Next step is: {step}. Reply ONLY with the "
                            "x,y coordinates in percent of the target to "
                            "click, as 'POSITION: x, y', or SKIP."
                        )
                    },
                )

                step_text = str(result.get("result", ""))

                import re as _re

                pos = _re.search(
                    r"POSITION:\s*(\d{1,3})\s*,\s*(\d{1,3})",
                    step_text,
                )

                if not pos:
                    performed.append(f"skipped: {step[:40]}")
                    continue

                x_pct = int(pos.group(1))
                y_pct = int(pos.group(2))

                from app.config import get as _get

                screen_w = _get("screen", "width") or 1920
                screen_h = _get("screen", "height") or 1080

                controller.move_mouse(
                    int(screen_w * x_pct / 100),
                    int(screen_h * y_pct / 100),
                )
                controller.click_mouse("left")

                import time as _time

                _time.sleep(0.8)

                performed.append(f"clicked: {step[:40]}")

            except Exception as error:
                performed.append(f"failed: {step[:40]} ({error})")
                break

        return {
            "success": True,
            "performed": performed,
            "message": (
                "Done, sir — "
                + "; ".join(performed[:4])
                + ". Your screen is yours again."
            ),
        }

    # ------------------------------------------------------
    # MEDIA: virtual key-codes (KEYEVENTF_*) via SendInput — works
    # on Spotify, browsers, and any player honoring media keys.
    # ------------------------------------------------------

    _MEDIA_VK = {
        "play": 0xB3,      # VK_MEDIA_PLAY_PAUSE
        "pause": 0xB3,
        "toggle": 0xB3,
        "next": 0xB0,      # VK_MEDIA_NEXT_TRACK
        "previous": 0xB1,  # VK_MEDIA_PREV_TRACK
    }

    def _media_playback(self, action: str = "toggle"):
        import ctypes

        action = (action or "toggle").lower().strip()

        vk = self._MEDIA_VK.get(action)

        if vk is None:
            return {
                "success": False,
                "error": (
                    f"I can't {action} — play, pause, next or "
                    "previous are the media controls."
                ),
            }

        user32 = ctypes.windll.user32

        user32.keybd_event(vk, 0, 0, 0)
        user32.keybd_event(vk, 0, 2, 0)  # KEYEVENTF_KEYUP

        return {
            "success": True,
            "message": {
                "play": "Playing, sir.",
                "pause": "Paused.",
                "toggle": "Toggled playback.",
                "next": "Next track.",
                "previous": "Previous track.",
            }.get(action, "Done."),
        }

    # ------------------------------------------------------
    # WINDOW MANAGEMENT: focus/minimize/maximize/close by title.
    # ------------------------------------------------------

    def _computer_window(self, action: str = "focus", target: str = ""):
        import win32con
        import win32gui

        action = (action or "focus").lower().strip()
        target = (target or "").strip()

        # minimize_all: shell command, no enumeration needed.
        if action == "minimize_all":
            import subprocess

            subprocess.Popen(
                [
                    "powershell", "-NoProfile", "-Command",
                    "(New-Object -ComObject Shell.Application)"
                    ".MinimizeAll()",
                ],
            )

            return {
                "success": True,
                "message": "Desktop's clear, sir.",
            }

        if not target:
            return {
                "success": False,
                "error": "Which window should I act on, sir?",
            }

        needle = target.lower()
        matches = []

        def collect(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd):
                return True

            title = win32gui.GetWindowText(hwnd)

            if title and needle in title.lower():
                matches.append((hwnd, title))

            return True

        win32gui.EnumWindows(collect, None)

        if not matches:
            return {
                "success": False,
                "error": (
                    f"I can't find a window matching '{target}', sir."
                ),
            }

        hwnd, title = matches[0]

        try:
            if action == "focus":
                try:
                    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)

                except Exception:
                    pass

                win32gui.SetForegroundWindow(hwnd)

                return {
                    "success": True,
                    "message": f"{title[:40]} is now front and center.",
                }

            if action == "minimize":
                win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)

                return {
                    "success": True,
                    "message": f"Minimized {title[:40]}.",
                }

            if action == "maximize":
                win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)

                return {
                    "success": True,
                    "message": f"Maximized {title[:40]}.",
                }

            if action == "close":
                win32gui.PostMessage(
                    hwnd,
                    win32con.WM_CLOSE,
                    0,
                    0,
                )

                return {
                    "success": True,
                    "message": f"Closing {title[:40]} — gently.",
                }

        except Exception as error:
            return {
                "success": False,
                "error": f"The window fought back: {error}",
            }

        return {
            "success": False,
            "error": (
                f"'{action}' isn't a window move I know — focus, "
                "minimize, maximize or close."
            ),
        }

    # ------------------------------------------------------
    # CLIPBOARD read/write.
    # ------------------------------------------------------

    def _computer_clipboard(self, action: str = "read", text: str = ""):
        import win32clipboard
        import win32con

        action = (action or "read").lower().strip()

        if action == "write":
            if not text:
                return {
                    "success": False,
                    "error": "What should go on the clipboard, sir?",
                }

            win32clipboard.OpenClipboard()

            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardText(
                    text,
                    win32con.CF_UNICODETEXT,
                )

            finally:
                win32clipboard.CloseClipboard()

            return {
                "success": True,
                "message": "Copied to the clipboard, sir.",
            }

        try:
            win32clipboard.OpenClipboard()

            try:
                data = win32clipboard.GetClipboardData(
                    win32con.CF_UNICODETEXT,
                )

            finally:
                win32clipboard.CloseClipboard()

        except Exception:
            return {
                "success": False,
                "error": (
                    "The clipboard is empty or holds something I "
                    "can't read, sir."
                ),
            }

        data = (data or "").strip()

        if not data:
            return {
                "success": False,
                "error": "The clipboard is empty, sir.",
            }

        preview = data[:180] + ("..." if len(data) > 180 else "")

        return {
            "success": True,
            "text": data,
            "message": f"Your clipboard reads: {preview}",
        }

    def register(self, name: str, handler: Callable):
        self._handlers[name] = handler

    def _get_active_window(self):
        return self.computer_observer.get_active_window()


    def _get_running_apps(self):
        return self.computer_observer.get_running_applications()

    def has_tool(self, name: str) -> bool:
        return name in self._handlers

    def execute(self, name: str, parameters: dict):
        handler = self._handlers.get(name)

        if handler is None:
            return {
                "success": False,
                "result": f"Tool '{name}' is not registered.",
            }

        try:
            result = handler(
                **self._align_parameters(handler, parameters),
            )

            return {
                "success": True,
                "result": result,
            }

        except Exception as error:
            return {
                "success": False,
                "result": str(error),
            }

    @staticmethod
    def _align_parameters(handler: Callable, parameters: dict) -> dict:
        """
        Map a planner-supplied parameter dict onto the handler's real
        signature: unknown keys are dropped, and missing required
        arguments are filled from the dropped values in order. This
        keeps catalogue/handler name drift (e.g. 'application' vs
        'name') from surfacing as a raw TypeError to the user.
        """

        parameters = parameters or {}

        if not parameters:
            return {}

        try:
            signature = inspect.signature(handler)

        except (TypeError, ValueError):
            return parameters

        accepted = {}
        required = []

        for parameter in signature.parameters.values():
            if parameter.kind in (
                parameter.VAR_POSITIONAL,
                parameter.VAR_KEYWORD,
            ):
                # *args/**kwargs absorb everything as-is.
                return parameters

            accepted[parameter.name] = parameter

            if parameter.default is parameter.empty:
                required.append(parameter.name)

        known = {
            key: value
            for key, value in parameters.items()
            if key in accepted
        }

        unknown = {
            key: value
            for key, value in parameters.items()
            if key not in accepted
        }

        for parameter_name in required:
            if parameter_name not in known and unknown:
                fallback = next(iter(unknown))

                known[parameter_name] = unknown.pop(fallback)

        return known

    def _open_application(self, application: str):
        name = (application or "").strip()

        if not name:
            return {
                "success": False,
                "error": "No application name was provided.",
            }

        success = self.application_manager.open_application(name)

        if not success:
            import difflib

            suggestions = difflib.get_close_matches(
                name.lower(),
                list(self.application_manager.applications.keys()),
                n=3,
                cutoff=0.5,
            )

            if suggestions:
                return {
                    "success": False,
                    "error": (
                        f"I couldn't find an application called {name}. "
                        "The closest installed ones are: "
                        + ", ".join(suggestions)
                        + "."
                    ),
                }

            return {
                "success": False,
                "error": (
                    f"I couldn't find an application called {name}."
                ),
            }

        return {
            "success": True,
            "message": f"Opening {name}.",
        }

    def _whatsapp_message(self, contact: str, message: str):
        from tools.whatsapp import send_message

        return send_message(contact, message)

    def _whatsapp_search(self, query: str):
        from tools.whatsapp import search_contacts

        return search_contacts(query)

    def _app_send_message(self, app: str, contact: str, message: str):
        from tools.app_messenger import send_message_in_app

        return send_message_in_app(app, contact, message)

    def _browser_close_tabs(self, count: int = 3):
        """
        Close recent browser tabs: first the tabs JARVIS opened this
        session (tracked URLs), then plain Ctrl+W presses. Bounded so
        a stuck loop can never close the user's whole session.
        """

        count = max(1, min(int(count or 3), 10))

        controller = self.browser_controller

        if not controller.focus_browser():
            return {
                "success": False,
                "error": "No browser window is available to close tabs in.",
            }

        closed = 0

        # Step 1: close JARVIS-opened tabs by navigating each away?
        # Simpler and safer: press Ctrl+W repeatedly on the active tab
        # after focusing the browser; Chrome closes the current tab.
        import time as _time

        for _ in range(count):
            before = None

            try:
                state = controller.tab_state()
                before = state.get("url", "")

            except Exception:
                pass

            controller._combo(controller.VK_CONTROL, ord("W"))

            _time.sleep(0.7)

            after = ""

            try:
                state = controller.tab_state()
                after = state.get("url", "")

            except Exception:
                pass

            if before and after and before == after:
                # Last tab: Chrome won't close it (window persists).
                break

            closed += 1

        if closed == 0:
            return {
                "success": False,
                "error": "No tabs could be closed (maybe only one is open).",
            }

        return {
            "success": True,
            "message": f"Closed {closed} browser tab(s).",
        }

    def _browser_navigate(self, url: str):
        result = self.browser_controller.navigate(url)

        # Browser window exists and navigation worked (or failed for a
        # non-window reason): pass the result through.
        if result.get("success"):
            return result

        error = str(result.get("error", ""))

        # No browser window: open the URL in the default browser,
        # then attempt verified navigation once it has started.
        if "No browser window" in error or not self._browser_running():
            import subprocess

            subprocess.Popen(["cmd", "/c", "start", "", url])

            import time

            time.sleep(3.0)

            retry = self.browser_controller.navigate(url)

            if retry.get("success"):
                message = retry.get("message") or f"Opened {url}."

                return {
                    "success": True,
                    "verified": retry.get("verified", False),
                    "message": (
                        f"I opened your default browser. {message}"
                    ),
                }

            return {
                "success": True,
                "message": f"I opened {url} in your default browser.",
            }

        return result

    def _browser_running(self) -> bool:
        import psutil

        browser_processes = {
            "chrome.exe", "msedge.exe", "firefox.exe", "brave.exe",
            "opera.exe", "comet.exe", "safari.exe", "browser.exe",
        }

        for process in psutil.process_iter(["name"]):
            try:
                if (process.info["name"] or "").lower() in browser_processes:
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        return False

    def _browser_refresh(self):
        return self.browser_controller.refresh()

    def _browser_back(self):
        return self.browser_controller.back()

    def _browser_forward(self):
        return self.browser_controller.forward()

    def _browser_read(self, max_chars: int = 4000):
        return self.browser_controller.read(max_chars)

    def _browser_tab_state(self):
        return self.browser_controller.tab_state()

    def _browser_type(
        self,
        text: str,
        press_enter: bool = False,
        target: str = None,
    ):
        # `target` is declared in the catalogue; typing goes to the
        # focused element, so it is accepted but not needed here.
        return self.browser_controller.type_text(text, press_enter)

    def _browser_scroll(self, amount: int = 3):
        return self.browser_controller.scroll(amount)

    def _browser_search(self, site: str, query: str):
        """
        Search ON a site (opens the site's own search page).
        Falls back to browser.navigate-style Google search when no
        site is recognizable.
        """

        site = (site or "").strip().lower()

        # Detect the site from common names if the agent passed the
        # whole phrase instead of extracting it.
        for known in self.browser_controller._SEARCH_ENDPOINTS:
            if known in site or site in known:
                site = known
                break

        # Strip leading filler words like "search youtube for".
        import re as _re

        query = _re.sub(
            r"^(?:search\s+(?:youtube|google|the web|for)\s*)+",
            "",
            (query or ""),
            flags=_re.IGNORECASE,
        )

        if not site:
            # Generic web search: open the search results page.
            from urllib.parse import quote

            return self.browser_controller.navigate(
                "https://www.google.com/search?q=" + quote(query)
            )

        return self.browser_controller.search_site(site, query)

    def _browser_click(self, target: str):
        return self.browser_controller.click_target(target)

    def _browser_copy(self, target: str = None):
        return self.browser_controller.copy_target(target)

    def _browser_inspect(self):
        if not self.browser_controller.focus_browser():
            return {
                "success": False,
                "error": "No browser window is available to inspect.",
            }

        return {
            "success": True,
            "result": self.screen_vision.analyze(
                "List the main interactive elements currently visible on "
                "this webpage (buttons, links, search boxes, menus), as a "
                "short comma-separated list. If none are visible, say "
                "'No interactive elements visible'."
            ),
        }

    def _browser_media_state(self):
        if not self.browser_controller.focus_browser():
            return {
                "success": False,
                "error": "No browser window is available.",
            }

        return {
            "success": True,
            "result": self.screen_vision.analyze(
                "Is a video or audio currently playing on this webpage? "
                "Answer 'playing', 'paused', 'not playing', or 'no media "
                "visible'."
            ),
        }
                

    def _open_browser(self, browser: str, profile: str | None = None):
        success = self.tools.open_browser(browser, profile)

        if not success:
            return f"Could not open {browser}."

        if profile:
            return f"Opened {browser} with the {profile} profile."

        return f"Opened {browser}."

    def _system_diagnostics(self):
        """
        Inspect JARVIS's own subsystems (context 69) and report the
        first likely problem, plus an overall status summary.
        """

        checks = []

        # Provider / API connectivity.
        try:
            import os as _os

            if not _os.getenv("GROQ_API_KEY"):
                checks.append(
                    {
                        "component": "model provider",
                        "ok": False,
                        "detail": "GROQ_API_KEY is not set in .env",
                    }
                )
            else:
                checks.append(
                    {
                        "component": "model provider",
                        "ok": True,
                        "detail": "API key configured",
                    }
                )

        except Exception as error:
            checks.append(
                {
                    "component": "model provider",
                    "ok": False,
                    "detail": str(error),
                }
            )

        # Microphone.
        try:
            import sounddevice as sd

            devices = sd.query_devices()

            inputs = [
                device
                for device in devices
                if device.get("max_input_channels", 0) > 0
            ]

            checks.append(
                {
                    "component": "microphone",
                    "ok": bool(inputs),
                    "detail": (
                        f"{len(inputs)} input device(s) found"
                        if inputs
                        else "No input devices"
                    ),
                }
            )

        except Exception as error:
            checks.append(
                {
                    "component": "microphone",
                    "ok": False,
                    "detail": str(error),
                }
            )

        # Network connectivity. Any HTTP response (even 403) proves
        # reachability; only DNS/socket failures mean the network is down.
        try:
            import urllib.error
            import urllib.request

            try:
                urllib.request.urlopen(
                    "https://api.groq.com",
                    timeout=5,
                )

            except urllib.error.HTTPError:
                # Server answered: network is fine.
                pass

            checks.append(
                {
                    "component": "network",
                    "ok": True,
                    "detail": "api.groq.com reachable",
                }
            )

        except Exception as error:
            checks.append(
                {
                    "component": "network",
                    "ok": False,
                    "detail": str(error)[:80],
                }
            )

        # Tool registry.
        try:
            count = len(self._handlers)

            checks.append(
                {
                    "component": "tool registry",
                    "ok": count > 40,
                    "detail": f"{count} tools registered",
                }
            )

        except Exception as error:
            checks.append(
                {
                    "component": "tool registry",
                    "ok": False,
                    "detail": str(error),
                }
            )

        # Memory store.
        try:
            facts = len(self.memory.all_facts())

            checks.append(
                {
                    "component": "memory",
                    "ok": True,
                    "detail": f"{facts} fact(s) stored",
                }
            )

        except Exception as error:
            checks.append(
                {
                    "component": "memory",
                    "ok": False,
                    "detail": str(error),
                }
            )

        # Skill store.
        try:
            skills = len(self.skills.discover("").get("skills", []))

            checks.append(
                {
                    "component": "skills",
                    "ok": True,
                    "detail": f"{skills} skill(s) saved",
                }
            )

        except Exception as error:
            checks.append(
                {
                    "component": "skills",
                    "ok": False,
                    "detail": str(error),
                }
            )

        problems = [
            check
            for check in checks
            if not check["ok"]
        ]

        if problems:
            first = problems[0]
            summary = (
                f"The problem looks like the {first['component']}: "
                f"{first['detail']}."
            )
        else:
            summary = "All my systems are healthy."

        return {
            "success": True,
            "checks": checks,
            "problems": problems,
            "message": summary,
        }

    def _filesystem_search_all(self, query: str):
        """
        Unified search across files, applications, skills, and memory.
        Returns a categorized summary (context 53).
        """

        query = (query or "").strip()

        if not query:
            return {
                "success": False,
                "error": "No search query was provided.",
            }

        files = self.filesystem_searcher.search(query)

        lower = query.lower()

        applications = [
            name
            for name in self.application_manager.applications
            if lower in name
        ][:5]

        skills = self.skills.discover(query).get("skills", [])
        memory = self.memory.recall(query).get("results", [])

        parts = []

        if files:
            parts.append(
                f"{len(files)} files (first: {files[0].get('name')})"
            )

        if applications:
            parts.append(
                "apps: " + ", ".join(applications)
            )

        if skills:
            parts.append(
                "skills: "
                + ", ".join(
                    skill["display_name"]
                    for skill in skills
                )
            )
        
        if memory:
            parts.append(
                "memory: " + "; ".join(memory[:2])
            )

        message = (
            "Found " + "; ".join(parts) + "."
            if parts
            else "I couldn't find anything matching that."
        )

        return {
            "success": True,
            "files": files,
            "applications": applications,
            "skills": [
                skill["display_name"]
                for skill in skills
            ],
            "memory": memory,
            "message": message,
        }

    def _search_filesystem(
        self,
        query: str,
        location: str | None = None,
    ):
        results = self.filesystem_searcher.search(
            query=query,
            location=location,
        )

        if not results:
            return f"No files found matching '{query}'."

        return results

    def _get_filesystem_info(self, path: str):
        return self.filesystem_observer.get_info(path)