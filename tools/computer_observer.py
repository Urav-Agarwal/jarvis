import ctypes
from ctypes import wintypes

import psutil


class ComputerObserver:
    def get_active_window(self):
        hwnd = ctypes.windll.user32.GetForegroundWindow()

        if not hwnd:
            return {
                "success": False,
                "error": "No active window found.",
            }

        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)

        if length == 0:
            title = ""
        else:
            buffer = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(
                hwnd,
                buffer,
                length + 1,
            )
            title = buffer.value

        process_id = wintypes.DWORD()

        ctypes.windll.user32.GetWindowThreadProcessId(
            hwnd,
            ctypes.byref(process_id),
        )

        try:
            process = psutil.Process(process_id.value)

            return {
                "success": True,
                "title": title,
                "process": process.name(),
                "pid": process.pid,
            }

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return {
                "success": True,
                "title": title,
                "process": "Unknown",
                "pid": process_id.value,
            }

    def get_screen_state(self):
        try:
            user32 = ctypes.windll.user32

            screen_width = user32.GetSystemMetrics(0)
            screen_height = user32.GetSystemMetrics(1)

            point = wintypes.POINT()

            if not user32.GetCursorPos(ctypes.byref(point)):
                return {
                    "success": False,
                    "error": "Could not determine cursor position.",
                }

            active_window = self.get_active_window()

            return {
                "success": True,
                "screen": {
                    "width": screen_width,
                    "height": screen_height,
                },
                "cursor": {
                    "x": point.x,
                    "y": point.y,
                },
                "active_window": active_window,
            }

        except OSError as error:
            return {
                "success": False,
                "error": str(error),
            }

    def get_running_applications(self):
        applications = {}

        def enum_window_callback(hwnd, _):
            if not ctypes.windll.user32.IsWindowVisible(hwnd):
                return True

            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)

            if length == 0:
                return True

            buffer = ctypes.create_unicode_buffer(length + 1)

            ctypes.windll.user32.GetWindowTextW(
                hwnd,
                buffer,
                length + 1,
            )

            title = buffer.value.strip()

            if not title:
                return True

            process_id = wintypes.DWORD()

            ctypes.windll.user32.GetWindowThreadProcessId(
                hwnd,
                ctypes.byref(process_id),
            )

            try:
                process = psutil.Process(process_id.value)
                process_name = process.name()

                applications[process_id.value] = {
                    "name": process_name,
                    "pid": process_id.value,
                    "window": title,
                }

            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

            return True

        callback = ctypes.WINFUNCTYPE(
            wintypes.BOOL,
            wintypes.HWND,
            wintypes.LPARAM,
        )(enum_window_callback)

        ctypes.windll.user32.EnumWindows(
            callback,
            0,
        )

        return {
            "success": True,
            "count": len(applications),
            "applications": list(applications.values()),
        }