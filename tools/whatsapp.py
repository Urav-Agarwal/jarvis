"""
WhatsApp Desktop automation.

Activates the WhatsApp window, finds a chat via its search box, and
sends a typed message. Used through the gated
"application.whatsapp_message" tool — always confirmed by the user
first, and only when WhatsApp is already running and signed in.
"""

import ctypes
import os
import re
import time
from ctypes import wintypes

import win32clipboard
import win32con
import win32gui

user32 = ctypes.windll.user32

# ------------------------------------------------------------
# Low-level input (SendInput with UNICODE for arbitrary names)
# ------------------------------------------------------------

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.DWORD),
        ("union", _INPUTUNION),
    ]


def _send_key_event(vk_or_scan, flags):
    event = INPUT()
    event.type = INPUT_KEYBOARD
    event.union.ki.wVk = 0 if flags & KEYEVENTF_UNICODE else vk_or_scan
    event.union.ki.wScan = vk_or_scan if flags & KEYEVENTF_UNICODE else 0
    event.union.ki.dwFlags = flags
    event.union.ki.time = 0
    event.union.ki.dwExtraInfo = ctypes.pointer(wintypes.ULONG(0))

    user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(INPUT))


def press_key(vk_code):
    _send_key_event(vk_code, 0)
    _send_key_event(vk_code, KEYEVENTF_KEYUP)


def press_combo(*vk_codes):
    for vk in vk_codes:
        _send_key_event(vk, 0)

    for vk in reversed(vk_codes):
        _send_key_event(vk, KEYEVENTF_KEYUP)


def type_unicode(text):
    for char in text:
        code = ord(char)

        if code == 0:
            continue

        # Surrogate pairs for characters outside the BMP.
        if code > 0xFFFF:
            code -= 0x10000
            for part in (0xD800 + (code >> 10), 0xDC00 + (code & 0x3FF)):
                _send_key_event(part, KEYEVENTF_UNICODE)
                _send_key_event(part, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)
        else:
            _send_key_event(code, KEYEVENTF_UNICODE)
            _send_key_event(code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)


VK_CONTROL = 0x11
VK_MENU = 0x12
VK_RETURN = 0x0D
VK_ESCAPE = 0x1B
VK_V = 0x56
VK_F = 0x46


def _set_clipboard_text(text: str) -> bool:
    try:
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(text, win32con.CF_UNICODETEXT)
        finally:
            win32clipboard.CloseClipboard()
        return True

    except Exception:
        return False


def _paste_text(text: str) -> bool:
    if not _set_clipboard_text(text):
        return False

    press_combo(VK_CONTROL, VK_V)

    return True


# ------------------------------------------------------------
# Window discovery
# ------------------------------------------------------------

def find_whatsapp_window():
    """
    Return the best WhatsApp window handle: a visible one first,
    then the largest hidden one (WhatsApp keeps several helper
    windows with the same title; the real one is the big one).
    """

    visible = []
    hidden = []

    def collect(hwnd, _):
        title = win32gui.GetWindowText(hwnd)

        if "WhatsApp" in title:
            try:
                left, top, right, bottom = win32gui.GetWindowRect(hwnd)

                area = max(0, right - left) * max(0, bottom - top)

            except Exception:
                area = 0

            if win32gui.IsWindowVisible(hwnd):
                visible.append((area, hwnd))

            else:
                hidden.append((area, hwnd))

        return True

    win32gui.EnumWindows(collect, None)

    if visible:
        return max(visible)[1]

    if hidden:
        return max(hidden)[1]

    return None


def is_whatsapp_running() -> bool:
    try:
        import psutil

        for process in psutil.process_iter(["name"]):
            name = (process.info["name"] or "").lower()

            if "whatsapp" in name:
                return True

    except Exception:
        pass

    return False


