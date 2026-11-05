# Job Applier Tracker

A job-search assistant you run from your own GitHub account. Every morning it finds new jobs that match your settings, tailors your CV to each one so it gets through applicant tracking systems (ATS), and keeps a tracker of everything it did. It **never invents experience**: it only rewords and reorders what is already on your CV.

You don't need to write any code to use it. You copy the template, edit one settings file, add your CV and a couple of API keys, and it runs on a schedule in GitHub Actions.

> **Status:** finding jobs, tailoring CVs and queueing applications all work. Automatic submission to company career sites, the LinkedIn Easy Apply laptop helper, and the daily email digest are next. See [Roadmap](#roadmap).

## What it does

```
 find ──► filter ──► analyse + tailor ──► one-page check ──► queue ──► track
```

1. **Find.** Searches company job boards directly (Greenhouse, Lever, Ashby), plus the Adzuna and Reed UK job APIs if you add free keys.
2. **Filter.** Keeps jobs that match your target titles, locations (or remote), recency (e.g. last 21 days) and salary floor, and skips companies you exclude. Duplicates across sources are merged. Your first location is ranked first.
3. **Screen and analyse.** A cheap Claude model scores every matching advert first, so only promising ones go further. Then a stronger model reads each one, pulls out its keywords, marks which ones are must-haves, checks each against your CV (already there, there in other words, or missing), and scores the fit from 0 to 100.
4. **Tailor.** Claude rewrites your summary, the most relevant bullets and your skills lines to use the advert's wording where it's true, and puts the most relevant bullets first. Your Word file is edited in place, so fonts and layout don't change.
5. **Truth check.** Every edit is checked against your original CV, plus any extra skills you list. An edit that mentions a tool or number you don't have is thrown away and logged.
6. **One page.** The CV is turned into a PDF and the pages counted. If it runs over, the least relevant items for that job are removed until it fits.
7. **Queue and track.** Good matches go into the apply queue with the tailored PDF and your screening answers. Everything is logged in `data/tracker.csv`, which opens in Excel or Google Sheets.

For each job you get a `report.md` showing the keywords, coverage before and after, every change (before and after), any gaps, and what was trimmed.

## Why it doesn't auto-click LinkedIn from the cloud

LinkedIn's User Agreement bans bots, and it restricts accounts that log in from cloud servers or apply in bulk. So LinkedIn Easy Apply jobs wait in a queue for your one-tap approval, and a small helper on your own laptop submits them in your normal browser (coming soon). Jobs on company career sites don't carry that account risk and can be submitted automatically.

## Quick start

Full step-by-step guide: **[docs/SETUP.md](docs/SETUP.md)**. In short:

1. Click **Use this template** → **Create a new repository** → choose **Private**. Your CV and job history will live there, so it must be private.
2. In your private copy, delete the last three lines of `.gitignore` (`settings.yaml`, `cv/`, `data/`).
3. Copy `settings.example.yaml` to `settings.yaml` and edit it. Add your CV as `cv/cv.docx`.
4. Add your API keys under **Settings → Secrets and variables → Actions**: `ANTHROPIC_API_KEY` (required), plus `ADZUNA_APP_ID`/`ADZUNA_APP_KEY` and `REED_API_KEY` (optional, free).
5. Go to **Actions → Daily job run → Run workflow**. After that it runs every morning.

## Running it on your own computer

```bash
pip install -r requirements.txt        # Python 3.11+, and LibreOffice for PDFs
cp settings.example.yaml settings.yaml # then edit it
export ANTHROPIC_API_KEY=...           # and optionally ADZUNA_APP_ID, ADZUNA_APP_KEY, REED_API_KEY

python -m jobapplier find              # list matching jobs, with ids
python -m jobapplier tailor --job <id> # tailor your CV for one of them and print the report
python -m jobapplier queue --job <id>  # add it to the apply queue
python -m jobapplier run               # all of the above for the day's best matches, up to your caps
```

You can also tailor for any advert you've copied into a file:

```bash
python -m jobapplier tailor --jd-file advert.txt --title "Data Engineer" --company "Acme"
```

## Where things are saved

| Path | What |
|---|---|
| `data/found.json` | Jobs from the latest search that passed your filters |
| `data/tracker.csv` | One row per job: dates, company, role, link, fit score, missing keywords, salary, status, CV file |
| `data/applications/<job>/` | `*_cv.docx`, `*_cv.pdf`, `report.md`, `analysis.json`, `job.json`, and `application.json` once queued |

Tracker statuses: Tailored → Awaiting approval (LinkedIn or manual) / Ready to auto-apply (company sites) → Applied → Interview / Offer / Rejected, or Skipped.

## Costs

- GitHub Actions: free for a daily run on a private repo (well within the free minutes).
- Adzuna and Reed: free API keys.
- Claude API: screening costs a fraction of a penny per job. Tailoring a job that passes is roughly 5p to 15p on the default model. You can change `matching.screen_model` and `matching.model` in settings.

## Privacy

- Your CV, settings and tracker stay in **your private repo**. The workflow refuses to do a full run in a public repo.
- API keys are stored as GitHub secrets and never written to files.
- Job adverts and your CV text are sent to the Claude API for analysis.

## Roadmap

- [x] Search company boards, Adzuna and Reed, with filters for title, location, recency and salary
- [x] Keyword analysis and truthful CV tailoring with a one-page limit
- [x] Apply queue and CSV tracker
- [ ] Automatic submission on Greenhouse, Lever, Ashby and Workable forms
- [ ] Laptop helper for LinkedIn Easy Apply (approve once, it submits)
- [ ] Daily email digest with one-click approval, and LinkedIn job-alert emails as a source
- [ ] Google Sheets tracker and Gmail reply tracking (interviews and rejections)

## Development

```bash
pip install -r requirements.txt pytest
python -m pytest
```

The code is in `jobapplier/`: `sources/` (one file per job board), `filters.py`, `cv.py` (Word editing and page fitting), `llm.py` (Claude prompt and output schema), `truth.py` (truthfulness guard), `tailor.py`, `tracker.py`, and `__main__.py` (the CLI).

## License

MIT
