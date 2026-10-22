"""Where everything personal lives: a data folder outside the repo (JOB_SCANNER_DATA, default ~/.job_scanner).

Nothing about the person using the app is ever written into the repo: the profile, résumé, captured jobs, AI
usage and the pairing token all go here.
"""

from __future__ import annotations

import json
import os
import secrets
import threading
from pathlib import Path

_lock = threading.RLock()


def data_dir() -> Path:
    d = Path(os.environ.get("JOB_SCANNER_DATA") or Path.home() / ".job_scanner").expanduser()
    d.mkdir(parents=True, exist_ok=True)
    return d


def path(name: str) -> Path:
    return data_dir() / name


def read_json(name: str, default):
    try:
        return json.loads(path(name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(name: str, data) -> None:
    p = path(name)
    with _lock:
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(p)


def settings() -> dict:
    return read_json("settings.json", {})


def save_settings(changes: dict) -> dict:
    with _lock:
        s = settings()
        s.update(changes)
        write_json("settings.json", s)
        return s


def pairing_token(rotate: bool = False) -> str:
    """The shared secret the extension sends with every capture, so no other page can post jobs in."""
    with _lock:
        s = settings()
        if rotate or not s.get("token"):
            s = save_settings({"token": secrets.token_urlsafe(24)})
        return s["token"]


BACKUP_KEEP = 14


def backup(today: str | None = None) -> Path | None:
    """Copy every JSON file in the data folder to backups/YYYY-MM-DD (once a day; the newest BACKUP_KEEP kept)."""
    import shutil
    from datetime import date

    day = today or date.today().isoformat()
    root = data_dir() / "backups"
    dest = root / day
    if dest.exists():
        return None
    files = [f for f in data_dir().glob("*.json")]
    if not files:
        return None
    dest.mkdir(parents=True, exist_ok=True)
    for f in files:
        shutil.copy2(f, dest / f.name)
    for old in sorted(p for p in root.iterdir() if p.is_dir())[:-BACKUP_KEEP]:
        shutil.rmtree(old, ignore_errors=True)
    return dest
