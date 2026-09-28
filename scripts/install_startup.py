"""
Install (or remove) JARVIS to start automatically with Windows.

Registers the app in HKCU\\...\\Run so it launches at login — no admin
rights required. Run from the project root:

    python scripts/install_startup.py           # install
    python scripts/install_startup.py --remove  # remove
"""

import os
import sys
from pathlib import Path

import winreg

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "JARVIS"


def command() -> str:
    # pythonw.exe: no console window at login.
    pythonw = Path(sys.executable).parent / "pythonw.exe"

    root = Path(__file__).resolve().parent.parent

    return f'"{pythonw}" "{root / "app" / "main.py"}"'


def install():
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        RUN_KEY,
        0,
        winreg.KEY_SET_VALUE,
    ) as key:
        winreg.SetValueEx(
            key,
            VALUE_NAME,
            0,
            winreg.REG_SZ,
            command(),
        )

    print("JARVIS will now start with Windows.")
    print("Command:", command())


def remove():
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            RUN_KEY,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.DeleteValue(key, VALUE_NAME)

        print("JARVIS startup entry removed.")

    except FileNotFoundError:
        print("JARVIS was not registered for startup.")


if __name__ == "__main__":
    if "--remove" in sys.argv:
        remove()
    else:
        install()
