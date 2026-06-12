"""
Betabox Grant Radar — scraper
Runs every 2 weeks (via GitHub Actions) to discover new grant opportunities,
summarize them with Claude, extract contact info, and update site/grants.json.

Usage:
    export ANTHROPIC_API_KEY=sk-ant-...
    python scraper.py

Approach: instead of brittle HTML scraping of dozens of foundation sites,
this uses Claude with the web_search tool to find and read grant pages,
then returns structured JSON. One model call per search query.
"""

import json
import os
import re
import sys
from datetime import date
from pathlib import Path

import anthropic

MODEL = "claude-sonnet-4-6"
GRANTS_PATH = Path(__file__).parent / "site" / "grants.json"

# Each query becomes one search-enabled Claude call. Tune these over time.
SEARCH_QUERIES = [
    "K-12 STEM education grants currently open applications {year}",
    "corporate foundation grants hands-on STEM learning K-12 {year}",
    "grants for field trips and experiential learning K-12 schools {year}",
    "North Carolina K-12 STEM education grant funding open {year}",
    "federal grants edtech small business SBIR education {year}",
    "afterschool and summer STEM program grants {year}",
    "STEM grants for school districts experiential learning providers {year}",
]

EXTRACTION_PROMPT = """You are a grant researcher for Betabox, a K-12 STEM education \
startup that provides hands-on STEM learning experiences (field trips, mobile labs, \
on-site programs) to children. Betabox is a for-profit company based in North Carolina.

Search the web for: "{query}"

Find grant opportunities that are CURRENTLY OPEN or opening soon, and that are relevant \
to Betabox in one of these ways:
- "direct": Betabox (a for-profit small business) can apply directly
- "partner": schools, districts, or nonprofits apply, and could spend the funds on \
Betabox as their program provider
- "monitor": not a funding source, but a market signal worth tracking

For each grant you find, extract every detail available, including any named people, \
program officers, emails, or phone numbers listed for contact.

Respond with ONLY a JSON array (no markdown fences, no preamble). Each element:
{{
  "title": "...",
  "funder": "...",
  "amount": "... (e.g. 'Up to $50,000')",
  "deadline": "YYYY-MM-DD (best estimate; use the cycle's next deadline)",
  "deadline_note": "... (cycles, exact times, caveats)",
  "category": "one of: Federal — R&D, Federal — via State, State — North Carolina, Corporate Foundation, Foundation — North Carolina, Nonprofit / Industry Partnership, Other",
  "fit": "direct | partner | monitor",
  "ai_summary": "3-5 sentence plain-language summary: what it funds, who applies, why it matters",
  "betabox_angle": "2-3 sentences on the specific play for Betabox",
  "contacts": [{{"name": "...", "role": "...", "info": "...", "email": "...", "phone": "..."}}],
  "url": "direct link to the grant's official page"
}}

Rules:
- Only include grants you actually found via search, with real URLs. Never invent.
- Only include contact names/emails/phones that actually appear on the pages. If none, \
use a single contact pointing to where contact info lives.
- Skip grants whose final deadline has clearly passed with no next cycle.
- Aim for 3-8 high-quality results."""


def slugify(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s[:60]


def load_existing() -> dict:
    if GRANTS_PATH.exists():
        return json.loads(GRANTS_PATH.read_text())
    return {"last_updated": "", "grants": []}


def normalize_url(url: str) -> str:
    return url.rstrip("/").replace("http://", "https://").lower()


def is_duplicate(grant: dict, existing: list[dict]) -> bool:
    g_url = normalize_url(grant.get("url", ""))
    g_title = grant.get("title", "").lower()
    for e in existing:
        if g_url and normalize_url(e.get("url", "")) == g_url:
            return True
        # crude title similarity: shared word ratio
        a, b = set(g_title.split()), set(e.get("title", "").lower().split())
        if a and b and len(a & b) / max(len(a), len(b)) > 0.7:
            return True
    return False


def parse_json_array(text: str) -> list[dict]:
    text = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        return []
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return []


def search_grants(client: anthropic.Anthropic, query: str) -> list[dict]:
    print(f"  searching: {query}")
    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=8000,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 6}],
            messages=[{"role": "user", "content": EXTRACTION_PROMPT.format(query=query)}],
        )
    except anthropic.APIError as e:
        print(f"  ! API error: {e}", file=sys.stderr)
        return []
    text = "".join(b.text for b in resp.content if b.type == "text")
    grants = parse_json_array(text)
    print(f"  -> {len(grants)} candidates")
    return grants


def validate(grant: dict) -> bool:
    required = ["title", "funder", "deadline", "url", "ai_summary", "fit"]
    if not all(grant.get(k) for k in required):
        return False
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", grant["deadline"]):
        return False
    if not grant["url"].startswith("http"):
        return False
    return True


def prune_stale(grants: list[dict], grace_days: int = 30) -> list[dict]:
    """Drop grants whose deadline passed more than `grace_days` ago."""
    today = date.today()
    kept = []
    for g in grants:
        try:
            d = date.fromisoformat(g["deadline"])
            if (today - d).days <= grace_days:
                kept.append(g)
            else:
                print(f"  pruning stale grant: {g['title']}")
        except ValueError:
            kept.append(g)
    return kept


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("Set ANTHROPIC_API_KEY before running.")

    client = anthropic.Anthropic(api_key=api_key)
    data = load_existing()
    existing = data["grants"]
    year = date.today().year

    print(f"Existing grants: {len(existing)}")
    new_grants = []
    for q in SEARCH_QUERIES:
        for g in search_grants(client, q.format(year=year)):
            if not validate(g):
                continue
            if is_duplicate(g, existing) or is_duplicate(g, new_grants):
                continue
            g["id"] = slugify(g["title"])
            g["found"] = date.today().isoformat()
            g.setdefault("contacts", [])
            g.setdefault("deadline_note", "")
            g.setdefault("betabox_angle", "")
            g.setdefault("category", "Other")
            new_grants.append(g)
            print(f"  + NEW: {g['title']}")

    data["grants"] = prune_stale(existing + new_grants)
    data["last_updated"] = date.today().isoformat()
    GRANTS_PATH.write_text(json.dumps(data, indent=2))
    print(f"\nDone. {len(new_grants)} new, {len(data['grants'])} total. Wrote {GRANTS_PATH}")


if __name__ == "__main__":
    main()
