# Website-to-Skill Pipeline

Convert any website into an AI-searchable skill folder that agents can use to answer questions about the site's content.

## Quick Start

1. **Get a Firecrawl API key** from [firecrawl.dev](https://firecrawl.dev)

2. **Set up your API key** (choose one method):
   ```bash
   # Option 1: Environment variable (recommended)
   $env:FIRECRAWL_API_KEY = "your_api_key_here"
   
   # Option 2: .env.local file (create from .env.local.example)
   # Copy .env.local.example to .env.local and add your key
   
   # Option 3: Firecrawl CLI (fallback)
   firecrawl login
   ```

3. **Run the pipeline**:
   ```bash
   python pipeline.py https://example.com
   ```

4. **Find your skill folder**:
   ```
   output/example-com-website-search-skill/
   ├── SKILL.md          # Instructions for AI agents
   └── pages/            # All website pages as markdown files
       ├── index.md
       ├── about.md
       └── ...
   ```

## What It Does

- **Discovers** all pages on a website using Firecrawl's Map API
- **Scrapes** each page and extracts structured metadata (title, description, summary)
- **Generates** a searchable skill folder with:
  - `SKILL.md` - Instructions for AI agents on how to search and use the content
  - `pages/` - All website pages as markdown files with YAML frontmatter

## Usage Examples

```bash
# Basic usage
python pipeline.py https://example.com

# With custom description
python pipeline.py https://example.com --description "E-commerce platform"

# Limit to first 100 pages
python pipeline.py https://example.com --max-pages 100

# Skip scraping, reuse cached data (idempotent mode)
python pipeline.py https://example.com --skip-scrape

# Force refresh - ignore cache, scrape everything
python pipeline.py https://example.com --force-refresh
```

## How It Works

1. **Map**: Discovers all URLs on the website (1 credit)
2. **Scrape**: Batch scrapes pages with markdown + JSON extraction (~5 credits per page)
3. **Assemble**: Generates skill folder with searchable markdown files

## Cost Estimation

- **Map**: 1 credit per run
- **Scrape**: ~5 credits per page
- **Example**: 100-page website = 1 + (100 × 5) = **501 credits**

The pipeline uses incremental updates by default - it only scrapes new/changed pages on subsequent runs.

## Folder Structure

The pipeline creates these folders automatically on first run:

```
website-to-skill-folder/
├── output/                    # Generated skill folders (created automatically)
│   └── {domain}-website-search-skill/
│       ├── SKILL.md          # Agent instructions
│       └── pages/            # All website pages as markdown
├── _workspace/               # Cache & state (created automatically)
│   └── {domain}/             # Per-domain workspace
│       ├── map-urls.txt      # Discovered URLs
│       ├── state.json        # Batch scrape state
│       └── batch-response.json  # Cached results
└── pipeline.py               # Main script
```

**Note**: The `output/` and `_workspace/` folders are created automatically when you first run the pipeline. They're included in the repo (empty) to show the expected structure.

Each page file has YAML frontmatter:
```yaml
---
title: "Page Title"
description: "1-2 sentence description"
url: "https://example.com/page"
summary: |
  3-5 sentence keyword-rich summary
---
```

## Requirements

- Python 3.8+
- Firecrawl API key ([get one here](https://firecrawl.dev))
- Dependencies: `requests`, `pydantic`, `tenacity`

Install dependencies:
```bash
pip install requests pydantic tenacity
```

## Multi-Domain Support

The pipeline automatically handles multiple domains. Each domain gets:
- **Output folder**: `output/{domain}-website-search-skill/`
- **Workspace folder**: `_workspace/{domain}/` (cache & state)

Run the same script for different websites:
```bash
python pipeline.py https://site1.com
python pipeline.py https://site2.com
python pipeline.py https://docs.site3.com  # Subdomains are separate
```

## Features

- ✅ **Incremental updates** - Only scrapes new/changed pages
- ✅ **Resumable** - Saves progress, can resume if interrupted
- ✅ **SEO-aware** - Prioritizes meta tags over LLM extraction
- ✅ **HTML cleanup** - Strips HTML tags from extracted content
- ✅ **Source citations** - Agents automatically cite page URLs
- ✅ **Multi-domain** - Handles hundreds of websites independently

## License

[Add your license here]

## Contributing

[Add contribution guidelines if desired]
