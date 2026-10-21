# Job Scanner

Job Scanner reads the job postings you browse on LinkedIn, Indeed, NCWorks and company career pages. It tells you which ones are worth applying to, and how to apply. A Chrome extension does the reading, and a small app on your computer keeps your profile, scores every job and asks Claude for an honest assessment, **using your own Claude subscription**.

- **Fit stamps on every card** as you scroll a search: *Apply 78*, *Consider 55*, *Skip 24*.
- **A panel in the corner** for the posting you have open, with Claude's assessment, realistic odds, strengths, gaps, red flags and résumé tips, plus buttons to save it or mark it applied.
- **Cover letters** for any job, from the panel or the app. Choose which résumé to base one on (Claude picks the best match by default) and a tone, then copy or download it.
- **Tailored résumés.** For any job, Claude reorders and rewords one of your résumés in the posting's terms, using only what your résumés already show. It lists what it changed and what it left out, and flags any number that isn't in your résumés.
- **PDF and Word downloads** for tailored résumés and cover letters.
- **Tracker to-dos.** From the dates you record, the tracker tells you when to apply, reach out to someone at the company, follow up (after a week, again after two), prepare for an interview, send a thank-you, and answer an offer. Claude drafts each message for you to edit.
- **Several résumés.** Claude reads them all as evidence of what you've done, and it tells you which one to send for each job.
- **The app** (http://127.0.0.1:8766) lists every job you've seen, best fit first. It also has an application tracker (saved, applied, interviewing, offer), cover letters, and a CSV export.

It's passive. It only reads pages you open, as you scroll, and never clicks, applies or fetches anything by itself. LinkedIn and Indeed forbid automated scraping in their terms, so it works the way you browse and nothing more.

## Honest by design

The guidance is meant to be objective, not encouraging:

- Claude judges you only on what your résumé and About Me actually show. A requirement your résumé doesn't show counts as unmet.
- Scores are calibrated the way a recruiter would screen applicants: most postings land between 30 and 70, and 80+ is rare. Thin information lowers the score and the stated confidence. It never raises them.
- The app holds Claude to its own rubric. The overall score can't run more than 10 points past how well you meet the requirements. A low-confidence read can't say *Apply*, and a dealbreaker gap always reads *Skip*.
- Tailored résumé bullets and cover letters only reword experience you really have. Nothing is invented, and a requirement you don't meet is left out of a letter rather than papered over.
- The quick score on search cards is labelled for what it is: a match to your stated preferences, not a judgement of your chances. A card on its own never scores above 75.

## Install

You need Python 3.9+, Chrome, and (for the AI guidance) a Claude Pro or Max subscription.

1. **Get the code:** clone this repo, or download it as a ZIP and unzip it.
2. **Start the app:** double-click `start.bat` (Windows) or run `./start.sh` (Mac/Linux). You can also run `python -m job_scanner serve --open`. The app opens at http://127.0.0.1:8766.
3. **Fill in your Profile, résumé first.** Upload or paste your résumé (PDF, Word or text). If you keep several targeted versions, add them all. Claude suggests job titles and skills from them, and you can edit those and add your own. Then pick your locations: start typing a city or state and choose it from the list. Finish with your minimum pay, your dealbreakers and your About Me. The more Claude knows, the better its advice.
4. **Set up Claude on your subscription:**
   - Install Claude Code: `npm install -g @anthropic-ai/claude-code` (or the installer from claude.com/claude-code).
   - Run `claude` once in a terminal and sign in with your Claude account.
   - Restart Job Scanner. Run `python -m job_scanner doctor` to check: it should say *Claude: Your Claude subscription (Claude Code)* and *Test call: OK*.
5. **Add the extension:** open `chrome://extensions`, turn on **Developer mode**, click **Load unpacked** and choose the `extension` folder. Then open the extension's **Settings**, paste the pairing token from the app's **Setup** page, and click **Save & test**.

Then browse jobs as usual.

## How Claude is used, and how much

Job Scanner runs Claude Code on your computer (`claude -p`). On Windows it starts the real `claude.exe` behind npm's `claude.cmd`, so it works whether you installed with npm or the installer. Its work counts against your Claude plan's usage, not a separate bill. Your `ANTHROPIC_API_KEY`, if you have one, is removed from those calls so a pay-as-you-go key is never used by accident.

- When you **open a posting**, Claude reads it automatically, but only if the quick score is at least 40 (adjustable).
- There's a **daily cap** on automatic calls (60 by default). Set both on the Setup page.
- **Ask Claude** in the panel or the app always works on demand.
- Each posting is read once. It's read again only if the posting or your profile changes.

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

Sites change their pages often. If a site stops being read properly, open a search or posting, click the extension, then **Copy diagnostics for this page**, and paste the result into an issue. It contains public page data only.

## Your data

Everything stays on your computer in `~/.job_scanner` (change it with `JOB_SCANNER_DATA`). That folder holds `profile.json`, `jobs.json`, `settings.json` and `ai_usage.json`. Nothing personal is ever written into the repo.

## Credits

The place names in the location picker come from [GeoNames](https://www.geonames.org/) (CC BY 4.0), via the geonamescache package. They're bundled, so the picker works offline.

## Commands

```
python -m job_scanner serve [--port 8766] [--open]   # run the app
python -m job_scanner doctor                         # check Claude and the data folder
python -m job_scanner token [--rotate]               # print (or replace) the extension pairing token
python -m job_scanner reset [--all] [-y]             # clear captured jobs (keeps tracked ones unless --all)
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
- `pdf.py`, `docx.py`: PDF and Word export.
- `static/`: the web app.
- `extension/`: the Chrome extension. `capture.js` holds the per-site readers.
