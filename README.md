# website-to-skill-folder

**Turn any website into an installable AI agent skill — one command, fully offline search.**

Point it at a URL. It crawls the site, packages every page as searchable markdown, and hands you a ready-to-install skill folder. Run the printed `npx skills add` command and your AI agents (Claude Code, Gemini CLI, Cursor, Codex, and more) can answer questions about that website — no live browsing, no API calls at query time.

---

## The Two-Step Flow

### Step 1 — Run the pipeline on any website URL

```bash
python scripts/pipeline.py https://docs.example.com
```

The pipeline maps the site, scrapes every page, and builds a skill folder in `output/`:

```
output/
└── docs.example.com-website-search-skill/
    ├── SKILL.md       # Agent instructions + keyword index
    └── pages/         # One .md file per scraped page
```

At the end it prints the exact install command:

```
  Install / update skill in agents:

    Claude Code:
    npx skills add "/path/to/output/docs.example.com-website-search-skill" -g -y -a claude-code

    All agents:
    npx skills add "/path/to/output/docs.example.com-website-search-skill" -g -y
```

### Step 2 — Install the skill

Copy and run the printed command. The website search skill is now live in your agents. Ask anything about the site:

> *"What are the authentication options?"*
> *"How do I configure webhooks?"*
> *"What changed in the latest release?"*

The agent searches the skill folder offline — fast, accurate, and with source citations back to the original page URLs.

Re-run the pipeline any time to pick up new pages. Re-run the `npx skills add` command to push the update to your agents.

---

## Install This Tool as an Agent Skill

The pipeline itself is packaged as an agent skill. Install it once and ask your agent to run it for you:

```bash
# All agents (Claude Code, Gemini CLI, Codex, Cursor, etc.):
npx skills add chirag2653/website-to-skill-folder -g -y

# Claude Code only:
npx skills add chirag2653/website-to-skill-folder -g -y -a claude-code
```

Then from any project folder, just ask:

> *"Create a website search skill for https://example.com"*

The agent runs the pipeline, builds the skill folder in `output/`, and prints the install command — you run it, the website skill is installed.

---

## Manual Setup

### Prerequisites

1. **Firecrawl API key** — get one free at [firecrawl.dev](https://firecrawl.dev) (used to map and scrape the site)

2. **Python dependencies:**
   ```bash
   pip install requests pydantic tenacity
   ```

3. **Set your API key** (choose one):
   ```bash
   # Option A: environment variable
   export FIRECRAWL_API_KEY="fc-your_key_here"

   # Option B: .env.local file next to the script
   cp scripts/.env.local.example scripts/.env.local
   # edit scripts/.env.local and add your key
   ```

### Run

```bash
python scripts/pipeline.py https://example.com
```

Output lands in `output/` inside your current directory. The script prints the `npx skills add` install command at the end.

### Options

| Flag | Purpose |
|------|---------|
| `--description "..."` | One-line site description added to the generated SKILL.md |
| `--max-pages 100` | Cap pages scraped — directly controls Firecrawl credit cost |
| `--skip-scrape` | Reassemble from cache, zero API calls |
| `--force-refresh` | Ignore cache and re-scrape all pages |

---

## What Gets Produced

Each scraped page becomes a `.md` file with YAML frontmatter optimised for fast `grep`/`ripgrep` search:

```yaml
---
title: "Page Title"
description: "1-2 sentence description"
url: "https://example.com/page"
summary: |
  3-5 sentence keyword-rich summary for search matching
---
```

The top-level `SKILL.md` indexes the whole site so agents know what's available before searching individual pages.

---

## Features

- **Incremental updates** — Only re-scrapes new or changed pages on subsequent runs
- **Resumable** — Saves progress to `_workspace/`; picks up exactly where it stopped if interrupted
- **Robust deletion** — Orphaned pages are removed only after 3 consecutive map misses (not on a single transient failure)
- **SEO-aware extraction** — Prefers `<meta>` tags over LLM extraction for title and description
- **Source citations** — Every answer the agent gives includes a link back to the original page URL
- **Multi-domain** — Each domain gets its own isolated output folder and workspace cache

---

## Cost

Powered by [Firecrawl](https://firecrawl.dev):

| Operation | Credits |
|-----------|---------|
| Map (per run) | 1 |
| Scrape (per page) | ~5 |
| 100-page site | ~501 total |

Incremental re-runs only pay for new or changed pages — far cheaper after the first run.

---

## How the Folders Are Owned

```
~/.agents/skills/website-to-skill-folder/   ← this tool (read-only, never written to)
├── SKILL.md
└── scripts/
    ├── pipeline.py
    ├── skill-md.template
    └── .env.local.example

your-project/                               ← your data (created automatically on first run)
├── output/
│   └── {domain}-website-search-skill/
│       ├── SKILL.md
│       └── pages/
└── _workspace/
    └── {domain}/
        ├── map-urls.txt
        └── state.json
```

The tool lives in the skill folder. Everything it produces — the website search skill and the workspace cache — lands in your current working directory. Nothing is ever written back to the tool's own folder.

---

## Requirements

- Python 3.8+
- [Firecrawl](https://firecrawl.dev) API key
- `pip install requests pydantic tenacity`
