"""
Desktop shortcut launcher — the deterministic fallback for
"open the Instagram shortcut on my desktop".

Clicking pixels to launch a shortcut is fragile (scaling, icon
position, resolution). The RELIABLE path is: enumerate the .lnk/.url
files on the user's Desktop and the Public Desktop, fuzzy-match the
spoken name, and os.startfile the target directly. Pixel clicking is
only for things that cannot be launched this way.

Also used by the fuzzy entity resolver (STT mishears) to find shortcut
names worth suggesting ("open comment" -> did you mean "Comet"?).
"""

import os
from pathlib import Path

from rapidfuzz import fuzz


def desktop_dirs():
    """User Desktop + Public Desktop (where installers put icons)."""

    dirs = []

    user_desktop = Path.home() / "Desktop"
    dirs.append(user_desktop)

    public = os.environ.get("PUBLIC")

    if public:
        dirs.append(Path(public) / "Desktop")

    # OneDrive often redirects the Desktop on Windows 11.
    try:
        import ctypes

        buf = ctypes.create_unicode_buffer(260)

        # CSIDL_DESKTOPDIRECTORY = 0x10 -> current user's desktop.
        CSIDL_DESKTOPDIRECTORY = 0x10

        if ctypes.windll.shell32.SHGetFolderPathW(
            None, CSIDL_DESKTOPDIRECTORY, None, 0, buf
        ) == 0 and buf.value:
            resolved = Path(buf.value)

            if resolved not in dirs:
                dirs.insert(0, resolved)

    except Exception:
        pass

    seen = set()
    unique = []

    for entry in dirs:
        key = str(entry).lower()

        if key not in seen and entry.exists():
            seen.add(key)
            unique.append(entry)

    return unique


def list_shortcuts():
    """
    Every .lnk / .url on the desktops, as dicts:
    {"name": "Instagram", "path": "C:\\...\\Instagram.url", "stem": "instagram"}
    """

    shortcuts = []

    for folder in desktop_dirs():
        try:
            entries = list(folder.iterdir())

        except OSError:
            continue

        for entry in entries:
            suffix = entry.suffix.lower()

            if suffix not in {".lnk", ".url"}:
                continue

            shortcuts.append(
                {
                    "name": entry.stem,
                    "path": str(entry),
                    "stem": entry.stem.lower().strip(),
                    "folder": str(folder),
                }
            )

    return shortcuts


def find_shortcut(spoken_name: str, threshold: float = 55.0):
    """
    Fuzzy-match a spoken shortcut name against the desktops.
    Returns (shortcut_dict, score) or (None, best_score).
    "instagram" -> Instagram.url, "comet" -> Comet.lnk.
    """

    wanted = (spoken_name or "").lower().strip()

    wanted = wanted.removeprefix("the ").strip()
    wanted = wanted.removesuffix(" shortcut").strip()
    wanted = wanted.removesuffix(" icon").strip()
    wanted = wanted.removesuffix(" app").strip()

    if not wanted:
        return None, 0.0

    best = None
    best_score = 0.0

    for shortcut in list_shortcuts():
        name = shortcut["stem"]

        score = max(
            fuzz.ratio(wanted, name),
            fuzz.partial_ratio(wanted, name),
            fuzz.token_set_ratio(wanted, name),
        )

        if score > best_score:
            best = shortcut
            best_score = score

    if best is not None and best_score >= threshold:
        return best, best_score

    return None, best_score


def open_shortcut(spoken_name: str):
    """
    Launch the best-matching desktop shortcut directly.
    Returns a tool-result dict (never raises).
    """

    shortcut, score = find_shortcut(spoken_name)

    if shortcut is None:
        return {
            "success": False,
            "error": (
                f"No shortcut named '{spoken_name}' on the desktop."
            ),
        }

    try:
        os.startfile(shortcut["path"])

    except OSError as error:
        return {
            "success": False,
            "error": f"Could not open {shortcut['name']}: {error}",
        }

    return {
        "success": True,
        "message": f"Opened the {shortcut['name']} shortcut, sir.",
        "shortcut": shortcut["name"],
        "path": shortcut["path"],
        "match_score": round(score, 1),
    }