def _activate_window(hwnd) -> bool:
    """
    Bring WhatsApp to the front and CONFIRM it took focus.

    Windows denies focus-stealing to background processes, which is
    exactly what JARVIS is right after launching the app. A
    synthetic ALT tap makes SetForegroundWindow permissible; three
    attempts with verification handle slow cold starts.
    """

    for _attempt in range(3):
        try:
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)

            _send_key_event(VK_MENU, 0)
            _send_key_event(VK_MENU, KEYEVENTF_KEYUP)

            win32gui.SetForegroundWindow(hwnd)

            time.sleep(0.5)

            if user32.GetForegroundWindow() == hwnd:
                return True

        except Exception:
            pass

        time.sleep(0.7)

    return False


def _window_is_foreground(hwnd) -> bool:
    try:
        return user32.GetForegroundWindow() == hwnd

    except Exception:
        return False


def _uia_window_shows_text(hwnd, tokens, budget_seconds=4.0):
    """
    Bounded UI-Automation scan: does any accessible element of the
    window expose a Name containing ALL the given word tokens?

    This is the reliable chat verification: the window TITLE on the
    current WhatsApp Desktop often stays just "WhatsApp" even with a
    chat open, but the UI tree always exposes the chat header (and
    message headers) with the contact's display name.
    """

    tokens = [t for t in tokens if t]

    if not tokens:
        return False

    try:
        import comtypes
        import comtypes.client

        # Tool handlers run in worker threads: COM must be
        # initialized on THIS thread before any comtypes call.
        try:
            comtypes.CoInitialize()

        except Exception:
            pass

        uia_mod = comtypes.client.GetModule("UIAutomationCore.dll")

        automation = comtypes.client.CreateObject(
            "{ff48dba4-60ef-4201-aa87-54103eef594e}",
            interface=uia_mod.IUIAutomation,
        )

        root = automation.ElementFromHandle(hwnd)

        from collections import deque

        deadline = time.time() + budget_seconds

        queue = deque([root])

        visited = 0

        while queue and visited < 800 and time.time() < deadline:
            element = queue.popleft()

            visited += 1

            try:
                name = element.CurrentName or ""

            except Exception:
                name = ""

            if name:
                lowered = " ".join(name.lower().split())

                if lowered and all(
                    token in lowered for token in tokens
                ):
                    return True

            try:
                walker = automation.RawViewWalker

                child = walker.GetFirstChildElement(element)

                while child is not None:
                    queue.append(child)

                    child = walker.GetNextSiblingElement(child)

            except Exception:
                break

    except Exception:
        return False

    return False


_OFFLINE_MARKERS = (
    "not connected",
    "internet connection",
    "reconnect",
    "phone offline",
    "trying to reach your phone",
)


def _whatsapp_offline(hwnd) -> bool:
    """
    Detect the 'Computer not connected' screen: WhatsApp Desktop lost
    its link to the phone, so NO chat can open or send. Distinguishing
    this from a wrong contact name gives the user an honest, fixable
    message instead of a vague refusal.
    """

    ocr_lines = _ocr_window_text(hwnd)

    full_text = " ".join(text for _x, _y, text in ocr_lines)

    return any(marker in full_text for marker in _OFFLINE_MARKERS)


def _chat_opened(hwnd, query):
    """Verify the requested chat is actually open and visible."""

    try:
        chat_title = (
            win32gui.GetWindowText(hwnd) or ""
        ).lower()

    except Exception:
        chat_title = ""

    tokens = [
        token
        for token in re.split(r"\s+", query.lower().strip())
        if token
    ]

    if not tokens:
        return False

    # 1) Window title (older WhatsApp builds put the chat name here).
    if all(token in chat_title for token in tokens):
        return True

    # 2) UI Automation scan (fast when the build exposes names).
    if _uia_window_shows_text(hwnd, tokens, budget_seconds=3.0):
        return True

    # 3) OCR the chat-header strip. Works on every build, including
    #    Electron builds that expose no UIA names (verified live:
    #    the header reads e.g. "Vishwa Fatty click here for contact
    #    info" while the window title stays just "WhatsApp"). Match
    #    only lines in the RIGHT pane (x beyond the chat list) so a
    #    name merely sitting in the chat list can never fake a hit.
    #    Two attempts: the renderer can lag a beat behind the search.
    for _attempt in range(2):
        ocr_lines = _ocr_window_text(hwnd)

        header_text = " ".join(
            text
            for x_frac, _y_frac, text in ocr_lines
            if x_frac >= 0.30
        )

        if header_text and all(
            token in header_text for token in tokens
        ):
            return True

        time.sleep(1.2)

    return False


