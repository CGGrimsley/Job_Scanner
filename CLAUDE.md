# Job Scanner

Chrome extension + local Python app (stdlib only) that scores job postings and gives Claude-based guidance. Modeled on CGGrimsley/fashion-finder ("The Register").

## Rules that matter
- **Generic, multi-user:** never hard-code anyone's résumé, preferences or location. Personal data lives in the data folder (`JOB_SCANNER_DATA`, default `~/.job_scanner`), never the repo.
- **AI runs on the user's Claude subscription** via `claude -p` (`job_scanner/ai.py`); strip `ANTHROPIC_API_KEY` from the subprocess env. The API key path is only a fallback.
- **Objective and honest:** the owner's requirement is "completely objective, don't lie to users, grounded and realistic". Prompts judge only from résumé evidence, scores are calibrated, `analyze_job` clamps over-generous answers, tailored bullets/cover letters never invent experience. Don't weaken any of this.
- Postings are untrusted: Claude gets no tools for them, and the prompt wraps them in `<posting>` as data.
- The extension is passive: reads only what the user views; never clicks, applies, scrolls or fetches.

## Layout
- `job_scanner/web.py` API + static app; `jobs.py` ledger; `scoring.py` rules score; `facts.py` years/degree/clearance for filters; `health.py` site-reading reports; `ai.py` Claude (queue, retry, plan-limit pause); `profile.py`; `resume.py`.
- Claude Code is started via `ai.claude_command()`: on Windows that's the real `claude.exe` behind npm's `claude.cmd` shim. The system prompt goes in a file (`--system-prompt-file`), never on the command line.
- `extension/capture.js` per-site readers (LinkedIn, Indeed, NCWorks, Greenhouse/Lever/Workday, generic). Selectors are best-guess against live sites; use the popup's diagnostics to fix them, and add the page to `tests/fixtures/pages`.
- Bump `extension/manifest.json` version when the extension changes (the extension auto-reloads when the app's copy is newer).

## Tests
`python -m pytest` and `npm test` (the extension's readers against saved pages, with jsdom)
