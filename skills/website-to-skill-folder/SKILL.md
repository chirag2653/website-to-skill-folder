---
name: website-to-skill-folder
description: >
  Converts any website into an installable AI skill folder by crawling all pages
  and packaging them as searchable markdown with frontmatter summaries. Use when
  asked to: create a website search skill, index a website for AI agents, scrape
  a site into a searchable knowledge base, turn a website into an offline-searchable
  skill, make website content available to AI agents without live browsing, crawl
  a site, download a website for AI, convert website to markdown, build a knowledge
  base from a URL, or make a site searchable offline. Also use when the user provides
  a URL and wants it indexed, wants offline docs from a live site, or asks to
  "turn this website into a skill". Outputs an installable skill folder plus the
  exact npx command to add it to any AI agent.
---

# Website-to-Skill Pipeline

Runs `scripts/pipeline.py` to crawl a website and produce an installable skill folder.
The script handles everything — no need to read it.

## 1. Locate the Skill

```bash
SKILL_DIR="$HOME/.agents/skills/website-to-skill-folder"
[ -d "$SKILL_DIR" ] || SKILL_DIR=$(find "$HOME/.agents/skills" "$HOME/.claude/skills" \
  -maxdepth 2 -type d -name "website-to-skill-folder" 2>/dev/null | head -1)
echo "Skill dir: $SKILL_DIR"
```

## 2. Pre-flight Checks

Run these in order before the pipeline. Fix anything missing before proceeding — do not skip.

### Python (required: 3.8+)

```bash
python --version 2>&1 || python3 --version 2>&1
```

- If `python` is Python 2 or not found, use `python3` for all commands below.
- If neither is found: tell the user to install Python 3.8+ and stop.

### Python packages (one-time)

```bash
python -c "import requests, pydantic, tenacity; print('OK')" 2>&1
```

If `ModuleNotFoundError`: install and retry before proceeding.

```bash
pip install requests pydantic tenacity
```

### Firecrawl API key

```bash
python -c "import os; print('set' if os.environ.get('FIRECRAWL_API_KEY') else 'missing')"
```

If missing: **stop and ask the user for their Firecrawl API key AND the target website in one question.**

Tell them: "What website do you want to convert, and what's your Firecrawl API key? Get a free key at https://firecrawl.dev — no credit card required."

Once they provide both, use them in steps 3 and 4 below.

## 3. Show Cost Estimate and Get Approval

**How the pipeline handles URLs:** The pipeline extracts the domain from any URL the user gives.
A path like `/blog` or `/docs/api` is ignored — the **full domain** is always crawled.
Do NOT suggest filtering by URL path, grep the map file, or try to limit to a subdirectory.
If the user provides `https://example.com/blog`, treat it as crawling `example.com`.
(Subdomains like `blog.example.com` ARE different domains and are treated as such.)

**Before running the pipeline, tell the user the estimated cost and ask for confirmation.**

Cost formula: **1 credit (map) + ~5 credits per page scraped**.

- If the user specified a page limit (e.g., "20 pages"), use that number directly.
  Example: "This will crawl resend.com (up to 20 pages). Estimated cost: ~101 credits. Shall I proceed?"
- If no page limit was given, tell the user you'll discover pages first:
  "I'll map the site first to discover the page count (1 credit), then show you the cost before scraping."
  Then run with `--dry-run` to get the count, show the result, and ask before the real run.

Do NOT run `--dry-run` if the user already specified a page limit — just calculate and ask.

Only run the pipeline after the user approves.

## 4. Run the Pipeline

Inline both the skill path and the API key so the command is self-contained:

```bash
FIRECRAWL_API_KEY="fc-their_key_here" python "$HOME/.agents/skills/website-to-skill-folder/scripts/pipeline.py" https://example.com --yes
```

If the skill was installed to a different location (check Step 1 output), substitute that path:

```bash
FIRECRAWL_API_KEY="fc-their_key_here" python "$SKILL_DIR/scripts/pipeline.py" https://example.com --yes
```

**IMPORTANT:**
- Always include `--yes` when running from an AI agent. Without it, the pipeline
  prompts for interactive confirmation which will time out and cancel the run.
- Set a **10-minute timeout** on the Bash call. The pipeline can take several minutes
  for large sites (scraping + API polling). Example: `timeout: 600000` in tool params.

**Options:**

| Flag | Purpose |
|------|---------|
| `--description "..."` | One-line site description for the generated SKILL.md |
| `--output /path/to/dir` | Output directory (default: `./output/{skill_name}`) |
| `--max-pages 100` | Limit pages scraped — directly controls Firecrawl credit cost |
| `--yes` / `-y` | **Always use from agents.** Auto-approve cost prompt (skips interactive confirmation) |
| `--dry-run` | Map the site and show cost estimate, then exit without scraping (1 credit for map) |
| `--skip-scrape` | Reassemble from cache — zero API calls |
| `--force-refresh` | Ignore cache, re-scrape all pages |

## Troubleshooting & Recovery

**Pipeline crashed or timed out mid-scrape?**
Just rerun the same command. The pipeline saves progress after each batch to `_workspace/{domain}/state.json`. Completed batches are skipped automatically — you only pay for the remaining pages.

**Want to rebuild the skill folder without re-scraping?**
Use `--skip-scrape`. This reassembles from cached data with zero API calls — useful if you want to tweak `--description` or the template changed.

**Pages seem stale or site was redesigned?**
Use `--force-refresh` to ignore all cached data and re-scrape everything from scratch.

**Firecrawl rate limit errors (HTTP 429)?**
The pipeline retries automatically with exponential backoff (up to 5 attempts per request). If it still fails, wait a few minutes and rerun — cached batches won't be repeated.

**"API key missing" or authentication errors?**
Double-check the key starts with `fc-` and is set correctly. Get a free key at https://firecrawl.dev.

## 5. Install the Output Skill

When the pipeline finishes, it prints the exact install command with the real absolute path
to the skill folder it just built. It looks like this (path will differ on your machine):

```
  Install / update skill in agents:

    Claude Code:
    npx skills add "/Users/yourname/path/to/output/example-com-website-search-skill" -g -y -a claude-code

    All agents:
    npx skills add "/Users/yourname/path/to/output/example-com-website-search-skill" -g -y
```

**Before running:** Show the user the command printed by the pipeline and ask:

> "The skill folder is ready. Shall I install it now so your agents can search [domain] offline?"

Only run the install command after the user confirms. Use the exact path from the pipeline
output — do not use the example path shown above.

### If `npx` fails

`npx skills` requires Node.js. Check:

```bash
node --version 2>&1
```

If not found: tell the user "Node.js is required to install the skill. Download it from
https://nodejs.org (LTS version) — it includes npx." Once they install it, re-run the
install command.

After installing, the user's agents can answer questions about the website offline.
Re-run the pipeline and re-run the install command any time to pick up new pages.

## Cost

1 Firecrawl credit (map) + ~5 credits per page scraped.
Example: 100-page site ≈ 501 credits.
Incremental re-runs only pay for new or changed pages.
