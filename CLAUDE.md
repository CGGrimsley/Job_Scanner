# Job Scanner

Chrome extension + local Python app (stdlib only) that scores job postings and gives Claude-based guidance. Modeled on CGGrimsley/fashion-finder ("The Register").

## Rules that matter
- **Generic, multi-user:** never hard-code anyone's résumé, preferences or location. Personal data lives in the data folder (`JOB_SCANNER_DATA`, default `~/.job_scanner`), never the repo.
- **AI runs on the user's Claude subscription** via `claude -p` (`job_scanner/ai.py`); strip `ANTHROPIC_API_KEY` from the subprocess env. The API key path is only a fallback.
- **Objective and honest:** the owner's requirement is "completely objective, don't lie to users, grounded and realistic". Prompts judge only from résumé evidence, scores are calibrated, `analyze_job` clamps over-generous answers, tailored bullets/cover letters never invent experience. Don't weaken any of this.
- Postings are untrusted: Claude gets no tools for them, and the prompt wraps them in `<posting>` as data.
- Automatic sources (`watch.py`) fetch only official, public feeds: the Greenhouse, Lever, Ashby and SmartRecruiters job-board APIs, USAJobs, Adzuna (`feeds.py`), and the user's own alert emails over read-only IMAP (`mail.py`). Never LinkedIn or Indeed pages, and never a site whose robots.txt disallows programs (governmentjobs.com does). `nearby.py` gets employer suggestions from Claude and checks every board and link before offering it; a board found by guessing a name is flagged `guessed`. Secrets in `watch.json` are masked by `watch.public`. Automatic Claude reads of watched jobs: score 70+, at most `web.READ_PER_RUN` per run.
- The extension is passive: reads only what the user views; never clicks, applies, scrolls or fetches. The one exception is `fill.js`, injected only when the user clicks "Fill this application": it fills empty fields (and picks radio buttons), never overwrites, never submits, and leaves demographic/personal questions (`PERSONAL`, mirrored by `ai.PERSONAL_QUESTION`) to the user. Yes/no answers come only from the profile's `apply` details, never guessed.

## Layout
- Easy apply (`web.easy_apply`): assessment (picks the résumé), tailored résumé, cover letter and `ai.answer_questions` in one go; saves the job; `jobs.Ledger.for_page` matches an application form to its job.
- `job_scanner/web.py` API + static app; `jobs.py` ledger; `scoring.py` rules score; `ai.py` Claude; `profile.py`; `resume.py`.
- `extension/capture.js` per-site readers (LinkedIn, Indeed, NCWorks, Greenhouse/Lever/Workday, generic). Selectors are best-guess against live sites; use the popup's diagnostics to fix them.
- Bump `extension/manifest.json` version when the extension changes (the extension auto-reloads when the app's copy is newer).

- Claude calls (`ai.ask_json`) go through `ai.gate`: asked-for calls first, automatic ones newest first, cancellable (`/api/capture/cancel`). Errors are classified (`ai.classify`: limit, auth, transient, timeout); transient ones are retried once, a plan limit pauses automatic reads (`ai.limited`). The system prompt goes in a file (`--system-prompt-file`) because of Windows' command-line limit.
- Models per task: settings `model_main`, `model_light` (default haiku; `LIGHT_KINDS`), `model_auto` (`ai.model_for`).
- `companies.py`: one light read per employer (`ai.company_read`), cached in `companies.json` for 180 days and passed to the analysis as context. Unknown employers are stored as unknown, never guessed.
- `facts.py`: years/degree/clearance from the posting, used for Jobs filters and a scoring caution. `health.py`: the extension reports readable/unreadable pages per site (`/api/capture/health`).

- LinkedIn's newer layout (`/jobs/search-results/`) has no stable classes: cards are list items whose markup names exactly one job id (`linkedinListCards`), the posting is the block under "About the job" (`newerItem`). Diagnostics include `structure` (tags, roles, attribute names and counts only) for fixing readers. `schedule()` never waits more than 1.5s, and scroll is listened for in the capture phase (inner scrolling lists).
- Reposts: `signals.relisted` (same site, new id, a week or more later; or `jobs.note_posted` seeing the posting date jump forward). The extension's daily reminder reads `/api/capture/due` (tracker to-dos marked now). `insights.weekly` is the Insights page's week in review.
- Discovery: `discover.py` builds search links only (the app never fetches job sites); `ai.adjacent_roles` (résumé evidence only) is kept in `insights.json` "roles". `learn.py` turns repeated passes into suggestions; only approved rules (`learned.json`) cost `PENALTY` points in `jobs.rescore`, with a caution saying why. `resume_check.py` is rule-based (no AI). `ai.interview_prep` marks questions the résumés don't answer (`from_resume` false).
- Streamlining: Home (`more.js` `showHome`), the setup strip, and the first-run `tour` (settings `tour_done`; Skip for now / Don't show this again). One-click pairing: `extension/pair.js` runs only on local app pages carrying meta `job-scanner-app`; background.js accepts a `pair` message only from that local server. Nightly `store.backup` (14 days). Windows: `Install Job Scanner.bat` → `scripts/install.ps1` (keep ASCII for PowerShell 5.1).

- Home server: `Dockerfile` + `compose.yaml` (Claude Code inside, `CLAUDE_CODE_OAUTH_TOKEN`, data in the `/data` volume). `web.serve` refuses a non-loopback host without `JOB_SCANNER_PASSWORD`; with one set, pages and the non-capture API need the `job_scanner_session` cookie from `/login` (`session_value`, signed with `store.session_secret`). `/api/capture*` stays token-only for the extension.

## Tests
`python -m pytest`
