# Betabox Grant Radar

Automatically finds grant funding opportunities relevant to Betabox every 2 weeks and displays them on a website. Each grant gets its own page with an AI summary, a "why it matters for Betabox" angle, contact info when available, and a link to the official grant page.

## How it works

```
scraper.py ──(Claude + web search)──> site/grants.json ──> site/index.html (static site)
     ▲
     └── GitHub Actions cron: 1st & 15th of each month
```

The scraper doesn't parse HTML from individual foundation sites (those break constantly). Instead it asks Claude, with the web search tool enabled, to find currently open grants for each of 7 search queries, and to return structured JSON: title, funder, amount, deadline, summary, Betabox angle, contacts, and the official URL. New grants are deduped against existing ones by URL and title similarity, stale grants (deadline >30 days past) are pruned, and the JSON is committed back to the repo.

The site is a single static HTML file that reads `grants.json`. No backend, no database, free to host.

## Grant classification

Every grant gets a `fit` tag:

- **direct** — Betabox, as a for-profit small business, can apply itself (ED/IES SBIR, NSF ITEST, NSF AISL)
- **partner** — schools/nonprofits apply and can spend the money on Betabox as their provider (most corporate foundations, NC state grants, 21st CCLC)
- **monitor** — market signals, like schools winning PLTW grants, useful for sales prospecting

## Setup (one time, ~10 minutes)

1. Create a GitHub repo and push this folder to it.
2. In the repo: **Settings → Secrets and variables → Actions → New repository secret**. Name it `ANTHROPIC_API_KEY`, paste your key.
3. **Settings → Pages → Source: GitHub Actions.**
4. Go to the **Actions** tab, select "Update grants", click **Run workflow** to do the first scrape and deploy.

Your site will be live at `https://<username>.github.io/<repo-name>/`.

## Run locally

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
python scraper.py            # updates site/grants.json
cd site && python -m http.server 8000   # view at localhost:8000
```

(You need a local server because the page fetches grants.json — opening index.html directly from the filesystem will hit a CORS block.)

## Tuning

- **Search queries**: edit `SEARCH_QUERIES` in `scraper.py`. Add queries for specific states as Betabox expands, or for specific funders you want monitored.
- **Schedule**: edit the cron in `.github/workflows/update-grants.yml`.
- **Cost**: ~7 search-enabled Claude calls per run, 2 runs/month — roughly a couple dollars a month at Sonnet pricing.

## Caveats

- Deadlines in the seed data marked "confirm" are best estimates from cycle patterns — verify on the funder's page before committing to one.
- Claude occasionally returns a grant whose deadline just passed; the pruner clears these within 30 days.
- Contact extraction only includes what's published on grant pages. Many funders only expose a contact form.
