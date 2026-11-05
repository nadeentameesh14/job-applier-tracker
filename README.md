# Job Applier Tracker

A job-search assistant you run from your own GitHub account. Every morning it finds new jobs that match your settings, tailors your CV to each one so it gets through applicant tracking systems (ATS), and keeps a tracker of everything it did. It **never invents experience**: it only rewords and reorders what is already on your CV.

You don't need to write any code to use it. You copy the template, edit one settings file, add your CV and connect your Claude subscription, and it runs on a schedule in GitHub Actions.

> **Status:** everything below works: finding jobs (including your LinkedIn alert emails), truthful CV tailoring, the laptop helper for LinkedIn Easy Apply and company career sites (Mac), the morning email and the Google Sheet tracker. Reply tracking from Gmail is next. See [Roadmap](#roadmap).

## What it does

```
 find ──► filter ──► analyse + tailor ──► one-page check ──► queue ──► track
```

1. **Find.** Searches LinkedIn's public job listings (no login, so your account is never at risk) and your LinkedIn job-alert emails, company job boards directly (Greenhouse, Lever, Ashby), plus the Reed (free) and Adzuna (paid) UK job APIs if you add keys.
2. **Filter.** Keeps jobs that match your target titles, locations (or remote), recency (e.g. last 21 days) and salary floor, and skips companies you exclude. Duplicates across sources are merged. Your first location is ranked first.
3. **Screen and analyse.** A light Claude model scores every matching advert first, so only promising ones go further. Then a stronger model reads each one, pulls out its keywords, marks which ones are must-haves, checks each against your CV (already there, there in other words, or missing), and scores the fit from 0 to 100.
4. **Tailor.** Claude rewrites your summary, the most relevant bullets and your skills lines to use the advert's wording where it's true, and puts the most relevant bullets first. Your Word file is edited in place, so fonts and layout don't change.
5. **Truth check.** Every edit is checked against your original CV, plus any extra skills you list. An edit that mentions a tool or number you don't have is thrown away and logged.
6. **One page.** The CV is turned into a PDF and the pages counted. If it runs over, the least relevant items for that job are removed until it fits.
7. **Queue and track.** Good matches go into the apply queue with the tailored PDF and your screening answers. Everything is logged in `data/tracker.csv`, copied to your Google Sheet if you set one up.
8. **Apply.** A small helper on your Mac applies on company career sites (Greenhouse, Lever, Ashby, Workable) by itself, and submits LinkedIn Easy Apply jobs after you approve the day's batch with one click. It answers form questions from your settings and CV, and pings you when it can't answer truthfully.
9. **Report.** Each morning you get an email with the numbers (scanned, suited, queued, applied), the LinkedIn jobs waiting for you, what needs you, and a link to your tracker.

For each job you get a `report.md` showing the keywords, coverage before and after, every change (before and after), any gaps, and what was trimmed.

## Why applications are sent from your laptop

LinkedIn's User Agreement bans bots, and it restricts accounts that log in from cloud servers or apply in bulk. So LinkedIn Easy Apply jobs wait in a queue for your one-tap approval, and a small helper on your own laptop submits them in a normal browser window, signed in as you. Company career sites don't carry that account risk, so they're submitted without asking, also from the laptop because many of them block cloud servers with robot checks.

## Prerequisites

You need:

- **A GitHub account** (free). The bot runs in GitHub Actions in your own private copy.
- **A Claude Pro or Max subscription.** The bot uses it through Claude Code, so there is no extra API bill. To create the sign-in token once you also need [Node.js](https://nodejs.org) on any computer.
- **Your CV as a Word file** (`.docx`), ideally one page.
- **Optional, free:** a [Reed API key](https://www.reed.co.uk/developers/jobseeker) for more UK jobs.
- **Optional, for LinkedIn job-alert emails:** a Gmail address that receives your LinkedIn job alerts (directly or forwarded), with 2-Step Verification turned on and an [app password](https://myaccount.google.com/apppasswords).
- **For the laptop helper (applying):** a Mac (macOS 13 or newer) with Python 3.10+ (3.12 recommended, from [python.org](https://www.python.org/downloads/macos/)), git (`xcode-select --install`) and Google Chrome. The Mac must be on and logged in when the helper runs (by default at 9am, or whenever you log in).

You don't need a computer switched on for the daily search and tailoring; that runs in the cloud.

## Quick start

Full step-by-step guide: **[docs/SETUP.md](docs/SETUP.md)**. In short:

1. Click **Use this template** → **Create a new repository** → choose **Private**. Your CV and job history will live there, so it must be private.
2. In your private copy, delete the last three lines of `.gitignore` (`settings.yaml`, `cv/`, `data/`).
3. Copy `settings.example.yaml` to `settings.yaml` and edit it. Add your CV as `cv/cv.docx`.
4. Add secrets under **Settings → Secrets and variables → Actions**: `CLAUDE_CODE_OAUTH_TOKEN` (required; run `npx @anthropic-ai/claude-code setup-token` and sign in with your Claude account), plus `REED_API_KEY` (optional, free), `GMAIL_ADDRESS` and `GMAIL_APP_PASSWORD` (optional: reads LinkedIn alert emails and sends the morning email), `SHEET_WEBHOOK_URL` and `SHEET_TOKEN` (optional, Google Sheet tracker) and `ADZUNA_APP_ID`/`ADZUNA_APP_KEY` (optional; Adzuna gives 25 trial calls, then about £8 a month).
5. Go to **Actions → Daily job run → Run workflow** and tick **Small test run** first: it scores about 15 jobs and tailors a couple, so you can check the results in `data/scores.csv` within minutes. After that the full run happens every morning by itself.
6. For LinkedIn Easy Apply, set up the laptop helper on your Mac: see [docs/SETUP.md](docs/SETUP.md#7-laptop-helper-for-linkedin-easy-apply-mac), then try `python -m jobapplier.helper --test` (fills the forms but never presses Submit). It applies on company career sites by itself and on LinkedIn Easy Apply after your one-click approval.

## Running it on your own computer

```bash
pip install -r requirements.txt        # Python 3.11+, and LibreOffice for PDFs
npm install -g @anthropic-ai/claude-code && claude   # sign in once with your Claude account
cp settings.example.yaml settings.yaml # then edit it
export ADZUNA_APP_ID=... ADZUNA_APP_KEY=... REED_API_KEY=...   # optional

python -m jobapplier find              # list matching jobs, with ids
python -m jobapplier tailor --job <id> # tailor your CV for one of them and print the report
python -m jobapplier queue --job <id>  # add it to the apply queue
python -m jobapplier run               # all of the above for the day's best matches, up to your caps
python -m jobapplier run --test        # small trial: score about 15 jobs and tailor a couple
python -m jobapplier digest --preview  # write the morning email to data/digest_preview.html
python -m jobapplier sheet             # copy the tracker to your Google Sheet
```

You can also tailor for any advert you've copied into a file:

```bash
python -m jobapplier tailor --jd-file advert.txt --title "Data Engineer" --company "Acme"
```

## Where things are saved

| Path | What |
|---|---|
| `data/found.json` | Jobs from the latest search that passed your filters |
| `data/scores.csv` | Every job Claude screened, with its score and the reason, so you can check the scoring makes sense |
| `data/tracker.csv` | One row per job: dates, company, role, link, fit score, missing keywords, salary, status, CV file |
| `data/applications/<job>/` | `*_cv.docx`, `*_cv.pdf`, `report.md`, `analysis.json`, `job.json`, and `application.json` once queued |

Tracker statuses: Tailored → Awaiting approval (LinkedIn or manual) / Ready to auto-apply (company sites) → Applied → Interview / Offer / Rejected, or Skipped.

## Costs

- GitHub Actions: free for a daily run on a private repo (well within the free minutes).
- Reed: free API key. Adzuna: 25 free trial calls, then about £8 a month (optional; the run uses about 10 calls a day).
- Claude: by default it runs through Claude Code on your existing Claude Pro/Max subscription, so there's no extra bill (it counts toward your plan's usage limits). If you'd rather use the pay-per-use Claude API, set `matching.provider: anthropic` and add `ANTHROPIC_API_KEY`.

## Privacy

- Your CV, settings and tracker stay in **your private repo**. The workflow refuses to do a full run in a public repo.
- API keys are stored as GitHub secrets and never written to files.
- Job adverts and your CV text are sent to Claude for analysis.

## Roadmap

- [x] Search company boards, Adzuna and Reed, with filters for title, location, recency and salary
- [x] Keyword analysis and truthful CV tailoring with a one-page limit
- [x] Apply queue and CSV tracker
- [x] Automatic submission on Greenhouse, Lever, Ashby and Workable forms (laptop helper)
- [x] Laptop helper for LinkedIn Easy Apply (approve once, it submits) — Mac, see docs/SETUP.md
- [x] LinkedIn job-alert emails as a source (Gmail)
- [x] Daily email summary (scanned, suited, queued, applied, needs you)
- [x] Google Sheet tracker that keeps your own notes and statuses
- [ ] Gmail reply tracking (interviews and rejections)

## Development

```bash
pip install -r requirements.txt pytest
python -m pytest
```

The code is in `jobapplier/`: `sources/` (one file per job board), `filters.py`, `cv.py` (Word editing and page fitting), `llm.py` (Claude prompt and output schema), `truth.py` (truthfulness guard), `tailor.py`, `tracker.py`, `digest.py` (morning email), `sheet.py` (Google Sheet), `helper/` (laptop helper: `easyapply.py`, `careersite.py`, `answers.py`) and `__main__.py` (the CLI).

## License

MIT
