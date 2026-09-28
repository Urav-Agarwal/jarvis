import ctypes
import time


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

    def move_mouse(self, x: int, y: int):
        ctypes.windll.user32.SetCursorPos(x, y)

        return {
            "success": True,
            "x": x,
            "y": y,
        }

    def click_mouse(self, button: str = "left"):
        button = button.lower().strip()

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

        down, up = buttons[button]

        ctypes.windll.user32.mouse_event(
            down,
            0,
            0,
            0,
            0,
        )

        ctypes.windll.user32.mouse_event(
            up,
            0,
            0,
            0,
            0,
        )

        return {
            "success": True,
            "button": button,
        }

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