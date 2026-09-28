"""
Messaging across desktop apps.

WhatsApp has a full adapter (chat search + send via keyboard
automation). Other Electron-style apps (Discord, Instagram, Telegram)
share the same shape: activate window, paste recipient/message, Enter.
A generic adapter handles them honestly — with per-app known
limitations reported instead of pretending success.
"""

import time

import win32gui

from tools.whatsapp import (
    _activate_window,
    _paste_text,
    press_combo,
    press_key,
    VK_CONTROL,
    VK_ESCAPE,
    VK_RETURN,
)


# Apps with a Ctrl+F / search-first chat flow similar to WhatsApp.
_SEARCH_FIRST_APPS = {
    "discord": "discord",
    "instagram": "instagram",
    "telegram": "telegram",
}

# Known app window-title fragments (case-insensitive).
_WINDOW_HINTS = {
    "whatsapp": "whatsapp",
    "discord": "discord",
    "instagram": "instagram",
    "telegram": "telegram",
}


def _find_app_window(app_name: str):
    """Return the main visible window handle for app_name, or None."""

    fragment = _WINDOW_HINTS.get(app_name.lower(), app_name.lower())

    found = []

    def collect(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return True

        title = (win32gui.GetWindowText(hwnd) or "").lower()

        if fragment in title:
            found.append((hwnd, win32gui.GetWindowText(hwnd)))

        return True

    win32gui.EnumWindows(collect, None)

    return found[0] if found else None


def is_app_running(app_name: str) -> bool:
    try:
        import psutil

        needle = app_name.lower()

        for process in psutil.process_iter(["name"]):
            name = (process.info["name"] or "").lower()

            if needle in name:
                return True

    except Exception:
        pass

    return False


def send_message_in_app(app_name: str, contact: str, message: str) -> dict:
    """
    Generic send: focus the app window, search the contact, paste the
    message, press Enter. WhatsApp gets the dedicated, verified flow;
    other apps get the generic flow with honest reporting.
    """

    app_name = (app_name or "").strip().lower()
    contact = (contact or "").strip()
    message = (message or "").strip()

    if not app_name:
        return {
            "success": False,
            "error": "Which app should I send it through?",
        }

    if not contact or not message:
        return {
            "success": False,
            "error": "I need both a contact and a message to send.",
        }

    if app_name == "whatsapp":
        # Dedicated adapter with chat-open verification.
        from tools.whatsapp import send_message

        return send_message(contact, message)

    if not is_app_running(app_name):
        return {
            "success": False,
            "error": (
                f"{app_name.title()} is not running. Please open it "
                "and sign in first, then ask me again."
            ),
        }

    window = _find_app_window(app_name)

    if window is None:
        return {
            "success": False,
            "error": (
                f"{app_name.title()} is running but no window was "
                "found. Please bring it up and try again."
            ),
        }

    hwnd, title = window

    if not _activate_window(hwnd):
        return {
            "success": False,
            "error": (
                f"I couldn't bring the {app_name.title()} window to "
                "the front."
            ),
        }

    time.sleep(1.0)

    # Search-first apps: focus the in-app search, paste the contact,
    # open the chat. Others assume the chat is already selected.
    if app_name in _SEARCH_FIRST_APPS:
        press_key(VK_ESCAPE)
        time.sleep(0.3)
        press_combo(VK_CONTROL, VK_F)
        time.sleep(0.6)

        if not _paste_text(contact):
            return {
                "success": False,
                "error": "I couldn't use the clipboard to search.",
            }

        time.sleep(1.4)
        press_key(VK_RETURN)
        time.sleep(0.9)

    # Type the message and send.
    if not _paste_text(message):
        return {
            "success": False,
            "error": "I couldn't paste the message.",
        }

    time.sleep(0.4)
    press_key(VK_RETURN)
    time.sleep(0.6)

    return {
        "success": True,
        "message": (
            f"Message typed and sent in {app_name.title()} "
            f"({title[:40]}). Glance at the chat to confirm it landed "
            "on the right conversation."
        ),
    }


if __name__ == "__main__":
    print("window:", _find_app_window("whatsapp"))
