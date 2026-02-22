# Website-to-Skill Pipeline

Convert any website into an AI-searchable skill folder that agents can use to answer questions about the site's content.

## How It Works

The pipeline has two distinct parts with a clear boundary:

**The skill (read-only tool — never written to):**
```
~/.agents/skills/website-to-skill-folder/
├── SKILL.md              # Instructions for AI agents
└── scripts/
    ├── pipeline.py       # The pipeline script
    ├── skill-md.template # Template used internally by the script
    └── .env.local.example
```

**Your project folder (written to when you run the pipeline):**
```
your-project/             # wherever you run the script from
├── output/               # created automatically on first run
│   └── {domain}-website-search-skill/
│       ├── SKILL.md      # The produced website search skill
│       └── pages/        # One .md file per scraped page
└── _workspace/           # created automatically on first run
    └── {domain}/         # per-domain cache and run state
        ├── map-urls.txt
        └── state.json
```

The script and its internal files live in the skill folder. Everything it produces — output skills and the workspace cache that enables incremental updates and resumability — lands in your current working directory. Nothing is ever written back to the skill folder.

---

## Install as an AI Agent Skill (Recommended)

Install into your AI agents via [npx skills](https://github.com/vercel-labs/skills):

```bash
# All agents (Claude Code, Gemini CLI, Codex, Cursor, etc.):
npx skills add chirag2653/website-to-skill-folder -g -y

# Claude Code only:
npx skills add chirag2653/website-to-skill-folder -g -y -a claude-code
```

Then ask your agent from any project folder:
> *"Create a website search skill for https://example.com"*

The agent runs the pipeline, and output lands in `output/` inside your current project folder. At the end it prints the exact `npx skills add` command to install the produced skill — run it and the website search skill is available in all your agents.

---

## Manual Usage

Clone the repo, then run from the repo root:

### Setup

1. **Get a Firecrawl API key** from [firecrawl.dev](https://firecrawl.dev)

2. **Install Python dependencies:**
   ```bash
   pip install requests pydantic tenacity
   ```

3. **Set your API key** (choose one):
   ```bash
   # Option 1: environment variable
   export FIRECRAWL_API_KEY="your_api_key_here"

   # Option 2: .env.local file next to the script
   cp scripts/.env.local.example scripts/.env.local
   # edit scripts/.env.local and add your key
   ```

### Run

```bash
python scripts/pipeline.py https://example.com
```

Output is created in `output/` inside the current directory. The script prints the install command at the end.

### Options

| Flag | Purpose |
|------|---------|
| `--description "..."` | One-line site description for the generated SKILL.md |
| `--max-pages 100` | Limit pages scraped — controls Firecrawl credit cost |
| `--skip-scrape` | Reassemble from cache, zero API calls |
| `--force-refresh` | Ignore cache, re-scrape all pages |

---

## Pipeline Steps

1. **Map** — Discovers all URLs on the website via Firecrawl Map API (1 credit)
2. **Scrape** — Batch scrapes each page as markdown + extracts AI metadata (~5 credits/page)
3. **Assemble** — Builds the skill folder: `SKILL.md` + one `pages/*.md` per page

Each page file gets YAML frontmatter for fast ripgrep search:
```yaml
---
title: "Page Title"
description: "1-2 sentence description"
url: "https://example.com/page"
summary: |
  3-5 sentence keyword-rich summary for search matching
---
```

---

## Cost

- **Map:** 1 Firecrawl credit per run
- **Scrape:** ~5 credits per page
- **Example:** 100-page site = 1 + (100 × 5) = **501 credits**

Subsequent runs on the same site only scrape new or changed pages — incremental updates cost far less.

---

## Features

- ✅ **Incremental updates** — Only scrapes new/changed pages on re-runs
- ✅ **Resumable** — Saves progress, resumes from where it stopped if interrupted
- ✅ **Robust deletion** — Orphaned pages removed only after 3 consecutive map misses
- ✅ **SEO-aware** — Prioritises meta tags over LLM extraction for title/description
- ✅ **Source citations** — Generated skills automatically cite page URLs
- ✅ **Multi-domain** — Each domain gets its own isolated output and workspace

---

## Requirements

- Python 3.8+
- [Firecrawl](https://firecrawl.dev) API key
- `pip install requests pydantic tenacity`
