"""Start with Windows: a small script in your Startup folder runs the app, hidden, when you sign in.

Only on Windows. On a Mac or Linux, run start.sh from your login items instead.
"""

from __future__ import annotations

import os
import sys

NAME = "Job Scanner.vbs"


def supported() -> bool:
    return os.name == "nt" and bool(os.environ.get("APPDATA"))


def path() -> str:
    return os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs", "Startup", NAME)


def enabled() -> bool:
    return supported() and os.path.exists(path())


def _pythonw() -> str:
    exe = sys.executable or "pythonw"
    w = os.path.join(os.path.dirname(exe), "pythonw.exe")
    return w if os.path.exists(w) else exe


def script(repo: str, python: str) -> str:
    """The .vbs file: run `python -m job_scanner serve` from the repo with no window."""
    q = lambda s: s.replace('"', '""')  # noqa: E731
    return ('Set sh = CreateObject("WScript.Shell")\r\n'
            f'sh.CurrentDirectory = "{q(repo)}"\r\n'
            f'sh.Run """{q(python)}"" -m job_scanner serve", 0, False\r\n')


def enable() -> str:
    if not supported():
        raise OSError("Start with Windows only works on Windows.")
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.makedirs(os.path.dirname(path()), exist_ok=True)
    with open(path(), "w", encoding="utf-8") as fh:
        fh.write(script(repo, _pythonw()))
    return path()


def disable() -> bool:
    if enabled():
        os.remove(path())
        return True
    return False


def set(on: bool) -> bool:  # noqa: A001
    enable() if on else disable()
    return enabled()
