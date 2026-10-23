# Job Scanner

Job Scanner reads the job postings you browse on LinkedIn, Indeed, NCWorks and company career pages. It tells you which ones are worth applying to, and how to apply. A Chrome extension does the reading, and a small app on your computer keeps your profile, scores every job and asks Claude for an honest assessment, **using your own Claude subscription**.

- **Fit stamps on every card** as you scroll a search: *Apply 78*, *Consider 55*, *Skip 24*.
- **A panel in the corner** for the posting you have open, with Claude's assessment, realistic odds, strengths, gaps, red flags and résumé tips, plus buttons to save it or mark it applied.
- **Cover letters** for any job, from the panel or the app. Choose which résumé to base one on (Claude picks the best match by default) and a tone, then copy or download it.
- **Easy apply.** One click (in the app or the panel) gets Claude's assessment, a tailored résumé, a cover letter and answers to the questions the application will likely ask, all from the same résumé, and saves the job to your tracker. Anything your résumés don't show is left blank for you, not guessed.
- **Fill this application.** On an application form, click the extension's icon, then **Fill this application**. It fills your details from the Profile's *Application details*, attaches your tailored résumé and cover letter where the form asks for files, and offers to have Claude draft answers to the form's own questions. It never submits and never overwrites what you've typed, and it always leaves questions about gender, race, veterans, disability and the like to you.
- **Tailored résumés.** For any job, Claude reorders and rewords one of your résumés in the posting's terms, using only what your résumés already show. It lists what it changed and what it left out, and flags any number that isn't in your résumés.
- **PDF and Word downloads** for tailored résumés and cover letters.
- **Tracker to-dos.** From the dates you record, the tracker tells you when to apply, reach out to someone at the company, follow up (after a week, again after two), prepare for an interview, send a thank-you, and answer an offer. Claude drafts each message for you to edit.
- **Several résumés.** Claude reads them all as evidence of what you've done, and it tells you which one to send for each job.
- **Discover.** Search links tuned to surface the postings worth seeing (newest first, posted in the last day or week, your remote/hybrid/on-site choice, your avoid-list words left out) on LinkedIn, Indeed, USAJobs and Google Jobs, for your target roles and for roles Claude says your résumés already fit but you aren't searching for. They open in your browser; the app never searches job sites itself.
- **Learns from what you pass on.** When you keep passing on the same employer, title word, level, on-site jobs or staffing agencies, Discover suggests lowering their scores. Nothing changes until you approve it, every lowered score says why, and you can undo it.
- **Interview prep** for any job: likely questions, what in your résumé answers each one (or that nothing does), and questions to ask them.
- **Résumé check** on Insights: what application systems trip on (missing headings, dates, contact details, length) and the keywords your target jobs keep asking for that your résumés never mention.
- **Home** shows your next setup step, what needs you today and the best new matches. A short guide walks new users through setup (Skip for now, or Don't show this again; it's on Setup if you want it back), and everything it asks for can be changed later.
- **The app** (http://127.0.0.1:8766) lists every job you've seen, best fit first. It also has an application tracker (saved, applied, interviewing, offer), cover letters, and a CSV export.

It's passive. It only reads pages you open, as you scroll, and never clicks, applies or fetches anything by itself. Filling a form happens only when you click Fill this application, and you always submit it yourself. LinkedIn and Indeed forbid automated scraping in their terms, so on those sites it works the way you browse and nothing more. The app can also check some sources by itself, but only ones that publish their jobs for programs to read (see Watching).

## Honest by design

The guidance is meant to be objective, not encouraging:

- Claude judges you only on what your résumé and About Me actually show. A requirement your résumé doesn't show counts as unmet.
- Scores are calibrated the way a recruiter would screen applicants: most postings land between 30 and 70, and 80+ is rare. Thin information lowers the score and the stated confidence. It never raises them.
- The app holds Claude to its own rubric. The overall score can't run more than 10 points past how well you meet the requirements. A low-confidence read can't say *Apply*, and a dealbreaker gap always reads *Skip*.
- Tailored résumé bullets and cover letters only reword experience you really have. Nothing is invented, and a requirement you don't meet is left out of a letter rather than papered over.
- The quick score on search cards is labelled for what it is: a match to your stated preferences, not a judgement of your chances. A card on its own never scores above 75.

## Install

You need Python 3.9+, Chrome, and (for the AI guidance) a Claude Pro or Max subscription.

**Windows, the quick way:** download the code, then double-click `Install Job Scanner.bat`. It installs Python and Node.js if they're missing (via winget), installs Claude Code, sets the app to start when you sign in, puts a shortcut on the desktop and opens the app. Then run `claude` once to sign in, and do step 5 below.

1. **Get the code:** clone this repo, or download it as a ZIP and unzip it.
2. **Start the app:** double-click `start.bat` (Windows) or run `./start.sh` (Mac/Linux). You can also run `python -m job_scanner serve --open`. The app opens at http://127.0.0.1:8766.
3. **Fill in your Profile, résumé first.** Upload or paste your résumé (PDF, Word or text). If you keep several targeted versions, add them all. Claude suggests job titles and skills from them, and you can edit those and add your own. Then pick your locations: start typing a city or state and choose it from the list. Finish with your minimum pay, your dealbreakers and your About Me (**Draft it from my résumés** writes a first version from your résumés alone, for you to edit, and lists what only you can add). The more Claude knows, the better its advice.
4. **Set up Claude on your subscription:**
   - Install Claude Code: `npm install -g @anthropic-ai/claude-code` (or the installer from claude.com/claude-code). It needs Node.js 22 or newer: check with `node -v`, and on Windows update with `winget install OpenJS.NodeJS.LTS`.
   - Run `claude` once in a terminal and sign in with your Claude account. If PowerShell says *running scripts is disabled*, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` first (or type `claude.cmd`).
   - Restart Job Scanner. Run `python -m job_scanner doctor` to check: it should say *Claude: Your Claude subscription (Claude Code)* and *Test call: OK*.
5. **Add the extension:** open `chrome://extensions`, turn on **Developer mode**, click **Load unpacked** and choose the `extension` folder. Then click **Connect the extension** on the app's **Setup** page (or paste the pairing token from Setup into the extension's **Settings** and click **Save & test**).

Then browse jobs as usual.

**Start with Windows:** tick *Start Job Scanner when I sign in to Windows* on the Setup page (or run `python -m job_scanner startup on`). It puts a small script in your Startup folder that runs the app with no window.

## Home server (Docker)

Run Job Scanner on a homelab box and use it from any computer on your network. The extension stays on each computer's Chrome and sends what you browse to the server; Claude runs on the server, on your subscription.

1. **Make a Claude token.** On any computer where Claude Code is signed in to your Claude account, run `claude setup-token` and copy the token it prints (it lasts a year).
2. **Configure.** On the server, clone this repo, `cp .env.example .env`, and set:
   - `CLAUDE_CODE_OAUTH_TOKEN=` the token from step 1
   - `JOB_SCANNER_PASSWORD=` a password for the app (required: the app refuses to listen on the network without one)
   - `JOB_SCANNER_ALLOWED_HOSTS=` any host names you'll use besides the IP, e.g. `homelab.lan,jobs.example.com`
3. **Start it:** `docker compose up -d --build`. Check it with `docker compose logs -f` and `docker compose exec job-scanner python3 -m job_scanner doctor` (it should say *Test call: OK*).
4. **Open** `http://<server-ip>:8766`, sign in with the password, and fill in your Profile.
5. **Connect the extension** on each computer: load the `extension` folder (step 5 above), open its **Settings**, set the app address to `http://<server-ip>:8766`, allow the permission Chrome asks for, paste the pairing token from the app's **Setup** page and click **Save & test**. (One-click connecting only works when the app runs on the same computer as Chrome.)

Your data lives in the `job-scanner-data` Docker volume (`/data` in the container), with the same nightly backups; Watching checks your sources every 4 hours (change it on the Watching page) as long as the container runs. To update: `git pull && docker compose up -d --build`.

**Behind a reverse proxy** (Caddy, Traefik, Nginx Proxy Manager): add the proxy's host name to `JOB_SCANNER_ALLOWED_HOSTS`, and make sure the proxy passes the original `Host` header (Caddy and Traefik do; with plain nginx add `proxy_set_header Host $host;` and `proxy_set_header X-Forwarded-Proto $scheme;`). Over HTTPS the sign-in cookie is marked Secure. Keep it on your LAN or behind a VPN such as Tailscale rather than open to the internet: it holds your résumé and runs Claude on your plan.

## How Claude is used, and how much

Job Scanner runs Claude Code on your computer (`claude -p`). On Windows it starts the real `claude.exe` behind npm's `claude.cmd`, so it works whether you installed with npm or the installer. Its work counts against your Claude plan's usage, not a separate bill. Your `ANTHROPIC_API_KEY`, if you have one, is removed from those calls so a pay-as-you-go key is never used by accident.

- When you **open a posting**, Claude reads it automatically, but only if the quick score is at least 40 (adjustable).
- There's a **daily cap** on automatic calls (60 by default). Set both on the Setup page.
- **Ask Claude** in the panel or the app always works on demand.
- Each posting is read once. It's read again only if the posting or your profile changes.
- **Each employer is read once**, with the quick model: what Claude knows about the company in general (it can't browse, so this may be out of date, and it says so when it doesn't recognise an employer rather than guessing). The read is reused for every posting from that company for six months and is shown on the job page.
- **Your posting goes first.** Anything you ask for runs before automatic reads, and among automatic reads the posting you're looking at now goes first. Closing a tab drops its reads that haven't started.
- **Failures:** a passing glitch (overloaded, a dropped connection) is retried once. If you hit your plan's usage limit, the app says when it resets and pauses automatic reads until then.
- **Models:** on Setup, pick the model for the main work (default: whatever your Claude Code uses) and for quick jobs (default Haiku), and whether automatic reads use the quick one to save your plan.

Job postings are untrusted text from the web. Claude runs with no tools, in an empty temporary folder, and is told to treat the posting as data. A posting can't make it do anything except answer the question.

No subscription? Install the `anthropic` package (`pip install anthropic`) and set `ANTHROPIC_API_KEY` in `.env` to use the API instead.

## Sites

| Site | Search cards | Open posting |
|---|---|---|
| LinkedIn | ✓ | ✓ (search pane and `/jobs/view/`) |
| Indeed | ✓ | ✓ (right pane and `viewjob`) |
| NCWorks | ✓ | ✓ |
| Greenhouse, Lever, Workday career pages | | ✓ |
| Any other site | | **Scan this page** in the extension's popup. Select the description first if the page is unusual. |

The tag in the bottom-right corner shows what's happening as you scroll: jobs read on this page and how many are Apply or Consider; its dot pulses while new cards are being read. Once a day the extension also reminds you when tracked jobs have a to-do due (follow up, say thank you), and the Insights page has a week in review.

Sites change their pages often. When the extension finds job cards or a posting it can't read, the panel and the toolbar icon say so (an amber **!**), and the Jobs and Setup pages list which site is affected. The icon shows **off** when it can't reach the app. To get it fixed, open a search or posting, click the extension, then **Copy diagnostics**, and paste the result into an issue. It contains public page data only. `tests/extension/` runs the readers against saved pages in `tests/fixtures/` (needs Node and Playwright).

On the Jobs page you can also filter by remote/hybrid/on-site, listed pay, years of experience asked, degree and security clearance, which are read from each posting.

## Watching (automatic sources)

The **Watching** page sets up sources the app checks by itself, every few hours while it's running. Jobs worth a
look are added to your Jobs list like the ones you browse. These are jobs with a quick score of 45 or more (adjustable)
in one of your places, or remote if you take remote work. Strong matches get a desktop notification, and Claude reads
the best few from each check (score 70 or more, at most 5) within your daily limit.

- **Employers near you.** Claude lists the prominent employers around your Profile's places that hire for your roles,
  with each one's careers page and the job board it uses. The list comes from Claude's general knowledge, so it can be
  out of date. Every link and board is checked from your computer before it's offered. Employers whose boards publish
  a feed get a **Watch** button. A board found only by guessing the employer's name is marked so you can check it's
  really theirs. The rest are links to open in Chrome, and the extension reads them as you browse.
- **Company job boards.** Greenhouse, Lever, Ashby and SmartRecruiters publish each employer's jobs through public
  APIs. Paste a link to an employer's board to watch it.
- **Job alert emails, for LinkedIn and Indeed.** Set up alerts on those sites, and the app reads the alert emails from
  your mailbox over IMAP, **read-only** (nothing is marked read, moved or deleted). Gmail, Yahoo and iCloud need an
  app password. Outlook.com and Hotmail don't allow this kind of sign-in. The app itself never loads LinkedIn or
  Indeed.
- **USAJobs** and **Adzuna**, with free keys from their developer sites. Searches use your target roles and first
  place unless you set your own.

Sites that don't allow programs are left out even when a feed exists. governmentjobs.com, which many cities, counties
and states use, disallows every program but search engines in its robots.txt, so those employers stay as links.

## Your data

Everything stays on your computer in `~/.job_scanner` (change it with `JOB_SCANNER_DATA`). That folder holds `profile.json`, `jobs.json`, `settings.json`, `ai_usage.json`, `companies.json` (employer reads) `site_health.json`, `learned.json` (patterns you approved), `insights.json`, and `watch.json` / `watch_state.json` (what's watched and how each check went; API keys and the mail app password for Watching are kept there on your computer only, and are never sent back to the page). Each night the app copies them into `backups/YYYY-MM-DD/` there, keeping 14 days (`python -m job_scanner backup` does it now). Nothing personal is ever written into the repo.

## Credits

The place names in the location picker come from [GeoNames](https://www.geonames.org/) (CC BY 4.0), via the geonamescache package. They're bundled, so the picker works offline.

## Commands

```
python -m job_scanner serve [--port 8766] [--host 0.0.0.0] [--open]   # run the app (a host other than 127.0.0.1 needs JOB_SCANNER_PASSWORD)
python -m job_scanner doctor                         # check Claude and the data folder
python -m job_scanner token [--rotate]               # print (or replace) the extension pairing token
python -m job_scanner reset [--all] [-y]             # clear captured jobs (keeps tracked ones unless --all)
python -m job_scanner startup [on|off]               # start the app when you sign in to Windows
python -m job_scanner backup                         # copy your data into backups/ now
```

## Development

No runtime dependencies beyond the Python standard library.

```
pip install pytest
python -m pytest
```

The code is laid out as follows:

- `job_scanner/web.py`: the HTTP server and API.
- `jobs.py`: the job ledger.
- `scoring.py`: the quick rules score.
- `ai.py`: Claude, its prompts and the honesty rubric.
- `profile.py`: the profile.
- `resume.py`: résumé import.
- `advice.py`: the tracker's to-dos.
- `facts.py`: years, degree and clearance read from postings.
- `companies.py`: the one-per-employer read. `health.py`: whether each site is still readable. `startup.py`: Start with Windows.
- `pdf.py`, `docx.py`: PDF and Word export.
- `static/`: the web app.
- `extension/`: the Chrome extension. `capture.js` holds the per-site readers.
