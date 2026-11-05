# Setup guide

This takes about 20 minutes. You need a GitHub account, your CV as a Word file (`.docx`), and a credit card for the Claude API, which you pay for by usage.

## 1. Make your own private copy

1. On this repo's GitHub page, click **Use this template** → **Create a new repository**.
2. Give it a name (for example `job-applier-yourname`) and choose **Private**. This matters: your CV, salary answers and job history will be stored there, and GitHub shows run logs publicly on public repos.
3. Open your new repo. Everything below happens there.

## 2. Let your copy save your files

The template ignores personal files so nobody's data gets published by accident. In **your private copy**, open `.gitignore`, click the pencil icon, delete these three lines at the bottom, and commit:

```
settings.yaml
cv/
data/
```

## 3. Add your CV

1. Click **Add file → Upload files**.
2. Upload your CV and name it `cv/cv.docx` (create the `cv` folder by typing `cv/` before the file name).

Tips for a CV that tailors well:
- Write each bullet as its own paragraph starting with `•` (or use Word's bullet list).
- Use plain section headings in capitals, such as `PROFESSIONAL SUMMARY`, `PROFESSIONAL EXPERIENCE`, `EDUCATION`, `TECHNICAL SKILLS`.
- Write skills as `Label: item, item, item`, one line per group.
- Put job titles, companies and dates on their own line or in a small table above each job's bullets.

## 4. Fill in your settings

1. Open `settings.example.yaml`, copy all of it, then click **Add file → Create new file**, name it `settings.yaml` and paste.
2. Edit the values. The important ones:

| Setting | What it does |
|---|---|
| `search.roles` | Job titles to look for, highest priority first |
| `search.locations` | Places you'd work. The first one is ranked first. A job matches if its location contains one of these words |
| `search.remote_ok` | Also accept fully remote jobs in your country |
| `search.max_age_days` | Ignore jobs posted longer ago than this |
| `search.min_salary` | Skip jobs whose advertised maximum is below this. Jobs with no salary listed are kept |
| `search.exclude_companies` | Never apply here, e.g. your current employer |
| `search.companies` | Company job boards to check directly. Find a company's token in its careers link: `boards.greenhouse.io/<token>`, `jobs.lever.co/<token>`, `jobs.ashbyhq.com/<token>` |
| `matching.min_fit_score` | Only queue jobs that score at least this (0-100) |
| `extra_skills` | Skills you really have that aren't written on your CV. Tailoring may add these, and nothing else |
| `answers` | Your answers to common screening questions. Expected salary uses the middle of the advertised range when there is one |
| `apply` | Daily caps per channel |
| `max_pages` | Tailored CVs are trimmed to fit this many pages |

## 5. Get your API keys

| Key | Needed? | Where |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | [console.anthropic.com](https://console.anthropic.com) → API Keys. Add a little credit (e.g. £10 covers roughly 100 tailored CVs) |
| `ADZUNA_APP_ID`, `ADZUNA_APP_KEY` | Recommended, free | [developer.adzuna.com](https://developer.adzuna.com) → Register → your app's id and key |
| `REED_API_KEY` | Recommended, free | [reed.co.uk/developers/jobseeker](https://www.reed.co.uk/developers/jobseeker) |

Add each one in your repo under **Settings → Secrets and variables → Actions → New repository secret**, using exactly the names above.

## 6. Run it

1. Go to the **Actions** tab. If asked, click **I understand my workflows, go ahead and enable them**.
2. Click **Daily job run → Run workflow**. Choose `find` first to check the search without spending anything on Claude, then `run` for the full pipeline.
3. When the run finishes, open it and download **results** at the bottom, or look in the `data/` folder of your repo:
   - `data/tracker.csv`: open it in Excel or import it into Google Sheets
   - `data/applications/…/report.md`: what was changed for each job, and why
   - `data/applications/…/*_cv.pdf`: the tailored CV

From then on it runs every day at 06:00 UTC. To change the time, edit the `cron` line in `.github/workflows/daily.yml`.

## Running it on your laptop instead

1. Install [Python 3.11+](https://www.python.org/downloads/) and [LibreOffice](https://www.libreoffice.org/download/) (used to make PDFs and count pages).
2. Then:

```bash
git clone <your private repo url> && cd <repo>
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...   # Windows PowerShell: $env:ANTHROPIC_API_KEY="sk-ant-..."
python -m jobapplier find
python -m jobapplier tailor --job <id from the list>
python -m jobapplier queue --job <id>
```

## Troubleshooting

- **"settings.yaml not found"**: the file must be at the top of the repo, next to `README.md`.
- **A company board shows an error**: the token is wrong or the company moved provider. Open its careers page and check the link.
- **"Adzuna skipped" / "Reed skipped"**: the keys aren't set. The run still works with company boards only.
- **The tailored CV looks different from mine**: install the fonts your CV uses. On GitHub Actions, common fonts (Liberation, Carlito, Caladea, which match Arial, Calibri and Cambria) are installed automatically.
- **An edit was blocked by the truthfulness check**: the report says which tool or number it tried to add. If you really have that skill, add it to `extra_skills`.
