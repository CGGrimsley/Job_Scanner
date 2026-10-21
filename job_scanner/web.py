"""The local app: `python -m job_scanner serve`. A stdlib HTTP server on 127.0.0.1 serving the web app and the
API the Chrome extension posts captured jobs to."""

from __future__ import annotations

import base64
import hmac
import ipaddress
import json
import mimetypes
import os
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import __version__, ai, jobs, profile, resume, store

STATIC = Path(__file__).with_name("static")
EXTENSION_MANIFEST = Path(__file__).resolve().parent.parent / "extension" / "manifest.json"
MAX_BODY = 2_000_000
MAX_UPLOAD = 12_000_000
DEFAULT_PORT = 8766

SETTINGS_DEFAULTS = {"auto_analyze": True, "auto_min_score": 40, "ai_daily_limit": 60}


class BadRequest(ValueError):
    pass


def app_settings() -> dict:
    s = store.settings()
    return {k: s.get(k, v) for k, v in SETTINGS_DEFAULTS.items()}


def host_allowed(host: str) -> bool:
    """DNS rebinding guard: only loopback names, IP literals and hosts listed in JOB_SCANNER_ALLOWED_HOSTS."""
    try:
        name = urlparse("//" + (host or "").strip().lower()).hostname or ""
    except ValueError:
        return False
    if not name:
        return False
    if name in ("localhost", "localhost.") or name.endswith(".localhost"):
        return True
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        pass
    allowed = {h.strip().lower() for h in os.environ.get("JOB_SCANNER_ALLOWED_HOSTS", "").split(",") if h.strip()}
    return name in allowed


def extension_version() -> str:
    try:
        return json.loads(EXTENSION_MANIFEST.read_text(encoding="utf-8")).get("version", "")
    except (OSError, ValueError):
        return ""


