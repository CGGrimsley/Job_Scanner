"""Command line: `python -m job_scanner serve | token | reset | doctor`."""

from __future__ import annotations

import argparse
import os

from . import __version__, ai, jobs, store, web


def _load_env(path: str = ".env") -> None:
    """KEY=value lines from .env into the environment (without overriding what's already set)."""
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                v = v.strip().strip('"').strip("'")
                if v and k.strip() not in os.environ:
                    os.environ[k.strip()] = v
    except OSError:
        pass


def main(argv=None) -> int:
    _load_env()
    ap = argparse.ArgumentParser(prog="job_scanner", description="Job Scanner: AI guidance on the jobs you browse.")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("serve", help="run the app (default)")
    s.add_argument("--port", type=int, default=int(os.environ.get("JOB_SCANNER_PORT", web.DEFAULT_PORT)))
    s.add_argument("--host", default=os.environ.get("JOB_SCANNER_HOST", "127.0.0.1"))
    s.add_argument("--open", action="store_true", help="open the app in your browser")
    t = sub.add_parser("token", help="print the extension pairing token")
    t.add_argument("--rotate", action="store_true", help="make a new one (the extension must be paired again)")
    r = sub.add_parser("reset", help="clear captured jobs")
    r.add_argument("--all", action="store_true", help="also clear jobs you're tracking")
    r.add_argument("-y", action="store_true", help="don't ask")
    sub.add_parser("doctor", help="check Claude and the data folder")
    args = ap.parse_args(argv)

    if args.cmd in (None, "serve"):
        web.serve(port=getattr(args, "port", web.DEFAULT_PORT), host=getattr(args, "host", "127.0.0.1"),
                  open_browser=getattr(args, "open", False))
        return 0
    if args.cmd == "token":
        print(store.pairing_token(rotate=args.rotate))
        return 0
    if args.cmd == "reset":
        if not args.y and input("Clear captured jobs? [y/N] ").strip().lower() != "y":
            return 1
        print(f"Removed {jobs.Ledger().clear(keep_tracked=not args.all)} jobs.")
        return 0
    if args.cmd == "doctor":
        b = ai.describe_backend()
        print(f"Data folder: {store.data_dir()}")
        print(f"Claude Code installed: {'yes' if b['claude_installed'] else 'no'}")
        print(f"Claude: {b['label']}")
        if b["backend"]:
            try:
                ai.ask_json("Answer briefly.", "Reply with ok=true.", {"type": "object", "properties": {"ok": {"type": "boolean"}},
                            "required": ["ok"], "additionalProperties": False}, kind="doctor")
                print("Test call: OK")
            except ai.AIError as e:
                print(f"Test call failed: {e}")
                return 1
        return 0
    return 0