def _ocr_window_text(hwnd):
    """
    Read the visible text in the window's top strip (the chat header
    zone) using the built-in Windows OCR engine. Returns a list of
    (x_frac, y_frac, text) line tuples — coordinates as fractions of
    the captured strip — or [] if anything fails. The window is
    restored if minimized, but NOT activated: focus-stealing here
    would break any search/send keystrokes in flight. The pixels
    are readable from a visible (non-foreground) window.
    """

    root_dir = os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    )

    temp_path = os.path.join(root_dir, "data", "_wa_ocr.png")

    try:
        # Minimized or tray-hidden windows sit off-screen at
        # -25600/-32000: restore so the pixels exist on screen, but
        # do NOT SetForegroundWindow (that would steal focus from
        # the WhatsApp search box mid-send).
        if win32gui.IsIconic(hwnd) or not win32gui.IsWindowVisible(
            hwnd,
        ):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)

            time.sleep(0.8)

        left, top, right, bottom = win32gui.GetWindowRect(hwnd)

        # Still off-screen (restore lost the race): one more try,
        # then give up rather than capture garbage.
        if (
            left < -20000
            or top < -20000
            or right - left < 400
            or bottom - top < 300
        ):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)

            time.sleep(1.2)

            left, top, right, bottom = win32gui.GetWindowRect(hwnd)

            if (
                left < -20000
                or top < -20000
                or right - left < 400
                or bottom - top < 300
            ):
                return []

        from PIL import ImageGrab

        # Full width, header-height strip only.
        grab = ImageGrab.grab(
            bbox=(
                left,
                top,
                right,
                min(top + 200, bottom),
            )
        )

        grab.save(temp_path)

    except Exception:
        return []

    try:
        lines = _run_ocr_lines(temp_path, grab.size[0], grab.size[1])

    except Exception:
        return []

    finally:
        try:
            os.remove(temp_path)

        except OSError:
            pass

    return lines


def _run_ocr_lines(image_path, width, height, preserve_case=False):
    """
    Run the PowerShell WinRT OCR helper on an image and parse its
    "x y text" rows into (x_frac, y_frac, text) tuples. Shared by
    the chat-header reader and the search-results reader.
    """

    import subprocess

    root_dir = os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    )

    script = os.path.join(root_dir, "scripts", "ocr_image.ps1")

    output = subprocess.run(
        [
            "powershell", "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-File", script, image_path,
        ],
        capture_output=True,
        text=True,
        timeout=45,
    )

    safe_width = max(1, int(width))
    safe_height = max(1, int(height))

    lines = []

    for raw in (output.stdout or "").splitlines():
        parts = raw.strip().split(None, 2)

        if len(parts) != 3:
            continue

        try:
            x_frac = int(parts[0]) / safe_width
            y_frac = int(parts[1]) / safe_height

        except ValueError:
            continue

        text = parts[2] if preserve_case else parts[2].lower()

        lines.append((x_frac, y_frac, text))

    return lines


_NOISE_RESULT_TOKENS = {
    "am", "pm", "online", "typing", "archived", "unread", "missed",
    "chats", "contacts", "messages", "groups", "new", "chat", "group",
    "contact", "seen", "today", "yesterday", "status", "calls",
    "community", "communities", "settings", "updates",
}


def _is_noise_token(token: str) -> bool:
    """Times, badge counts, and section labels are not name words."""

    lowered = (token or "").lower().strip("….,:;!?()[]")

    if not lowered:
        return True

    if re.fullmatch(r"\d+", lowered):
        return True

    if re.fullmatch(r"\d{1,2}[:.]\d{2}", lowered):
        return True

    if re.fullmatch(r"\d{1,2}\s*(?:am|pm)", lowered):
        return True

    return lowered in _NOISE_RESULT_TOKENS


