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
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import __version__, advice, ai, docx, insights, jobs, pdf, places, profile, resume, signals, store

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


def unsupported_numbers(text: str, source: str) -> list:
    """Lines of a tailored résumé with a number, percentage or dollar figure that none of the person's own résumés
    contain: the one thing worth double-checking by hand, since a made-up metric is the easiest lie to slip in."""
    import re

    def nums(t):
        return {n.replace(",", "").rstrip(".") for n in re.findall(r"\d[\d,]*(?:\.\d+)?", t)}

    known = nums(source)
    out = []
    for line in text.splitlines():
        if nums(line) - known:
            out.append(line.strip().lstrip("-* ").strip())
    return out[:10]


def export_name(rec: dict, what: str, ext: str) -> str:
    import re

    base = f"{what} - {rec.get('company') or 'job'} - {rec.get('title') or ''}"
    return re.sub(r'[\\/:*?"<>|\r\n]+', "", base).strip(" -")[:110] + "." + ext


def export_doc(rec: dict, what: str, fmt: str) -> tuple:
    """A cover letter or tailored résumé as a file: (bytes, content type, file name)."""
    doc = rec.get({"letter": "cover_letter", "resume": "tailored"}.get(what, ""))
    if not doc or not doc.get("text"):
        raise BadRequest("Write it first.")
    label = "Cover letter" if what == "letter" else "Resume"
    if fmt == "pdf":
        body, ctype = pdf.from_text(doc["text"], letter=what == "letter"), "application/pdf"
    elif fmt == "docx":
        body, ctype = docx.from_text(doc["text"]), "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif fmt == "txt":
        body, ctype = doc["text"].encode("utf-8"), "text/plain; charset=utf-8"
    else:
        raise BadRequest("Format must be pdf, docx or txt.")
    return body, ctype, export_name(rec, label, fmt)


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
            return {"job": ledger.public(rec), "mark": ledger.mark(rec), "cached": True}
        if auto:
            s = app_settings()
            if not s["auto_analyze"]:
                return {"skipped": "Automatic analysis is off (turn it on in Setup).", "mark": ledger.mark(rec)}
            if rec["rules"]["score"] < int(s["auto_min_score"]):
                return {"skipped": f"Rules score {rec['rules']['score']} is under {s['auto_min_score']}, so Claude wasn't asked.",
                        "mark": ledger.mark(rec)}
            if ai.over_limit():
                return {"skipped": "Today's Claude limit is used up (change it in Setup).", "mark": ledger.mark(rec)}
            if not rec.get("description"):
                return {"skipped": "Open the posting so its full description is captured first.", "mark": ledger.mark(rec)}
        if profile.is_empty(p):
            raise BadRequest("Fill in your Profile first (target roles, skills and résumé) so Claude has something to go on.")
        with analyzing_lock:
            lock = analyzing.setdefault(key, threading.Lock())
        with lock:
            rec = ledger.get(key)
            if not force and jobs.ai_current(rec, fp):  # someone else just did it
                return {"job": ledger.public(rec), "mark": ledger.mark(rec), "cached": True}
            warn = signals.warnings(rec, ledger.siblings(rec))
            out = ai.analyze_job(rec, profile.for_prompt(p), "\n".join("- " + w["text"] for w in warn))
            rec = ledger.set_analysis(key, out, fp)
        return {"job": ledger.public(rec), "mark": ledger.mark(rec)}

    def write_letter(key: str, data: dict) -> dict:
        rec = ledger.get(key)
        if rec is None:
            raise KeyError(key)
        p = current_profile()
        if not p["resumes"]:
            raise BadRequest("Add a résumé on your Profile first: the letter is written from it.")
        name = str(data.get("resume") or "")
        if name and name not in {r["name"] for r in p["resumes"]}:
            raise BadRequest("No résumé by that name.")
        letter = ai.cover_letter(rec, profile.for_prompt(p), str(data.get("notes") or ""), name, str(data.get("tone") or "standard"))
        return ledger.set_letter(key, letter, name)

    def tailor(key: str, data: dict) -> dict:
        rec = ledger.get(key)
        if rec is None:
            raise KeyError(key)
        p = current_profile()
        if not p["resumes"]:
            raise BadRequest("Add a résumé on your Profile first: the tailored one is built from it.")
        name = str(data.get("resume") or "")
        if name and name not in {r["name"] for r in p["resumes"]}:
            raise BadRequest("No résumé by that name.")
        out = ai.tailor_resume(rec, profile.for_prompt(p), name)
        text = str(out.get("resume") or "").strip()
        doc = {"text": text, "resume": name, "changes": out.get("changes") or [], "left_out": out.get("left_out") or [],
               "check": unsupported_numbers(text, profile.all_resume_text(p) + "\n" + p["about_me"])}
        return ledger.set_doc(key, "tailored", doc)

    def answers(key: str, questions: list | None = None) -> list:
        rec = ledger.get(key)
        if rec is None:
            raise KeyError(key)
        p = current_profile()
        if not p["resumes"] and not p["about_me"]:
            raise BadRequest("Add a résumé on your Profile first: answers are written from it.")
        return ai.answer_questions(rec, profile.for_prompt(p), profile.apply_facts(p), questions)

    def easy_apply(key: str, data: dict) -> dict:
        """Everything for one application in one go: Claude's assessment, a tailored résumé, a cover letter and
        answers to the questions the form will likely ask, all from the same résumé. Saves the job to the tracker."""
        rec = ledger.get(key)
        if rec is None:
            raise KeyError(key)
        p = current_profile()
        if not p["resumes"]:
            raise BadRequest("Add a résumé on your Profile first: the application is built from it.")
        names = {r["name"] for r in p["resumes"]}
        fp = profile.fingerprint(p)
        name = str(data.get("resume") or "")
        if name and name not in names:
            raise BadRequest("No résumé by that name.")
        errors = {}
        if not name and len(names) > 1 and not jobs.ai_current(rec, fp):
            try:  # the assessment picks the résumé, so the letter and the résumé agree
                analyze(key)
            except ai.AIError as e:
                errors["analysis"] = str(e)
        best = ((ledger.get(key).get("ai") or {}).get("best_resume") or "") if not name else name
        name = best if best in names else (next(iter(names)) if len(names) == 1 else "")
        parts = {"tailored": lambda: tailor(key, {"resume": name}),
                 "letter": lambda: write_letter(key, {"resume": name, "notes": data.get("notes") or ""}),
                 "answers": lambda: ledger.set_doc(key, "answers", {"items": answers(key)})}
        if not jobs.ai_current(ledger.get(key), fp) and "analysis" not in errors:
            parts["analysis"] = lambda: analyze(key)

        def run(part, fn):
            try:
                fn()
            except (ai.AIError, BadRequest) as e:
                errors[part] = str(e)

        threads = [threading.Thread(target=run, args=item) for item in parts.items()]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        if all(k in errors for k in ("tailored", "letter", "answers")):
            raise ai.AIError(errors["tailored"])
        rec = ledger.get(key)
        if rec.get("status") in ("", "dismissed"):
            ledger.update(key, {"status": "saved"})
        rec = ledger.set_doc(key, "packet", {"resume": name})
        return {"job": ledger.public(rec), "mark": ledger.mark(rec), "errors": errors}

    def autofill(url: str) -> dict:
        """What the extension fills an application form with: the person's details, plus the job's letter and
        answers when the form belongs to a job it knows."""
        p = current_profile()
        a = dict(p.get("apply") or {})
        if p["name"] and not (a.get("first_name") or a.get("last_name")):
            first, _, last = p["name"].partition(" ")
            a.setdefault("first_name", first)
            if last:
                a.setdefault("last_name", last)
        rec = ledger.for_page(url)
        out = {"fields": a, "job": None}
        if rec:
            out["job"] = {"key": rec["key"], "title": rec.get("title") or "", "company": rec.get("company") or ""}
            out["letter"] = (rec.get("cover_letter") or {}).get("text") or ""
            out["answers"] = [x for x in (rec.get("answers") or {}).get("items") or [] if x.get("answer")]
            out["has_resume"] = bool((rec.get("tailored") or {}).get("text"))
        return out

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

        def _file(self, body: bytes, ctype: str, name: str):
            from urllib.parse import quote

            self._send(body, ctype, extra={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})

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
            except Exception as e:  # a bug shouldn't drop the connection without a word
                import traceback

                traceback.print_exc()
                self._error(f"Something went wrong in Job Scanner: {type(e).__name__}: {e}", HTTPStatus.INTERNAL_SERVER_ERROR)

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
                    return self._json({"job": ledger.public(rec), "mark": ledger.mark(rec)})
                if path == "/api/capture/export":  # a file for the extension to attach to an application form
                    rec = ledger.get(q.get("key", ""))
                    if rec is None:
                        raise KeyError(q.get("key"))
                    return self._file(*export_doc(rec, q.get("doc", "resume"), q.get("format", "pdf")))
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
                idx = ledger.index()
                return self._json({"jobs": [ledger.public(r, idx) for r in recs[:limit]], "total": len(recs)})
            if path == "/api/jobs.csv":
                return self._send(ledger.csv().encode("utf-8"), "text/csv; charset=utf-8",
                                  extra={"Content-Disposition": 'attachment; filename="jobs.csv"'})
            if path == "/api/todo":
                tracked = ledger.listing({"status": "tracked"})
                return self._json({"todo": advice.todo(tracked)})
            if path.startswith("/api/jobs/") and path.endswith("/export"):
                key = path[len("/api/jobs/"):-len("/export")]
                rec = ledger.get(key)
                if rec is None:
                    raise KeyError(key)
                return self._file(*export_doc(rec, q.get("doc", "letter"), q.get("format", "pdf")))
            if path == "/api/insights":
                recs = list(ledger.jobs.values())
                p = current_profile()
                return self._json({"accuracy": insights.accuracy(recs), "skills": insights.skill_gaps(recs, p),
                                   "pay": insights.pay_report(recs, p), "plan": store.read_json("insights.json", {}).get("plan"),
                                   "week": insights.weekly(recs, datetime.now(timezone.utc))})
            if path.startswith("/api/jobs/"):
                rec = ledger.get(path[len("/api/jobs/"):])
                if rec is None:
                    raise KeyError(path)
                return self._json({"job": ledger.public(rec), "todo": advice.nudges(rec),
                                   "pay": insights.pay_position(rec, list(ledger.jobs.values())),
                                   "ai_current": jobs.ai_current(rec, profile.fingerprint(current_profile()))})
            if path == "/api/places":
                return self._json({"places": places.search(q.get("q", ""))})
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
                if path == "/api/capture/cover-letter":
                    rec = write_letter(f"{data.get('source', '')}:{data.get('id', '')}", data)
                    return self._json({"letter": rec["cover_letter"]["text"]})
                if path == "/api/capture/easy-apply":
                    return self._json(easy_apply(f"{data.get('source', '')}:{data.get('id', '')}", data))
                if path == "/api/capture/autofill":
                    return self._json(autofill(str(data.get("url") or "")))
                if path == "/api/capture/answers":
                    qs = data.get("questions")
                    if not isinstance(qs, list) or not qs:
                        raise BadRequest("No questions.")
                    return self._json({"answers": answers(str(data.get("key") or ""), qs)})
                if path == "/api/capture/status":
                    key = f"{data.get('source', '')}:{data.get('id', '')}"
                    rec = ledger.update(key, {"status": data.get("status", "")})
                    return self._json({"mark": ledger.mark(rec)})
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
                text = str(data.get("resume") or profile.all_resume_text(current_profile()))
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
            if path == "/api/insights/plan":
                p = current_profile()
                gaps = insights.skill_gaps(list(ledger.jobs.values()), p)
                if not gaps["gaps"] and not gaps["missing_keywords"]:
                    raise BadRequest("No gaps to plan for yet: have Claude read a few jobs you'd consider first.")
                plan = {**ai.gap_plan(gaps, profile.for_prompt(p)), "at": jobs.now_iso(), "jobs": gaps["jobs"]}
                saved = store.read_json("insights.json", {})
                saved["plan"] = plan
                store.write_json("insights.json", saved)
                return self._json({"plan": plan})
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
                    return self._json({"job": ledger.public(write_letter(key, data))})
                if action == "tailor":
                    return self._json({"job": ledger.public(tailor(key, data))})
                if action == "easy-apply":
                    return self._json(easy_apply(key, data))
                if action == "answers":
                    return self._json({"job": ledger.public(ledger.set_doc(key, "answers", {"items": answers(key)}))})
                if action == "message":
                    rec = ledger.get(key)
                    if rec is None:
                        raise KeyError(key)
                    kind = str(data.get("kind") or "")
                    if kind not in ai.MESSAGE_KINDS:
                        raise BadRequest("Unknown kind of message.")
                    msg = ai.draft_message(rec, profile.for_prompt(current_profile()), kind, rec.get("notes") or "")
                    return self._json({"job": ledger.public(ledger.set_doc(key, f"draft_{kind}", msg)), "message": msg})
                if action == "update":
                    return self._json({"job": ledger.public(ledger.update(key, data))})
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
