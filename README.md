# Website-to-Skill Pipeline

Convert any website into an AI-searchable skill folder that agents can use to answer questions about the site's content.

## Install as an AI Agent Skill (Recommended)

Install directly into your AI agents via [npx skills](https://github.com/vercel-labs/skills):

```bash
# All agents (Claude Code, Gemini CLI, Codex, Cursor, etc.):
npx skills add chirag2653/website-to-skill-folder -g -y

# Claude Code only:
npx skills add chirag2653/website-to-skill-folder -g -y -a claude-code
```

Once installed, ask your agent: *"Create a website search skill for https://example.com"* — the agent handles the rest and gives you the install command for the produced skill.

## Manual Usage

### Setup

1. **Get a Firecrawl API key** from [firecrawl.dev](https://firecrawl.dev)

2. **Install Python dependencies**:
   ```bash
   pip install requests pydantic tenacity
   ```

3. **Set your API key** (choose one method):
   ```bash
   # Option 1: Environment variable
   export FIRECRAWL_API_KEY="your_api_key_here"

   # Option 2: .env.local file (copy from example)
   cp skills/website-to-skill-folder/scripts/.env.local.example skills/website-to-skill-folder/scripts/.env.local
   # then edit .env.local and add your key
   ```

### Run

```bash
python skills/website-to-skill-folder/scripts/pipeline.py https://example.com
```

### Options

```bash
# With custom description
python skills/website-to-skill-folder/scripts/pipeline.py https://example.com --description "E-commerce platform"

# Limit to first 100 pages (controls cost)
python skills/website-to-skill-folder/scripts/pipeline.py https://example.com --max-pages 100

# Skip scraping, reuse cached data
python skills/website-to-skill-folder/scripts/pipeline.py https://example.com --skip-scrape

# Force full re-scrape
python skills/website-to-skill-folder/scripts/pipeline.py https://example.com --force-refresh
```

### Output

After the pipeline runs, it prints the install command for the produced skill:

```
npx skills add "/path/to/output/example-com-website-search-skill" -g -y
```

Run that command to install the website search skill into your agents.

## How It Works

1. **Map**: Discovers all URLs on the website via Firecrawl Map API (1 credit)
2. **Scrape**: Batch scrapes each page as markdown + extracts AI metadata (~5 credits/page)
3. **Assemble**: Builds a skill folder — `SKILL.md` + one `pages/*.md` per page

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

## Folder Structure

```
skills/website-to-skill-folder/
├── SKILL.md                      # Agent instructions for this pipeline skill
├── scripts/
│   ├── pipeline.py               # Main pipeline script
│   ├── skill-md.template         # Template for generated website skill SKILL.md
│   └── .env.local.example        # API key setup reference
├── output/                       # Generated skill folders (gitignored)
│   └── {domain}-website-search-skill/
│       ├── SKILL.md
│       └── pages/
└── _workspace/                   # Cache & state per domain (gitignored)
    └── {domain}/
        ├── map-urls.txt
        └── state.json
```

## Cost

- **Map**: 1 Firecrawl credit per run
- **Scrape**: ~5 credits per page
- **Example**: 100-page site = 1 + (100 × 5) = **501 credits**

Incremental updates only scrape new/changed pages — subsequent runs on the same site cost far less.

## Features

- ✅ **Incremental updates** — Only scrapes new/changed pages on re-runs
- ✅ **Resumable** — Saves progress, can resume if interrupted mid-scrape
- ✅ **Robust deletion** — Orphaned pages removed only after 3 consecutive map misses
- ✅ **SEO-aware** — Prioritises meta tags over LLM extraction for title/description
- ✅ **Source citations** — Generated skills automatically cite page URLs
- ✅ **Multi-domain** — Each domain gets its own isolated output and workspace

## Requirements

- Python 3.8+
- [Firecrawl](https://firecrawl.dev) API key
- `pip install requests pydantic tenacity`