def _clean_result_name(line_text: str) -> str:
    """
    Turn one OCR line of a WhatsApp search row into a speakable
    contact/chat name: keep the leading name words and drop the
    right-aligned time, unread badge, and section noise.
    """

    kept = []

    for token in line_text.split():
        if kept and _is_noise_token(token):
            break

        kept.append(token)

    while kept and _is_noise_token(kept[0]):
        kept.pop(0)

    return " ".join(kept).strip(" ….!?.-")


def _ensure_window(timeout_seconds: float = 30.0):
    """
    Get WhatsApp ready for automation: launch it if closed, wait for
    its window, restore it when tray-hidden/minimized, and bring it
    to the foreground. Returns the window handle or None.
    """

    if not is_whatsapp_running():
        try:
            from tools.applications import ApplicationManager

            launched = ApplicationManager().open_application("whatsapp")

        except Exception:
            launched = False

        if not launched:
            return None

    hwnd = None

    for _ in range(int(timeout_seconds)):
        hwnd = find_whatsapp_window()

        if hwnd is not None:
            break

        time.sleep(1.0)

    if hwnd is None:
        return None

    try:
        if win32gui.IsIconic(hwnd) or not win32gui.IsWindowVisible(
            hwnd,
        ):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)

            time.sleep(0.8)

    except Exception:
        pass

    time.sleep(1.5)

    if not _activate_window(hwnd):
        return None

    return hwnd


def _open_chat_with_query(hwnd, query: str) -> bool:
    """
    Search for `query` in WhatsApp and verify the matching chat
    actually opened (window title → UIA scan → header OCR).
    """

    if not _window_is_foreground(hwnd):
        _activate_window(hwnd)

        time.sleep(0.8)

    press_key(VK_ESCAPE)
    time.sleep(0.3)
    press_combo(VK_CONTROL, VK_F)
    time.sleep(0.6)

    if not _paste_text(query):
        return False

    time.sleep(1.6)

    # Pick the best search result.
    press_key(VK_RETURN)
    time.sleep(1.0)

    # Escape leaves the in-chat search focused on the chat itself.
    press_key(VK_ESCAPE)
    time.sleep(0.5)

    # RE-ASSERT FOCUS: OCR/UIA verification must never steal it, but
    # other windows (VS Code popups, notifications) can steal it from
    # US. If WhatsApp lost the foreground while we verified, bring it
    # back BEFORE the caller types the message.
    if not _window_is_foreground(hwnd):
        _activate_window(hwnd)

        time.sleep(0.5)

    return _chat_opened(hwnd, query)


