"""
Browser interaction tools for JARVIS.

Deterministic Windows-level control of the active browser window:
navigate (address bar), refresh, back/forward, tab URL via clipboard,
and reading selectable page text through the clipboard.

No third-party automation framework required.
"""

import re
import time

import win32clipboard

from tools.computer_controller import ComputerController


class BrowserController:
    """Controls the active browser window via keyboard automation."""

    VK_RETURN = 0x0D
    VK_CONTROL = 0x11
    VK_MENU = 0x12  # Alt
    VK_ESCAPE = 0x1B
    VK_LEFT = 0x25
    VK_RIGHT = 0x27
    VK_DELETE = 0x2E
    KEYEVENTF_KEYUP = 0x0002

    def __init__(self):
        self.controller = ComputerController()

    # ==================================================
    # PUBLIC OPERATIONS
    # ==================================================

    _BROWSER_EXES = {
        "chrome.exe", "msedge.exe", "firefox.exe", "brave.exe",
        "opera.exe", "comet.exe", "safari.exe", "browser.exe",
    }

    def focus_browser(self) -> bool:
        """
        Bring a browser window to the foreground so keyboard input
        reaches it. Returns True only when the browser window is
        verified as the foreground window.
        """

        import ctypes
        import time as _time

        import win32gui
        import win32process
        import psutil

        target = {"hwnd": None}

        def enum_handler(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd):
                return

            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)

                exe = psutil.Process(pid).name().lower()

                if exe in self._BROWSER_EXES and win32gui.GetWindowText(hwnd):
                    target["hwnd"] = hwnd

            except Exception:
                pass

        win32gui.EnumWindows(enum_handler, None)

        hwnd = target["hwnd"]

        if hwnd is None:
            return False

        user32 = ctypes.windll.user32

        HWND_TOPMOST = -1
        HWND_NOTOPMOST = -2
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001

        for _attempt in range(3):
            foreground = user32.GetForegroundWindow()

            if foreground == hwnd or self._foreground_is_browser():
                _time.sleep(0.2)
                return True

            foreground_thread = (
                user32.GetWindowThreadProcessId(foreground, 0)
                if foreground
                else 0
            )

            target_thread = win32process.GetWindowThreadProcessId(hwnd)[0]

            attached = False

            if foreground_thread and foreground_thread != target_thread:
                attached = bool(
                    user32.AttachThreadInput(
                        foreground_thread,
                        target_thread,
                        True,
                    )
                )

            try:
                win32gui.ShowWindow(hwnd, 9)  # SW_RESTORE
                win32gui.BringWindowToTop(hwnd)

                # Topmost-toggle: the reliable focus-steal bypass.
                user32.SetWindowPos(
                    hwnd,
                    HWND_TOPMOST,
                    0,
                    0,
                    0,
                    0,
                    SWP_NOMOVE | SWP_NOSIZE,
                )
                user32.SetWindowPos(
                    hwnd,
                    HWND_NOTOPMOST,
                    0,
                    0,
                    0,
                    0,
                    SWP_NOMOVE | SWP_NOSIZE,
                )

                user32.SetForegroundWindow(hwnd)

            finally:
                if attached:
                    user32.AttachThreadInput(
                        foreground_thread,
                        target_thread,
                        False,
                    )

            _time.sleep(0.35)

            if user32.GetForegroundWindow() == hwnd or self._foreground_is_browser():
                _time.sleep(0.2)
                return True

            # Alt-key nudge: releases Windows' foreground lock so the
            # next SetForegroundWindow is allowed.
            user32.keybd_event(0x12, 0, 0, 0)
            user32.keybd_event(0x12, 0, 2, 0)

        return self._foreground_is_browser()

    def _foreground_is_browser(self) -> bool:
        """
        True when the current foreground window belongs to a browser
        process. If the user is already looking at some browser window,
        operating on it is the sensible behavior even when the exact
        target hwnd could not be focused.
        """

        import ctypes
        import win32process
        import psutil

        hwnd = ctypes.windll.user32.GetForegroundWindow()

        if not hwnd:
            return False

        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)

            return psutil.Process(pid).name().lower() in self._BROWSER_EXES

        except Exception:
            return False

    def navigate(self, url: str) -> dict:
        url = (url or "").strip()

        if not url:
            return {
                "success": False,
                "error": "No URL was provided.",
            }

        if not self.focus_browser():
            return {
                "success": False,
                "error": "No browser window is available to navigate.",
            }

        target = self._normalize_url(url)

        # Open a NEW tab first so the user's current tab (e.g. their
        # Instagram) is never hijacked by our navigation.
        self._combo(self.VK_CONTROL, ord("T"))
        time.sleep(0.4)

        # Focus the address bar, type the target, press Enter.
        self._combo(self.VK_CONTROL, ord("L"))
        time.sleep(0.3)

        self.controller.type_text(target, interval=0.01)
        time.sleep(0.2)

        # Kill Chrome's inline autocomplete BEFORE Enter: the address
        # bar auto-appends a highlighted suffix from history (e.g.
        # typing youtube.com completes to a previously-visited watch
        # URL) and Enter would accept the hijacked address. Delete
        # clears any selected completion; typing already ends clean.
        self._tap(self.VK_DELETE)
        time.sleep(0.1)

        self._tap(self.VK_RETURN)

        # ------------------------------------------------
        # VERIFICATION: read the tab URL back and compare.
        # ------------------------------------------------
        time.sleep(2.0)

        verification = self.tab_state()

        final_url = (
            verification.get("url", "")
            if isinstance(verification, dict)
            else ""
        )

        if not final_url:
            # One retry: page load or clipboard read can race.
            time.sleep(1.5)
            verification = self.tab_state()

            final_url = (
                verification.get("url", "")
                if isinstance(verification, dict)
                else ""
            )

        if final_url:
            landed = self._same_site(final_url, target)

            # Cold-start race: the browser was still initializing when
            # our keystrokes arrived (e.g. sitting on chrome://whats-new).
            # Retry once after letting it settle.
            if not landed:
                time.sleep(2.0)

                self._combo(self.VK_CONTROL, ord("T"))
                time.sleep(0.5)
                self._combo(self.VK_CONTROL, ord("L"))
                time.sleep(0.3)
                self.controller.type_text(target, interval=0.01)
                time.sleep(0.2)
                self._tap(self.VK_DELETE)
                time.sleep(0.1)
                self._tap(self.VK_RETURN)
                time.sleep(2.5)

                verification = self.tab_state()

                final_url = (
                    verification.get("url", "")
                    if isinstance(verification, dict)
                    else ""
                )

                if final_url:
                    landed = self._same_site(final_url, target)

            return {
                "success": landed,
                "url": final_url,
                "verified": True,
                "message": (
                    f"Navigated to {final_url}."
                    if landed
                    else (
                        f"I typed the address but the browser is on "
                        f"{final_url} instead."
                    )
                ),
            }

        # Could not verify (clipboard/read failure): report without
        # claiming verified success.
        return {
            "success": True,
            "verified": False,
            "message": f"I navigated to {target}, but couldn't verify the page.",
        }

    @staticmethod
    def _same_site(actual: str, target: str) -> bool:
        """True when actual URL matches the target's host (and path prefix)."""

        from urllib.parse import urlparse

        try:
            actual_host = urlparse(actual).netloc.lower()
            target_host = urlparse(target).netloc.lower()

            if not target_host:
                return False

            # Treat www.example.com and example.com as equal.
            normalize = lambda host: host[4:] if host.startswith("www.") else host

            return normalize(actual_host) == normalize(target_host)

        except Exception:
            return False

    def refresh(self) -> dict:
        if not self.focus_browser():
            return {
                "success": False,
                "error": "No browser window is available to refresh.",
            }

        self.controller.press_key("f5")

        return {
            "success": True,
            "message": "Refreshed the page.",
        }

    def back(self) -> dict:
        if not self.focus_browser():
            return {
                "success": False,
                "error": "No browser window is available.",
            }

        self._combo(self.VK_MENU, self.VK_LEFT)

        return {
            "success": True,
            "message": "Went back one page.",
        }

    def forward(self) -> dict:
        if not self.focus_browser():
            return {
                "success": False,
                "error": "No browser window is available.",
            }

        self._combo(self.VK_MENU, self.VK_RIGHT)

        return {
            "success": True,
            "message": "Went forward one page.",
        }

    def read(self, max_chars: int = 4000) -> dict:
        """Copy the selectable page text via the clipboard."""

        if not self.focus_browser():
            return {
                "success": False,
                "error": "No browser window is available to read.",
            }

        previous = self._clipboard_text()

        # Empty the clipboard first: any text found after the copy is
        # guaranteed to be fresh page content, never stale clipboard.
        self._restore_clipboard("")

        self._combo(self.VK_CONTROL, ord("A"))
        time.sleep(0.2)

        self._combo(self.VK_CONTROL, ord("C"))
        time.sleep(0.4)

        text = self._clipboard_text()

        self._restore_clipboard(previous)
        self._tap(self.VK_ESCAPE)

        if not text:
            return {
                "success": False,
                "error": (
                    "The page provided no selectable text. "
                    "It may be empty, an image, or a protected view."
                ),
            }

        text = text.strip()

        return {
            "success": True,
            "text": text[:max_chars],
            "message": text[:600] + ("..." if len(text) > 600 else ""),
        }

    def tab_state(self) -> dict:
        """Return the URL of the active tab via the clipboard."""

        if not self.focus_browser():
            return {
                "success": False,
                "error": "No browser window is available.",
            }

        previous = self._clipboard_text()

        self._restore_clipboard("")

        self._combo(self.VK_CONTROL, ord("L"))
        time.sleep(0.2)

        self._combo(self.VK_CONTROL, ord("C"))
        time.sleep(0.3)

        url = self._clipboard_text()

        self._tap(self.VK_ESCAPE)
        self._restore_clipboard(previous)

        if not url:
            return {
                "success": False,
                "error": "Could not read the active tab URL.",
            }

        return {
            "success": True,
            "url": url.strip(),
            "message": f"The active tab is {url.strip()}.",
        }

    def type_text(self, text: str, press_enter: bool = False) -> dict:
        """Type into the currently focused element of the page."""

        if not self.focus_browser():
            return {
                "success": False,
                "error": "No browser window is available.",
            }

        if not text:
            return {
                "success": False,
                "error": "No text was provided.",
            }

        self.controller.type_text(text, interval=0.01)

        if press_enter:
            time.sleep(0.1)
            self._tap(self.VK_RETURN)

        return {
            "success": True,
            "message": f"Typed {len(text)} characters.",
        }

    def scroll(self, amount: int = 3) -> dict:
        if not self.focus_browser():
            return {
                "success": False,
                "error": "No browser window is available.",
            }

        self.controller.scroll_mouse(int(amount) * 120)

        return {
            "success": True,
            "message": "Scrolled the page.",
        }

    def click_target(self, target: str) -> dict:
        """
        Click a described element on the active browser page using
        screen vision to find its coordinates.
        """

        from tools.screen_vision import ScreenVision

        if not self.focus_browser():
            return {
                "success": False,
                "error": "No browser window is available to click in.",
            }

        try:
            vision = ScreenVision()
        except ValueError:
            return {
                "success": False,
                "error": "Vision model is not configured.",
            }

        located = vision.locate(
            f"On the webpage currently shown, locate this element: {target}. "
            "Return the center of the clickable element (button, link, or control)."
        )

        if not located.get("success"):
            return {
                "success": False,
                "error": (
                    f"I couldn't find '{target}' on the current page."
                ),
            }

        self.controller.move_mouse(located["x"], located["y"])
        time.sleep(0.2)
        self.controller.click_mouse("left")

        return {
            "success": True,
            "x": located["x"],
            "y": located["y"],
            "message": f"Clicked {target}.",
        }

    def copy_target(self, target: str = None) -> dict:
        """
        Copy text from the active page to the clipboard and return it.
        With a target, clicks the described element first (selecting or
        focusing it); without, copies the selectable page text.
        """

        if not self.focus_browser():
            return {
                "success": False,
                "error": "No browser window is available.",
            }

        previous = self._clipboard_text()

        # Empty-first: guarantees fresh copy, never stale clipboard.
        self._restore_clipboard("")

        if target:
            self.click_target(target)
            time.sleep(0.3)

        self._combo(self.VK_CONTROL, ord("A"))
        time.sleep(0.2)
        self._combo(self.VK_CONTROL, ord("C"))
        time.sleep(0.5)

        text = self._clipboard_text()

        self._restore_clipboard(previous)
        self._tap(self.VK_ESCAPE)

        return {
            "success": bool(text),
            "text": text[:4000],
            "message": (
                text[:400] + ("..." if len(text) > 400 else "")
                if text
                else "Nothing could be copied."
            ),
        }

    # ==================================================
    # INTERNALS
    # ==================================================

    # Site-native search endpoints: searching a site means opening
    # ITS search page, never a random result link.
    _SEARCH_ENDPOINTS = {
        "youtube": "https://www.youtube.com/results?search_query={}",
        "google": "https://www.google.com/search?q={}",
        "github": "https://github.com/search?q={}",
        "wikipedia": "https://en.wikipedia.org/w/index.php?search={}",
        "amazon": "https://www.amazon.in/s?k={}",
        "reddit": "https://www.reddit.com/search/?q={}",
        "twitter": "https://twitter.com/search?q={}",
        "x": "https://twitter.com/search?q={}",
        "stack overflow": "https://stackoverflow.com/search?q={}",
        "stackoverflow": "https://stackoverflow.com/search?q={}",
        "flipkart": "https://www.flipkart.com/search?q={}",
    }

    def search_site(self, site: str, query: str) -> dict:
        """
        Search ON a named site by opening that site's own search page.
        Falls back to a Google site-restricted search for unknown sites.
        """

        site = (site or "").strip().lower()
        query = (query or "").strip()

        if not query:
            return {
                "success": False,
                "error": "No search query was provided.",
            }

        from urllib.parse import quote

        endpoint = self._SEARCH_ENDPOINTS.get(site)

        if endpoint:
            url = endpoint.format(quote(query))
            display = site
        else:
            url = (
                "https://www.google.com/search?q="
                + quote(f"site:{site} {query}")
                if site
                else "https://www.google.com/search?q=" + quote(query)
            )

            display = site or "the web"

        result = self.navigate(url)

        if result.get("success"):
            result["message"] = (
                f"Searching {display} for {query}."
            )

        return result

    @staticmethod
    def _normalize_url(url: str) -> str:
        url = url.strip()

        # Has a scheme already.
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", url):
            return url

        # Looks like a domain (e.g. "example.com/docs").
        if re.match(r"^[\w-]+(\.[\w-]+)+(/|$)", url):
            return "https://" + url

        # Not a URL: treat it as a web search.
        from urllib.parse import quote

        return "https://duckduckgo.com/?q=" + quote(url)

    def _combo(self, modifier_vk: int, key_vk: int):
        self._key_down(modifier_vk)
        self._key_down(key_vk)
        self._key_up(key_vk)
        self._key_up(modifier_vk)

    def _tap(self, vk: int):
        self._key_down(vk)
        self._key_up(vk)

    KEYEVENTF_KEYUP = 0x0002
    KEYEVENTF_SCANCODE = 0x0008
    KEYEVENTF_UNICODE = 0x0004
    INPUT_KEYBOARD = 1

    def _send_scan(self, vk: int, keyup: bool = False):
        """Send a key via SendInput with scan code (Chromium-safe)."""

        import ctypes

        scan = ctypes.windll.user32.MapVirtualKeyW(vk, 0)

        flags = self.KEYEVENTF_SCANCODE

        if keyup:
            flags |= self.KEYEVENTF_KEYUP

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [
                ("wVk", ctypes.c_ushort),
                ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
            ]

        class INPUT(ctypes.Structure):
            _fields_ = [
                ("type", ctypes.c_ulong),
                ("ki", KEYBDINPUT),
                ("padding", ctypes.c_ubyte * 8),
            ]

        item = INPUT()
        item.type = self.INPUT_KEYBOARD
        item.ki = KEYBDINPUT(0, scan, flags, 0, None)

        ctypes.windll.user32.SendInput(1, ctypes.byref(item), ctypes.sizeof(INPUT))

    def _key_down(self, vk: int):
        self._send_scan(vk, keyup=False)

    def _key_up(self, vk: int):
        self._send_scan(vk, keyup=True)

    def _clipboard_text(self) -> str:
        try:
            win32clipboard.OpenClipboard()

            try:
                if win32clipboard.IsClipboardFormatAvailable(
                    win32clipboard.CF_UNICODETEXT
                ):
                    return win32clipboard.GetClipboardData(
                        win32clipboard.CF_UNICODETEXT
                    )

                return ""
            finally:
                win32clipboard.CloseClipboard()

        except Exception:
            return ""

    def _restore_clipboard(self, text: str):
        try:
            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()

            try:
                win32clipboard.SetClipboardText(
                    text,
                    win32clipboard.CF_UNICODETEXT,
                )
            finally:
                win32clipboard.CloseClipboard()

        except Exception:
            pass
