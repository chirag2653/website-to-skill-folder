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

Runs `scripts/pipeline.py` to crawl a website and produce an installable skill
folder. The script handles everything — no need to read it.

## Prerequisites

**Python packages** (install once):
```bash
pip install requests pydantic tenacity
```

**Firecrawl API key** — get one free at [firecrawl.dev](https://firecrawl.dev):
```bash
# Option 1: environment variable
export FIRECRAWL_API_KEY="fc-your_key_here"

# Option 2: .env.local file next to the script
echo 'FIRECRAWL_API_KEY=fc-your_key_here' > "$SKILL_DIR/scripts/.env.local"
```

## Locate the Skill

```bash
SKILL_DIR="$HOME/.agents/skills/website-to-skill-folder"
[ -d "$SKILL_DIR" ] || SKILL_DIR=$(find "$HOME/.agents/skills" "$HOME/.claude/skills" \
  -maxdepth 2 -type d -name "website-to-skill-folder" 2>/dev/null | head -1)
```

## Run

```bash
python "$SKILL_DIR/scripts/pipeline.py" https://example.com
```

**Options:**

| Flag | Purpose |
|------|---------|
| `--description "..."` | One-line site description for the generated SKILL.md |
| `--max-pages 100` | Limit pages scraped (controls Firecrawl credit cost) |
| `--skip-scrape` | Reassemble from cache — zero API calls |
| `--force-refresh` | Ignore cache, re-scrape all pages |

## Output & Install

When done, the pipeline prints two install commands. Run the appropriate one:

```bash
# Claude Code only:
npx skills add "/absolute/path/to/output/skill-folder" -g -y -a claude-code

# All agents (Claude Code, Gemini CLI, Codex, Cursor, etc.):
npx skills add "/absolute/path/to/output/skill-folder" -g -y
```

Re-run the same command after any pipeline rerun to refresh the installed skill.

## Cost

1 Firecrawl credit (map) + ~5 credits per page scraped.
Example: 100-page site ≈ 501 credits.
