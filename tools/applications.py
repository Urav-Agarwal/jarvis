from pathlib import Path
import os


class ApplicationManager:
    def __init__(self):
        self.applications = {}
        self.refresh_applications()

    def refresh_applications(self):
        self.applications.clear()

        start_menu_locations = [
            Path(os.environ.get("APPDATA", ""))
            / "Microsoft/Windows/Start Menu/Programs",

            Path(os.environ.get("PROGRAMDATA", ""))
            / "Microsoft/Windows/Start Menu/Programs",
        ]

        for location in start_menu_locations:
            self._scan_directory(location)

    def _scan_directory(self, directory: Path):
        if not directory.exists():
            return

        try:
            for path in directory.rglob("*"):
                if path.is_file() and path.suffix.lower() in {
                    ".lnk",
                    ".url",
                }:
                    name = path.stem.lower().strip()

                    if name and name not in self.applications:
                        self.applications[name] = path

        except (PermissionError, OSError):
            pass

    # Windows 11 delivers common apps as Store packages that do not
    # appear in Start Menu folders; fall back to known executables
    # and URI schemes for the most common aliases.
    FALLBACK_LAUNCHERS = {
        "notepad": ["notepad.exe"],
        "calculator": ["calc.exe", "ms-calculator:"],
        "calc": ["calc.exe", "ms-calculator:"],
        "paint": ["mspaint.exe", "ms-paint:"],
        "cmd": ["cmd.exe"],
        "command prompt": ["cmd.exe"],
        "terminal": ["wt.exe"],
        "settings": ["ms-settings:"],
    }

    # URI schemes for Store apps that ship no Start Menu shortcut.
    URI_SCHEMES = {
        "whatsapp": "whatsapp:",
        "instagram": "instagram:",
        "microsoft store": "ms-windows-store:",
        "store": "ms-windows-store:",
        "calculator": "calculator:",
        "mail": "mailto:",
        "teams": "msteams:",
        "spotify": "spotify:",
        "telegram": "tg:",
        "instagram": "instagram:",
        "netflix": "netflix:",
    }

    def open_application(self, name: str) -> bool:
        application_path = self.find_application(name)

        if application_path is not None:
            try:
                os.startfile(application_path)
                return True
            except OSError:
                pass

        requested = name.lower().strip()

        for launcher in self.FALLBACK_LAUNCHERS.get(requested, []):
            try:
                os.startfile(launcher)
                return True
            except OSError:
                continue

        # Start-menu scan missed it: ask Windows for the registered
        # Start-apps list (covers Store/UAL apps like WhatsApp).
        if self._open_via_start_apps(requested):
            return True

        # Known URI scheme as the last resort.
        scheme = self.URI_SCHEMES.get(requested)

        if scheme:
            try:
                os.startfile(scheme)
                return True
            except OSError:
                pass

        return False

    def _open_via_start_apps(self, requested: str) -> bool:
        """
        Resolve an app against the Windows 'Get-StartApps' registry
        (all apps the Start menu can launch, including Store apps
        without .lnk files), then launch by its AUMID shell: URI.
        """

        if not requested:
            return False

        try:
            import subprocess
            import json

            output = subprocess.run(
                [
                    "powershell", "-NoProfile", "-Command",
                    "Get-StartApps | ConvertTo-Json -Compress",
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )

            apps = json.loads(output.stdout or "[]")

            if isinstance(apps, dict):
                apps = [apps]

            def normalized(value):
                return " ".join(
                    str(value).lower().replace("!", " ").split()
                )

            target = normalized(requested)

            exact = None
            partial = None

            for app in apps:
                app_name = normalized(app.get("Name", ""))
                app_id = app.get("AppID", "")

                if not app_name or not app_id:
                    continue

                if app_name == target:
                    exact = app_id
                    break

                if partial is None and (
                    target in app_name or app_name in target
                ):
                    partial = app_id

            app_id = exact or partial

            if not app_id:
                return False

            # Store/UAL apps MUST be launched through the shell
            # namespace; a bare AUMID fails silently with plain
            # startfile() (this is why Instagram never opened).
            os.startfile(f"shell:AppsFolder\\{app_id}")
            return True

        except (
            OSError,
            ValueError,
            json.JSONDecodeError,
            subprocess.TimeoutExpired,
        ):
            return False

    def get_application_state(self, name: str):
        requested = name.lower().strip()

        if not requested:
            return {
                "success": False,
                "error": "Application name was not provided.",
            }

        try:
            from tools.computer_observer import ComputerObserver

            observer = ComputerObserver()
            result = observer.get_running_applications()

            if not result.get("success"):
                return result

            matches = []

            for application in result.get("applications", []):
                process_name = application.get("name", "").lower()
                window_title = application.get("window", "").lower()

                clean_process_name = process_name.removesuffix(".exe")

                if (
                    requested == clean_process_name
                    or requested == process_name
                    or requested in clean_process_name
                    or requested in window_title
                ):
                    matches.append(application)

            return {
                "success": True,
                "application": name,
                "running": bool(matches),
                "matches": matches,
            }

        except Exception as error:
            return {
                "success": False,
                "error": str(error),
            }

    def close_application(self, name: str):
        """
        Gracefully request that an application close.

        This does NOT force-kill the process.
        Windows/application dialogs are allowed to handle
        unsaved work normally.
        """

        requested = name.lower().strip()

        if not requested:
            return {
                "success": False,
                "application": name,
                "error": "Application name was not provided.",
            }

        try:
            import win32gui
            import win32process
            import psutil

            matching_pids = set()

            observer_result = self.get_application_state(name)

            if observer_result.get("success"):
                for application in observer_result.get("matches", []):
                    pid = application.get("pid")

                    if pid:
                        matching_pids.add(int(pid))

            if not matching_pids:
                return {
                    "success": False,
                    "application": name,
                    "closed": False,
                    "error": f"{name} is not currently running.",
                }

            windows = []

            def collect_window(hwnd, _):
                if not win32gui.IsWindowVisible(hwnd):
                    return True

                if win32gui.GetWindow(hwnd, win32con.GW_OWNER):
                    return True

                try:
                    _, pid = win32process.GetWindowThreadProcessId(hwnd)

                    if pid in matching_pids:
                        title = win32gui.GetWindowText(hwnd).strip()

                        if title:
                            windows.append(hwnd)

                except Exception:
                    pass

                return True

            import win32con

            win32gui.EnumWindows(collect_window, None)

            if not windows:
                return {
                    "success": False,
                    "application": name,
                    "closed": False,
                    "error": (
                        f"{name} is running, but no closable visible "
                        "application window was found."
                    ),
                }

            requested_windows = 0

            for hwnd in windows:
                try:
                    win32gui.PostMessage(
                        hwnd,
                        win32con.WM_CLOSE,
                        0,
                        0,
                    )
                    requested_windows += 1
                except Exception:
                    pass

            return {
                "success": requested_windows > 0,
                "application": name,
                "closed": requested_windows > 0,
                "windows_requested": requested_windows,
                "message": (
                    "A graceful close was requested. "
                    "Any unsaved-work prompt remains under the "
                    "application's control."
                ),
            }

        except Exception as error:
            return {
                "success": False,
                "application": name,
                "closed": False,
                "error": str(error),
            }

    def find_application(self, name: str):
        name = name.lower().strip()

        if name in self.applications:
            return self.applications[name]

        matches = [
            (app_name, path)
            for app_name, path in self.applications.items()
            if name in app_name or app_name in name
        ]

        if len(matches) == 1:
            return matches[0][1]

        return None


if __name__ == "__main__":
    manager = ApplicationManager()

    print("APPLICATION DISCOVERY READY")
    print()
    print(f"Applications found: {len(manager.applications)}")
    print()

    for name in sorted(manager.applications):
        print(f"- {name}")