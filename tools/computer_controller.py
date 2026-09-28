import ctypes
import ctypes.wintypes
import math
import time


_DPI_APPLIED = False


def ensure_dpi_awareness():
    """
    Make this process per-monitor DPI aware so screenshot pixels and
    SetCursorPos coordinates both live in PHYSICAL pixels. Without
    this, on a scaled display (125%/150%) the vision step returns
    coordinates that are systematically wrong and the cursor clicks
    the wrong spot (or appears never to move towards the target).
    Idempotent; safe to call from any module.
    """

    global _DPI_APPLIED

    if _DPI_APPLIED:
        return

    try:
        # Windows 8.1+: per-monitor aware (value 2).
        ctypes.windll.shcore.SetProcessDpiAwareness(2)

    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()

        except Exception:
            pass

    _DPI_APPLIED = True


class ComputerController:
    MOUSEEVENTF_MOVE = 0x0001
    MOUSEEVENTF_LEFTDOWN = 0x0002
    MOUSEEVENTF_LEFTUP = 0x0004
    MOUSEEVENTF_RIGHTDOWN = 0x0008
    MOUSEEVENTF_RIGHTUP = 0x0010
    MOUSEEVENTF_WHEEL = 0x0800

    KEYEVENTF_KEYUP = 0x0002

    VK_SHIFT = 0x10
    VK_CTRL = 0x11
    VK_ALT = 0x12
    VK_ENTER = 0x0D
    VK_ESCAPE = 0x1B
    VK_TAB = 0x09
    VK_SPACE = 0x20
    VK_BACKSPACE = 0x08
    VK_DELETE = 0x2E
    VK_UP = 0x26
    VK_DOWN = 0x28
    VK_LEFT = 0x25
    VK_RIGHT = 0x27

    # A double-click is two clicks inside the system double-click
    # time (default 500 ms); ~90 ms is comfortably inside it.
    DOUBLE_CLICK_INTERVAL = 0.09

    # Kill-switch hook: the orchestrator sets this Event and every
    # glide/click/drag bails out mid-motion.
    abort_event = None

    def __init__(self):
        ensure_dpi_awareness()

    @staticmethod
    def _aborted():
        abort = ComputerController.abort_event

        return bool(abort is not None and abort.is_set())

    @staticmethod
    def _cursor_position():
        point = ctypes.wintypes.POINT()

        ctypes.windll.user32.GetCursorPos(ctypes.byref(point))

        return point.x, point.y

    def move_mouse(self, x: int, y: int, duration: float = 0.45):
        """
        GLIDE to (x, y): interpolate the path with ease-in-out so the
        cursor visibly moves instead of teleporting (v3 used bare
        SetCursorPos, so "double-click the Instagram shortcut" looked
        like nothing happened). duration < 0.05 keeps instant
        teleport behavior for callers that want it.
        """

        ensure_dpi_awareness()

        x = int(x)
        y = int(y)

        start_x, start_y = self._cursor_position()

        duration = max(0.0, float(duration))

        if duration < 0.05 or self._aborted():
            ctypes.windll.user32.SetCursorPos(x, y)

            return {"success": True, "x": x, "y": y, "glided": False}

        # Ease-in-out quad: slow start, faster middle, slow settle.
        steps = max(6, min(40, int(duration * 60)))

        for index in range(1, steps + 1):
            if self._aborted():
                return {
                    "success": False,
                    "error": "mouse movement cancelled",
                    "x": start_x,
                    "y": start_y,
                }

            progress = index / steps

            eased = (
                2 * progress * progress
                if progress < 0.5
                else 1 - ((-2 * progress + 2) ** 2) / 2
            )

            current_x = int(round(start_x + (x - start_x) * eased))
            current_y = int(round(start_y + (y - start_y) * eased))

            ctypes.windll.user32.SetCursorPos(current_x, current_y)

            time.sleep(duration / steps)

        # Land exactly on target (rounding drift above).
        ctypes.windll.user32.SetCursorPos(x, y)

        return {"success": True, "x": x, "y": y, "glided": True}

    def click_mouse(self, button: str = "left", clicks: int = 1):
        """
        Click 1..3 times. clicks=2 is a REAL double-click: two down/up
        pairs inside the system double-click time. The v3 catalogue
        declared a `clicks` parameter but the controller only ever
        clicked once — "double-click the shortcut" did nothing.
        """

        if self._aborted():
            return {"success": False, "error": "click cancelled"}

        button = (button or "left").lower().strip()

        buttons = {
            "left": (
                self.MOUSEEVENTF_LEFTDOWN,
                self.MOUSEEVENTF_LEFTUP,
            ),
            "right": (
                self.MOUSEEVENTF_RIGHTDOWN,
                self.MOUSEEVENTF_RIGHTUP,
            ),
        }

        if button not in buttons:
            return {
                "success": False,
                "error": f"Unsupported mouse button: {button}",
            }

        try:
            count = max(1, min(3, int(clicks)))

        except (TypeError, ValueError):
            count = 1

        down, up = buttons[button]

        for index in range(count):
            ctypes.windll.user32.mouse_event(down, 0, 0, 0, 0)
            ctypes.windll.user32.mouse_event(up, 0, 0, 0, 0)

            if index < count - 1:
                time.sleep(self.DOUBLE_CLICK_INTERVAL)

        return {"success": True, "button": button, "clicks": count}

    def drag_mouse(self, x: int, y: int, duration: float = 0.5):
        """Press left, glide to (x, y), release."""

        if self._aborted():
            return {"success": False, "error": "drag cancelled"}

        ctypes.windll.user32.mouse_event(
            self.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0
        )

        time.sleep(0.08)

        result = self.move_mouse(x, y, duration=duration)

        ctypes.windll.user32.mouse_event(
            self.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0
        )

        return result

    def scroll_mouse(self, amount: int):
        ctypes.windll.user32.mouse_event(
            self.MOUSEEVENTF_WHEEL,
            0,
            0,
            amount,
            0,
        )

        return {
            "success": True,
            "amount": amount,
        }

    def type_text(self, text: str, interval: float = 0.01):
        if not text:
            return {
                "success": False,
                "error": "No text provided.",
            }

        for character in text:
            self._type_character(character)

            if interval > 0:
                time.sleep(interval)

        return {
            "success": True,
            "text_length": len(text),
        }

    def press_key(self, key: str):
        virtual_key = self._get_virtual_key(key)

        if virtual_key is None:
            return {
                "success": False,
                "error": f"Unsupported key: {key}",
            }

        ctypes.windll.user32.keybd_event(
            virtual_key,
            0,
            0,
            0,
        )

        ctypes.windll.user32.keybd_event(
            virtual_key,
            0,
            self.KEYEVENTF_KEYUP,
            0,
        )

        return {
            "success": True,
            "key": key,
        }

    def _type_character(self, character: str):
        scan_code = ctypes.windll.user32.VkKeyScanW(
            ord(character)
        )

        if scan_code == -1:
            return

        virtual_key = scan_code & 0xFF
        shift_state = (scan_code >> 8) & 0xFF

        if shift_state & 1:
            self._key_down(self.VK_SHIFT)

        self._key_down(virtual_key)
        self._key_up(virtual_key)

        if shift_state & 1:
            self._key_up(self.VK_SHIFT)

    def _key_down(self, virtual_key):
        ctypes.windll.user32.keybd_event(
            virtual_key,
            0,
            0,
            0,
        )

    def _key_up(self, virtual_key):
        ctypes.windll.user32.keybd_event(
            virtual_key,
            0,
            self.KEYEVENTF_KEYUP,
            0,
        )

    def _get_virtual_key(self, key: str):
        key = key.lower().strip()

        special_keys = {
            "enter": self.VK_ENTER,
            "return": self.VK_ENTER,
            "escape": self.VK_ESCAPE,
            "esc": self.VK_ESCAPE,
            "tab": self.VK_TAB,
            "space": self.VK_SPACE,
            "backspace": self.VK_BACKSPACE,
            "delete": self.VK_DELETE,
            "up": self.VK_UP,
            "down": self.VK_DOWN,
            "left": self.VK_LEFT,
            "right": self.VK_RIGHT,
            "shift": self.VK_SHIFT,
            "ctrl": self.VK_CTRL,
            "control": self.VK_CTRL,
            "alt": self.VK_ALT,
        }

        if key in special_keys:
            return special_keys[key]

        if len(key) == 1:
            return ord(key.upper())

        if key.startswith("f") and key[1:].isdigit():
            number = int(key[1:])

            if 1 <= number <= 12:
                return 0x70 + number - 1

        return None