def _read_search_results(hwnd, query: str, attempts: int = 3):
    """
    Read the visible search-results list after `query` was typed into
    WhatsApp's search box. Pure read — nothing is opened or sent.
    Returns the visible result names, best match first.

    CRITICAL: the window is captured WITHOUT restoring/activating it.
    _ocr_window_text-style activation would steal focus from the
    search box mid-send and the subsequent Enter/typing would land
    in the wrong application. Screen capture reads the pixels even
    when the window is merely visible, not foreground.
    """

    query_tokens = [
        token
        for token in re.split(r"\s+", query.lower().strip())
        if token
    ]

    if not query_tokens:
        return []

    root_dir = os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    )

    temp_path = os.path.join(root_dir, "data", "_wa_search.png")

    for _attempt in range(max(1, attempts)):
        try:
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)

            width = max(1, right - left)
            height = max(1, bottom - top)

            # Minimized windows sit at -25600: nothing to read and
            # restoring here would steal focus — skip quietly.
            if (
                left < -20000
                or top < -20000
                or right - left < 400
                or bottom - top < 300
            ):
                time.sleep(1.0)
                continue

            # The chat-list column only: below the search box, left
            # side, so chat-pane text can never leak into results.
            strip_right = min(
                left + max(320, int(width * 0.30)),
                right,
            )

            strip_top = top + int(height * 0.10)
            strip_bottom = top + int(height * 0.80)

            from PIL import ImageGrab

            grab = ImageGrab.grab(
                bbox=(
                    left,
                    strip_top,
                    strip_right,
                    strip_bottom,
                )
            )

            grab.save(temp_path)

            ocr_lines = _run_ocr_lines(
                temp_path,
                grab.size[0],
                grab.size[1],
                preserve_case=True,
            )

        except Exception:
            ocr_lines = []

        finally:
            try:
                os.remove(temp_path)

            except OSError:
                pass

        # Group OCR rows into visual lines (same y), top to bottom.
        rows = []

        for x_frac, y_frac, text in sorted(
            ocr_lines,
            key=lambda item: item[1],
        ):
            if rows and abs(y_frac - rows[-1][0]) < 0.02:
                rows[-1][1].append((x_frac, text))

            else:
                rows.append((y_frac, [(x_frac, text)]))

        names = []

        for _y, cells in rows:
            cells.sort(key=lambda item: item[0])

            line_text = " ".join(
                text for _x, text in cells
            ).strip()

            if not line_text:
                continue

            lowered = " ".join(line_text.lower().split())

            # The contact's NAME line always contains the query (that
            # is why WhatsApp matched it); message previews and the
            # chat pane are excluded by the left-column crop above.
            if not all(
                token in lowered
                for token in query_tokens
            ):
                continue

            name = _clean_result_name(line_text)

            if len(name) < 2:
                continue

            if not any(
                name.lower() == existing.lower()
                for existing in names
            ):
                names.append(name)

        if names:
            return names[:6]

        time.sleep(1.0)

    return []


# ------------------------------------------------------------
# Public API
# ------------------------------------------------------------