def make_handler(ledger: jobs.Ledger):
    state = {"profile": profile.load()}
    analyzing: dict = {}
    analyzing_lock = threading.Lock()

    def current_profile() -> dict:
        return state["profile"]

    def analyze(key: str, force: bool = False, auto: bool = False) -> dict:
        rec = ledger.get(key)
        if rec is None:
            raise KeyError(key)
        p = current_profile()
        fp = profile.fingerprint(p)
        if not force and jobs.ai_current(rec, fp):
            return {"job": jobs.public(rec), "mark": jobs.mark_for(rec), "cached": True}
        if auto:
            s = app_settings()
            if not s["auto_analyze"]:
                return {"skipped": "Automatic analysis is off (turn it on in Setup).", "mark": jobs.mark_for(rec)}
            if rec["rules"]["score"] < int(s["auto_min_score"]):
                return {"skipped": f"Rules score {rec['rules']['score']} is under {s['auto_min_score']}, so Claude wasn't asked.",
                        "mark": jobs.mark_for(rec)}
            if ai.over_limit():
                return {"skipped": "Today's Claude limit is used up (change it in Setup).", "mark": jobs.mark_for(rec)}
            if not rec.get("description"):
                return {"skipped": "Open the posting so its full description is captured first.", "mark": jobs.mark_for(rec)}
        if profile.is_empty(p):
            raise BadRequest("Fill in your Profile first (target roles, skills and résumé) so Claude has something to go on.")
        with analyzing_lock:
            lock = analyzing.setdefault(key, threading.Lock())
        with lock:
            rec = ledger.get(key)
            if not force and jobs.ai_current(rec, fp):  # someone else just did it
                return {"job": jobs.public(rec), "mark": jobs.mark_for(rec), "cached": True}
            out = ai.analyze_job(rec, profile.for_prompt(p))
            rec = ledger.set_analysis(key, out, fp)
        return {"job": jobs.public(rec), "mark": jobs.mark_for(rec)}

    class Handler(BaseHTTPRequestHandler):
        server_version = f"JobScanner/{__version__}"

        def log_message(self, fmt, *args):
            if os.environ.get("JOB_SCANNER_DEBUG"):
                super().log_message(fmt, *args)

        def parse_request(self):
            if not super().parse_request():
                return False
            if not host_allowed(self.headers.get("Host", "")):
                self.send_error(HTTPStatus.MISDIRECTED_REQUEST, "Unknown host")
                return False
            return True

        # -- helpers --
        def _cors(self):
            origin = self.headers.get("Origin") or ""
            if origin.startswith("chrome-extension://") and urlparse(self.path).path.startswith("/api/capture"):
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Scanner-Token")
                self.send_header("Access-Control-Allow-Methods", "GET, POST")
                if self.headers.get("Access-Control-Request-Private-Network"):
                    self.send_header("Access-Control-Allow-Private-Network", "true")

        def do_OPTIONS(self):
            self.send_response(HTTPStatus.NO_CONTENT)
            self._cors()
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _send(self, body: bytes, ctype: str, status=HTTPStatus.OK, extra: dict | None = None):
            self.send_response(status)
            self._cors()
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, payload, status=HTTPStatus.OK):
            self._send(json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"),
                       "application/json; charset=utf-8", status)

        def _error(self, msg, status=HTTPStatus.BAD_REQUEST):
            self._json({"error": msg}, status)

        def _body(self, limit: int = MAX_BODY) -> dict:
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                raise BadRequest("Bad Content-Length.") from None
            if n < 0 or n > limit:
                raise BadRequest("Request too large.")
            raw = self.rfile.read(n) if n else b"{}"
            try:
                data = json.loads(raw or b"{}")
            except ValueError:
                raise BadRequest("Invalid JSON.") from None
            if not isinstance(data, dict):
                raise BadRequest("Expected a JSON object.")
            return data

        def _same_origin(self) -> bool:
            """Blocks other pages in the browser from posting to the app (cross-site form posts)."""
            origin = self.headers.get("Origin")
            return not origin or urlparse(origin).netloc == self.headers.get("Host")

        def _token_ok(self) -> bool:
            return hmac.compare_digest(self.headers.get("X-Scanner-Token") or "", store.pairing_token())

        def _static(self, path: str):
            rel = "index.html" if path in ("", "/") else path.lstrip("/")
            f = (STATIC / rel).resolve()
            if STATIC.resolve() not in f.parents or not f.is_file():
                return self._error("Not found", HTTPStatus.NOT_FOUND)
            ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype.endswith("javascript"):
                ctype += "; charset=utf-8"
            self._send(f.read_bytes(), ctype)

        def _guard(self, fn):
            try:
                fn()
            except BadRequest as e:
                self._error(str(e))
            except ValueError as e:
                self._error(str(e))
            except KeyError:
                self._error("No such job.", HTTPStatus.NOT_FOUND)
            except resume.ResumeError as e:
                self._error(str(e))
            except ai.AIError as e:
                self._error(str(e), HTTPStatus.BAD_GATEWAY)

        # -- GET --
        def do_GET(self):
            self._guard(self._get)

        def _get(self):
            url = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            path = unquote(url.path)
            if path.startswith("/api/capture"):
                if not self._token_ok():
                    return self._error("Pair the extension: copy the token from Setup in the app.", HTTPStatus.UNAUTHORIZED)
                if path == "/api/capture/ping":
                    return self._json({"ok": True, "jobs": len(ledger.jobs), "extension_version": extension_version(),
                                       "profile_ready": not profile.is_empty(current_profile())})
                if path == "/api/capture/job":
                    rec = ledger.get(f"{q.get('source', '')}:{q.get('id', '')}")
                    if rec is None:
                        return self._error("Not captured yet.", HTTPStatus.NOT_FOUND)
                    return self._json({"job": jobs.public(rec), "mark": jobs.mark_for(rec)})
                return self._error("Not found", HTTPStatus.NOT_FOUND)
            if path.startswith("/api/") and not self._same_origin():
                return self._error("Forbidden", HTTPStatus.FORBIDDEN)
            if path == "/api/state":
                return self._json({"version": __version__, "profile": current_profile(), "ai": ai.describe_backend(),
                                   "settings": app_settings(), "counts": ledger.counts(), "sources": jobs.SOURCES,
                                   "statuses": jobs.STATUSES, "extension_version": extension_version(),
                                   "choices": {"remote": profile.REMOTE_CHOICES, "seniority": profile.SENIORITY_CHOICES,
                                               "job_types": profile.JOB_TYPE_CHOICES}})
            if path == "/api/token":
                return self._json({"token": store.pairing_token()})
            if path == "/api/jobs":
                recs = ledger.listing(q)
                limit = int(q.get("limit") or 300)
                return self._json({"jobs": [jobs.public(r) for r in recs[:limit]], "total": len(recs)})
            if path == "/api/jobs.csv":
                return self._send(ledger.csv().encode("utf-8"), "text/csv; charset=utf-8",
                                  extra={"Content-Disposition": 'attachment; filename="jobs.csv"'})
            if path.startswith("/api/jobs/"):
                rec = ledger.get(path[len("/api/jobs/"):])
                if rec is None:
                    raise KeyError(path)
                return self._json({"job": jobs.public(rec),
                                   "ai_current": jobs.ai_current(rec, profile.fingerprint(current_profile()))})
            if path == "/api/ai/usage":
                return self._json(ai.usage_summary())
            if path.startswith("/api/"):
                return self._error("Not found", HTTPStatus.NOT_FOUND)
            return self._static(path)

        # -- POST --
        def do_POST(self):
            self._guard(self._post)

        def _post(self):
            path = unquote(urlparse(self.path).path)
            if path.startswith("/api/capture"):
                if not self._token_ok():
                    return self._error("Pair the extension: copy the token from Setup in the app.", HTTPStatus.UNAUTHORIZED)
                data = self._body()
                if path == "/api/capture":
                    rows = data.get("jobs")
                    if not isinstance(rows, list):
                        raise BadRequest("Expected a list of jobs.")
                    return self._json(ledger.add(rows[:300], current_profile()))
                if path == "/api/capture/analyze":
                    key = f"{data.get('source', '')}:{data.get('id', '')}"
                    return self._json(analyze(key, force=bool(data.get("force")), auto=bool(data.get("auto"))))
                if path == "/api/capture/status":
                    key = f"{data.get('source', '')}:{data.get('id', '')}"
                    rec = ledger.update(key, {"status": data.get("status", "")})
                    return self._json({"mark": jobs.mark_for(rec)})
                return self._error("Not found", HTTPStatus.NOT_FOUND)
            if not self._same_origin():
                return self._error("Forbidden", HTTPStatus.FORBIDDEN)
            data = self._body(MAX_UPLOAD if path == "/api/profile/resume-file" else MAX_BODY)
            if path == "/api/profile":
                state["profile"] = profile.save(data.get("profile") or {})
                if data.get("rescore", True):
                    ledger.rescore_all(state["profile"])
                return self._json({"profile": state["profile"], "counts": ledger.counts()})
            if path == "/api/profile/resume-file":
                try:
                    blob = base64.b64decode(str(data.get("data") or ""), validate=True)
                except ValueError:
                    raise BadRequest("The file didn't upload properly.") from None
                return self._json(resume.read(str(data.get("filename") or ""), blob))
            if path == "/api/profile/suggest":
                text = str(data.get("resume") or current_profile()["resume"])
                if len(text) < 100:
                    raise BadRequest("Add your résumé first.")
                return self._json(ai.suggest_from_text(text))
            if path == "/api/settings":
                changes = {}
                if "auto_analyze" in data:
                    changes["auto_analyze"] = bool(data["auto_analyze"])
                for k, lo, hi in (("auto_min_score", 0, 100), ("ai_daily_limit", 0, 1000)):
                    if k in data:
                        try:
                            changes[k] = max(lo, min(hi, int(data[k])))
                        except (TypeError, ValueError):
                            raise BadRequest(f"{k} must be a number.") from None
                store.save_settings(changes)
                return self._json({"settings": app_settings(), "ai": ai.describe_backend()})
            if path == "/api/token/rotate":
                return self._json({"token": store.pairing_token(rotate=True)})
            if path == "/api/rescore":
                return self._json({"rescored": ledger.rescore_all(current_profile())})
            if path == "/api/jobs/clear":
                return self._json({"removed": ledger.clear(keep_tracked=bool(data.get("keep_tracked", True)))})
            if path.startswith("/api/jobs/"):
                rest = path[len("/api/jobs/"):]
                key, _, action = rest.rpartition("/")
                if action == "analyze":
                    return self._json(analyze(key, force=bool(data.get("force"))))
                if action == "cover-letter":
                    rec = ledger.get(key)
                    if rec is None:
                        raise KeyError(key)
                    if profile.is_empty(current_profile()):
                        raise BadRequest("Fill in your Profile first.")
                    letter = ai.cover_letter(rec, profile.for_prompt(current_profile()), str(data.get("notes") or ""))
                    return self._json({"job": jobs.public(ledger.set_letter(key, letter))})
                if action == "update":
                    return self._json({"job": jobs.public(ledger.update(key, data))})
                if action == "delete":
                    ledger.delete(key)
                    return self._json({"ok": True})
            return self._error("Not found", HTTPStatus.NOT_FOUND)

    return Handler


def serve(port: int = DEFAULT_PORT, host: str = "127.0.0.1", open_browser: bool = False) -> None:
    ledger = jobs.Ledger()
    httpd = ThreadingHTTPServer((host, port), make_handler(ledger))
    url = f"http://127.0.0.1:{port}/"
    b = ai.describe_backend()
    print(f"Job Scanner is running at {url}  (data: {store.data_dir()})")
    print(f"Claude: {b['label']}" + ("" if b["backend"] else "  -- install Claude Code and sign in to turn on AI guidance"))
    print("Ctrl-C to stop.")
    if open_browser:
        import webbrowser

        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
