# Setup guide

This takes about 20 minutes. You need a GitHub account, your CV as a Word file (`.docx`), and a Claude Pro or Max subscription. (Or, instead of a subscription, a Claude API key paid by usage.)

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

## 5. Get your keys

**Claude (required).** The bot uses Claude Code with your Claude subscription, so there's no separate bill.
1. Install [Node.js](https://nodejs.org) on your computer if you don't have it.
2. In a terminal, run `npx @anthropic-ai/claude-code setup-token`. A browser opens: sign in with your Claude account.
3. Copy the token it prints (it starts with `sk-ant-oat`) and save it as the secret `CLAUDE_CODE_OAUTH_TOKEN`.

Prefer to pay per use instead? Set `matching.provider: anthropic`, use full model ids (e.g. `claude-haiku-5-5`, `claude-sonnet-5-5`), and add the secret `ANTHROPIC_API_KEY` from [console.anthropic.com](https://console.anthropic.com).

**Job search (optional, free).**

| Key | Needed? | Where |
|---|---|---|
| `ADZUNA_APP_ID`, `ADZUNA_APP_KEY` | Optional, paid | [developer.adzuna.com](https://developer.adzuna.com) → Register (choose "Personal job search"). New keys get 25 trial calls; regular use needs the API Access plan (about £8 a month). The daily run uses about 10 calls |
| `REED_API_KEY` | Recommended, free | [reed.co.uk/developers/jobseeker](https://www.reed.co.uk/developers/jobseeker) |

Add each one in your repo under **Settings → Secrets and variables → Actions → New repository secret**, using exactly the names above.

**LinkedIn (no key needed for the public search).** The bot searches LinkedIn's public job pages without logging in, so your account is never used. For extra coverage it can also read your LinkedIn job-alert emails:
1. On LinkedIn, search for a role and location, set **Date posted**, and turn on **Set alert** (daily, by email). Do this for each role you want.
2. Turn on 2-Step Verification for your Google account, then create an app password at [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) (name it "job bot").
3. Add the secrets `GMAIL_ADDRESS` (your Gmail address) and `GMAIL_APP_PASSWORD` (the 16-letter app password). The bot only reads emails from LinkedIn job alerts, read-only.

## 6. Run it

1. Go to the **Actions** tab. If asked, click **I understand my workflows, go ahead and enable them**.
2. Click **Daily job run → Run workflow**. Choose `find` first to check the search without using Claude, then `run` for the full pipeline.
3. When the run finishes, open it and download **results** at the bottom, or look in the `data/` folder of your repo:
   - `data/tracker.csv`: open it in Excel, or see it in your Google Sheet (step 9)
   - `data/scores.csv`: every job Claude scored, with the reason
   - `data/applications/…/report.md`: what was changed for each job, and why
   - `data/applications/…/*_cv.pdf`: the tailored CV

Tick **Small test run** the first time: it scores about 15 jobs and finishes in minutes. From then on it runs every day at 06:00 UTC. If you use the laptop helper, move it earlier (e.g. `0 3 * * *`) so it finishes before the helper starts at 9am. To change the time, edit the `cron` line in `.github/workflows/daily.yml`.

## 7. Laptop helper (Mac): LinkedIn Easy Apply and company career sites

Applications are submitted from your own laptop, in a browser signed in as you. Cloud servers get blocked by LinkedIn and by the "are you a robot?" checks on many career sites; your own laptop doesn't.

- **Company career sites** (Greenhouse, Lever, Ashby, Workable) are applied to automatically, without asking.
- **LinkedIn jobs that apply on a company site**: the helper opens the job while you're signed in to find the real apply link. If it's one of the sites above, it applies there; otherwise the job is marked "Apply on company site" with the link.
- **LinkedIn Easy Apply** jobs wait for your one-click approval of the day's batch.

1. You need Python 3.10+ ([3.12 recommended](https://www.python.org/downloads/macos/)), git (`xcode-select --install`) and Google Chrome. Clone your private repo in Terminal: `git clone https://github.com/<you>/<your-private-repo>.git ~/Documents/<your-private-repo>`.
2. In Terminal, go to the repo folder (`cd ~/Documents/<your-private-repo>`) and run:
   ```bash
   bash helper/install_mac.sh
   ```
   It installs what it needs, installs Claude Code and asks you to sign in to your Claude account once (it answers form questions from your CV), then opens a browser window: sign in to LinkedIn there once.
3. Try a safe test, which fills in the forms but never presses Submit and doesn't change your tracker:
   ```bash
   ~/.job-applier/venv/bin/python -m jobapplier.helper --test
   ```
4. From then on it starts by itself when you log in and at 9am (the laptop must be on and logged in). Career-site applications start straight away; at the same time a page opens listing the day's Easy Apply jobs. Untick any you don't want and press **Approve and apply**.

How questions are answered:
- From your settings first (right to work, sponsorship, notice period, salary, and optional `gender`, `ethnicity`, `religion`, `nationality` under `answers`).
- Then by Claude, from your CV only. Answers to general questions are remembered in `~/.job-applier/learned_answers.json`, which you can edit.
- Questions about visa type or expiry get a true, non-committal answer; a yes/no "is your right to work time-limited?" is left for you.
- Anything it can't answer truthfully: it stops, plays a sound and shows a pop-up, leaves that tab open and marks the job "Needs you".

Useful options: `--ask "words"` always stops at questions containing those words; `--ping` shows a test pop-up; `apply.always_ask: ["words", ...]` in settings does the same as `--ask` every day.

## 8. Morning email

After each daily run you get an email with: how many jobs were scanned, matched your filters, were scored and were suited; the LinkedIn Easy Apply jobs waiting for approval (fit, salary, missing keywords, links); what goes to company sites; what was applied to since yesterday; what needs you; why jobs were filtered out; and links to your tracker and the run.

It's sent with the `GMAIL_ADDRESS` / `GMAIL_APP_PASSWORD` secrets (step 5) to `digest.to` in settings (or your profile email). Turn it off with `digest.enabled: false`.

## 9. Google Sheet tracker

The tracker can be copied into a Google Sheet after every run and every laptop-helper session. Your own notes in the **My notes** column, and statuses you change to Interview, Offer or Rejected, are kept.

1. Create a blank Google Sheet. Open **Extensions → Apps Script**, delete the sample code and paste in everything from `helper/google_sheet.gs`.
2. Change `TOKEN` near the top to a long random password, and press **Save**.
3. Click **Deploy → New deployment**, choose the type **Web app**, set **Execute as: Me** and **Who has access: Anyone**, then **Deploy**. Allow the permissions it asks for (Google warns that the app isn't verified because you wrote it: click **Advanced → Go to … (unsafe)**). Copy the **Web app URL**.
4. In your private repo add two secrets: `SHEET_WEBHOOK_URL` (the web app URL) and `SHEET_TOKEN` (the same password). Put the sheet's own link in settings as `sheet.url` so the morning email links to it.
5. Run **Actions → Update Google Sheet → Run workflow** to fill it now.

## Running it on your laptop instead

1. Install [Python 3.11+](https://www.python.org/downloads/), [LibreOffice](https://www.libreoffice.org/download/) (used to make PDFs and count pages) and Claude Code (`npm install -g @anthropic-ai/claude-code`, then run `claude` once to sign in).
2. Then:

```bash
git clone <your private repo url> && cd <repo>
pip install -r requirements.txt
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