def send_message(contact: str, message: str) -> dict:
    """
    Send a WhatsApp message to a contact/chat.

    Flow: ensure WhatsApp is running (launch it if not), activate the
    window, focus search (Ctrl+F), paste the contact, pick the chat
    with Enter, verify the chat really opened, paste the message,
    send with Enter.
    """

    contact = (contact or "").strip()
    message = (message or "").strip()

    if not contact or not message:
        return {
            "success": False,
            "error": "I need both a contact and a message to send.",
        }

    hwnd = _ensure_window()

    if hwnd is None:
        if is_whatsapp_running():
            return {
                "success": False,
                "error": (
                    "I couldn't bring the WhatsApp window to the front."
                ),
            }

        return {
            "success": False,
            "error": (
                "I couldn't open WhatsApp. Please open it and sign "
                "in first, then ask me again."
            ),
        }

    # ------------------------------------------------
    # CONTACT SEARCH WITH RETRY: WhatsApp stores contacts in many
    # forms ("Vishwa", "Vishwa Bhaiya", "+91 98765 43210"). One
    # exact-name search misses most of them, so we try progressively
    # looser queries and verify the chat title after each attempt.
    # ------------------------------------------------
    base_words = contact.split()

    queries = [contact]

    if len(base_words) > 1:
        queries.append(base_words[0])

    cleaned = re.sub(r"[^\w\s]", "", contact).strip()

    if cleaned and cleaned.lower() != contact.lower():
        queries.append(cleaned)

    opened = False
    matched_query = contact

    for query in queries:
        if _open_chat_with_query(hwnd, query):
            opened = True
            matched_query = query

            break

        # Clear the search box so the next attempt starts fresh.
        press_key(VK_ESCAPE)
        time.sleep(0.2)

    if not opened:
        if _whatsapp_offline(hwnd):
            return {
                "success": False,
                "error": (
                    "WhatsApp on your computer can't reach your phone "
                    "right now, so I can't send messages. Please check "
                    "your phone has internet and is connected, then "
                    "ask me again."
                ),
            }

        # Offer what the search ACTUALLY showed: the user confirms
        # which visible contact to message instead of guessing
        # spellings ("Vishwa High" was visible in the list while the
        # plain "Vishwa" query failed to open a chat).
        visible = _read_search_results(
            hwnd,
            queries[0] if queries else contact,
            attempts=1,
        )

        if visible:
            return {
                "success": False,
                "error": (
                    f"I found {len(visible)} chats similar to {contact} "
                    "but couldn't open the exact chat, so I did NOT send "
                    "anything. Similar contacts: "
                    + ", ".join(visible[:5])
                    + ". Which one should I message?"
                ),
                "contact_matches": visible,
            }

        return {
            "success": False,
            "error": (
                f"I searched for {contact} but couldn't find the chat, "
                "so I did NOT send anything. Please check the contact "
                "name and try again."
            ),
        }

    # The chat is verified open, but focus may have drifted while
    # verification ran (notifications, popups). The message MUST be
    # typed into WhatsApp's composer, so re-assert the foreground.
    if not _window_is_foreground(hwnd):
        if not _activate_window(hwnd):
            return {
                "success": False,
                "error": (
                    "The chat opened but I lost the window focus before "
                    "I could type — nothing was sent. Try again, sir."
                ),
            }

    # Click into the message composer area before typing: the chat
    # list or search box could hold focus after Escape. The composer
    # sits in the lower half of the right (chat) pane.
    try:
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)

        width = max(1, right - left)
        height = max(1, bottom - top)

        import win32api

        win32api.SetCursorPos(
            (
                left + int(width * 0.60),
                top + int(height * 0.88),
            )
        )

        user32.mouse_event(
            0x0002, 0, 0, 0, 0
        )  # MOUSEEVENTF_LEFTDOWN

        user32.mouse_event(
            0x0004, 0, 0, 0, 0
        )  # MOUSEEVENTF_LEFTUP

        time.sleep(0.4)

    except Exception:
        pass

    if not _paste_text(message):
        return {
            "success": False,
            "error": "I couldn't use the clipboard to type the message.",
        }

    time.sleep(0.5)

    press_key(VK_RETURN)
    time.sleep(1.0)

    # SEND VERIFICATION: the message must actually appear in the
    # chat. OCR the conversation area and look for the message text
    # (or its first words). Without this, a focus loss could "send"
    # into the void while JARVIS claims success.
    sent_verified = False

    try:
        check_words = [
            word.lower()
            for word in message.split()[:4]
            if len(word) > 2
        ]

        if check_words:
            for _attempt in range(2):
                ocr_lines = _read_chat_area(hwnd)

                chat_text = " ".join(
                    text for _x, _y, text in ocr_lines
                )

                if all(word in chat_text for word in check_words):
                    sent_verified = True
                    break

                time.sleep(1.0)

    except Exception:
        pass

    if not sent_verified:
        # Not proven delivered: be honest instead of optimistic. The
        # chat IS open, so the user can glance and hit Enter if the
        # message is sitting in the composer.
        return {
            "success": False,
            "error": (
                f"The chat with {matched_query} is open, but I couldn't "
                "confirm the message actually went through. Please check "
                "the composer — if it's still sitting there, one Enter "
                "sends it."
            ),
        }

    return {
        "success": True,
        "message": (
            f"Message sent to {matched_query} on WhatsApp."
        ),
    }


def _read_chat_area(hwnd, attempts: int = 1):
    """
    OCR the conversation (right) pane WITHOUT touching focus. Used
    to verify a sent message actually appears in the chat.
    """

    root_dir = os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    )

    temp_path = os.path.join(root_dir, "data", "_wa_chat.png")

    lines = []

    for _attempt in range(max(1, attempts)):
        try:
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)

            width = max(1, right - left)
            height = max(1, bottom - top)

            if (
                left < -20000
                or top < -20000
                or right - left < 400
                or bottom - top < 300
            ):
                continue

            from PIL import ImageGrab

            grab = ImageGrab.grab(
                bbox=(
                    left + int(width * 0.30),
                    top + int(height * 0.12),
                    right,
                    top + int(height * 0.85),
                )
            )

            grab.save(temp_path)

            lines = _run_ocr_lines(
                temp_path,
                grab.size[0],
                grab.size[1],
                preserve_case=False,
            )

        except Exception:
            lines = []

        finally:
            try:
                os.remove(temp_path)

            except OSError:
                pass

        if lines:
            break

        time.sleep(0.8)

    return lines


