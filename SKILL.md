---
name: website-to-skill-folder
description: >
  Converts any website into an installable AI skill folder by crawling all pages
  and packaging them as searchable markdown with frontmatter summaries. Use when
  asked to: create a website search skill, index a website for AI agents, scrape
  a site into a searchable knowledge base, turn a website into an offline-searchable
  skill, or make website content available to AI agents without live browsing.
  Outputs an installable skill folder plus the exact npx command to add it to any
  AI agent.
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

### Firecrawl API key (one-time, persists across sessions)

Check if already configured:

```bash
python -c "import os; print('set' if os.environ.get('FIRECRAWL_API_KEY') else 'missing')"
ls "$SKILL_DIR/scripts/.env.local" 2>/dev/null && echo ".env.local found" || echo ".env.local not found"
```

If the env var is missing **and** `.env.local` does not exist:

1. **Stop and tell the user:** "A Firecrawl API key is needed to crawl websites. Get a free key at https://firecrawl.dev — no credit card required for the free tier."
2. Once they provide the key, write it to the persistent config file next to the script:

```bash
echo 'FIRECRAWL_API_KEY=fc-their_key_here' > "$SKILL_DIR/scripts/.env.local"
```

This file persists across all future runs — the user only needs to do this once.

## 3. Run the Pipeline

```bash
python "$SKILL_DIR/scripts/pipeline.py" https://example.com
```

**Options:**

| Flag | Purpose |
|------|---------|
| `--description "..."` | One-line site description for the generated SKILL.md |
| `--max-pages 100` | Limit pages scraped — directly controls Firecrawl credit cost |
| `--skip-scrape` | Reassemble from cache — zero API calls |
| `--force-refresh` | Ignore cache, re-scrape all pages |

## 4. Install the Output Skill

Output lands in `output/` inside the current working directory. At the end, the pipeline
prints the exact install command — relay it to the user and run it:

```
  Install / update skill in agents:

    Claude Code:
    npx skills add "/absolute/path/to/output/example-com-website-search-skill" -g -y -a claude-code

    All agents:
    npx skills add "/absolute/path/to/output/example-com-website-search-skill" -g -y
```

After installing, the user's agents can answer questions about the website offline.
Re-run the pipeline and re-run the install command any time to pick up new pages.

## Cost

1 Firecrawl credit (map) + ~5 credits per page scraped.
Example: 100-page site ≈ 501 credits.
Incremental re-runs only pay for new or changed pages.
