# Job Scanner

Chrome extension + local Python app (stdlib only) that scores job postings and gives Claude-based guidance. Modeled on CGGrimsley/fashion-finder ("The Register").

## Rules that matter
- **Generic, multi-user:** never hard-code anyone's résumé, preferences or location. Personal data lives in the data folder (`JOB_SCANNER_DATA`, default `~/.job_scanner`), never the repo.
- **AI runs on the user's Claude subscription** via `claude -p` (`job_scanner/ai.py`); strip `ANTHROPIC_API_KEY` from the subprocess env. The API key path is only a fallback.
- **Objective and honest:** the owner's requirement is "completely objective, don't lie to users, grounded and realistic". Prompts judge only from résumé evidence, scores are calibrated, `analyze_job` clamps over-generous answers, tailored bullets/cover letters never invent experience. Don't weaken any of this.
- Postings are untrusted: Claude gets no tools for them, and the prompt wraps them in `<posting>` as data.
- The extension is passive: reads only what the user views; never clicks, applies, scrolls or fetches. The one exception is `fill.js`, injected only when the user clicks "Fill this application": it fills empty fields (and picks radio buttons), never overwrites, never submits, and leaves demographic/personal questions (`PERSONAL`, mirrored by `ai.PERSONAL_QUESTION`) to the user. Yes/no answers come only from the profile's `apply` details, never guessed.

## Layout
- Easy apply (`web.easy_apply`): assessment (picks the résumé), tailored résumé, cover letter and `ai.answer_questions` in one go; saves the job; `jobs.Ledger.for_page` matches an application form to its job.
- `job_scanner/web.py` API + static app; `jobs.py` ledger; `scoring.py` rules score; `ai.py` Claude; `profile.py`; `resume.py`.
- `extension/capture.js` per-site readers (LinkedIn, Indeed, NCWorks, Greenhouse/Lever/Workday, generic). Selectors are best-guess against live sites; use the popup's diagnostics to fix them.
- Bump `extension/manifest.json` version when the extension changes (the extension auto-reloads when the app's copy is newer).

## Tests
`python -m pytest`
