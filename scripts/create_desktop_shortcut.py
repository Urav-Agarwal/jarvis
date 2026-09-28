"""
Create a desktop shortcut that launches JARVIS without a console
window (pythonw.exe directly — no VBScript involved).

Run from the project root:
    python scripts/create_desktop_shortcut.py
"""

import os
import sys
from pathlib import Path

import winreg
import win32com.client


def root_path() -> Path:
    return Path(__file__).resolve().parent.parent


def desktop_path() -> Path:
    """
    Resolve the real Desktop folder (handles OneDrive redirection,
    which Path.home()/"Desktop" misses).
    """

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion"
            r"\Explorer\User Shell Folders",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "Desktop")

        return Path(os.path.expandvars(value))

    except OSError:
        return Path.home() / "Desktop"


def create_shortcut():
    root = root_path()

    pythonw = Path(sys.executable).parent / "pythonw.exe"

    desktop = desktop_path()

    shortcut_path = desktop / "JARVIS.lnk"

    shell = win32com.client.Dispatch("WScript.Shell")

    shortcut = shell.CreateShortCut(str(shortcut_path))

    shortcut.TargetPath = str(pythonw)
    shortcut.Arguments = f'"{root / "app" / "main.py"}"'
    shortcut.WorkingDirectory = str(root)
    shortcut.Description = "JARVIS — always-on desktop assistant"

    # Glowing-orb icon.
    icon_path = root / "assets" / "jarvis.ico"

    if icon_path.exists():
        shortcut.IconLocation = str(icon_path)

    shortcut.save()

    # Remove the old broken VBS launcher if present.
    legacy = root / "scripts" / "jarvis_launch.vbs"

    if legacy.exists():
        legacy.unlink()

    print("Desktop shortcut created:", shortcut_path)
    print("Target:", pythonw)


if __name__ == "__main__":
    create_shortcut()