def search_contacts(query: str, alias_fallback: bool = True) -> dict:
    """
    Search WhatsApp chats by name WITHOUT opening a chat or sending
    anything: type the query into the search box, then read the
    visible result list (left column) with OCR. Used for the clarify
    flow when several contacts match a spoken name.

    When the direct query reads nothing, saved memory aliases are
    tried ("mummy" -> whatever the user taught: e.g. a stored real
    name), because WhatsApp only matches what is in the contact list.
    """

    query = (query or "").strip()

    if not query:
        return {
            "success": False,
            "error": "I need a name to search WhatsApp for.",
        }

    result = _search_contacts_raw(query)

    if (
        result.get("success")
        or not alias_fallback
    ):
        return result

    # ------------------------------------------------
    # ALIAS FALLBACK: household names like "mummy", "papa",
    # "bhaiya" are rarely stored verbatim in WhatsApp. Saved memory
    # facts supply the real name: "remember that mummy means
    # Anisha" or "mummy is Anisha Gupta" turns the spoken alias
    # into something WhatsApp's search can match.
    # ------------------------------------------------
    try:
        from assistant.memory import MemoryStore

        facts = MemoryStore().recall(query).get("results") or []

    except Exception:
        return result

    for fact in facts:
        fact_text = str(fact)

        match = re.search(
            r"[\w\s]{2,40}?(?:\bfor\b|\bmeans\b|\bis\b)\s+"
            r"([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?)",
            fact_text,
        )

        if not match:
            continue

        aliased = match.group(1).strip()

        if aliased.lower() == query.lower():
            continue

        retry = _search_contacts_raw(aliased)

        if retry.get("success"):
            retry["resolved_alias"] = aliased

            return retry

    return result


def _search_contacts_raw(query: str) -> dict:
    """
    The original search: type into WhatsApp's search box and OCR the
    result list. No alias handling.
    """

    query = (query or "").strip()

    if not query:
        return {
            "success": False,
            "error": "I need a name to search WhatsApp for.",
        }

    hwnd = _ensure_window()

    if hwnd is None:
        if is_whatsapp_running():
            return {
                "success": False,
                "error": (
                    "I couldn't bring the WhatsApp window to the front."
                ),
            }

        return {
            "success": False,
            "error": (
                "I couldn't open WhatsApp. Please open it and sign "
                "in first, then ask me again."
            ),
        }

    if not _window_is_foreground(hwnd):
        _activate_window(hwnd)

        time.sleep(0.8)

    press_key(VK_ESCAPE)
    time.sleep(0.3)
    press_combo(VK_CONTROL, VK_F)
    time.sleep(0.6)

    if not _paste_text(query):
        return {
            "success": False,
            "error": "I couldn't use the clipboard for the search.",
        }

    time.sleep(1.8)

    names = _read_search_results(hwnd, query)

    # Close the search overlay; never leave WhatsApp mid-search.
    press_key(VK_ESCAPE)
    time.sleep(0.3)

    if not names:
        if _whatsapp_offline(hwnd):
            return {
                "success": False,
                "error": (
                    "WhatsApp on your computer can't reach your phone "
                    "right now, so I can't read your chats. Please check "
                    "your phone is connected, then ask me again."
                ),
            }

        return {
            "success": False,
            "error": (
                f"I searched WhatsApp for {query} but couldn't read "
                "any matching chats."
            ),
        }

    return {
        "success": True,
        "query": query,
        "contacts": names,
        "message": (
            f"I found {len(names)} matching chats: "
            + ", ".join(names[:5])
            + "."
        ),
    }


if __name__ == "__main__":
    print("WhatsApp running:", is_whatsapp_running())
    print("Window:", find_whatsapp_window())
