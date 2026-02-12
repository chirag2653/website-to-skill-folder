"""
Website-to-Skill Pipeline
==========================
Takes a website URL and produces a skill folder that AI agents can search
using ripgrep. Each page becomes a markdown file with YAML frontmatter.

Usage:
    python pipeline.py https://example.com
    python pipeline.py https://example.com --name my-website --limit 500
    python pipeline.py https://example.com --skip-scrape   # reuse cached scrape
"""

import argparse
import json
import os
import re
import sys
import time
from urllib.parse import urlparse

import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

FIRECRAWL_BASE = "https://api.firecrawl.dev"
CREDS_PATH = os.path.join(
    os.environ.get("APPDATA", ""),
    "firecrawl-cli",
    "credentials.json",
)

BATCH_SIZE = 100          # URLs per batch scrape request
POLL_INTERVAL = 5         # seconds between status checks
MAX_POLL_TIME = 600       # 10 minutes max wait per batch

# JSON extraction prompt — tells Firecrawl's LLM what we want
JSON_PROMPT = (
    "Extract structured metadata from this web page. This metadata will serve "
    "as frontmatter in a reference file that AI agents search through to find "
    "relevant pages. The summary field is critical — it must describe WHAT "
    "INFORMATION IS ON THIS PAGE, like a card catalog entry. Do not repeat "
    "the page content. Instead, tell the reader what they would find if they "
    "loaded the full page: what topics are covered, what questions are answered, "
    "what data points are available (e.g. pricing, recovery timelines, "
    "before-and-after photos, credentials, FAQs). An AI agent reading only "
    "the summary should be able to decide whether this page is relevant to "
    "their current task."
)

JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {
            "type": "string",
            "description": "The page title, clean and concise (without the site name suffix)",
        },
        "description": {
            "type": "string",
            "description": "A concise 1-2 sentence description of what this page is",
        },
        "summary": {
            "type": "string",
            "description": (
                "A 3-5 sentence content manifest. Describe what information "
                "this page contains as if answering: 'If I loaded this page, "
                "what would I find?' Mention specific topics covered, data "
                "available, and any unique content. This helps an AI agent "
                "decide whether to load the full page."
            ),
        },
    },
    "required": ["title", "description", "summary"],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_api_key() -> str:
    """Read Firecrawl API key from the CLI credentials file."""
    if not os.path.exists(CREDS_PATH):
        print(f"ERROR: Firecrawl credentials not found at {CREDS_PATH}")
        print("Run `firecrawl login` first.")
        sys.exit(1)
    with open(CREDS_PATH) as f:
        creds = json.load(f)
    key = creds.get("apiKey") or creds.get("api_key") or creds.get("key")
    if not key:
        print(f"ERROR: No API key found in {CREDS_PATH}")
        print(f"Keys present: {list(creds.keys())}")
        sys.exit(1)
    return key


def url_to_slug(url: str) -> str:
    """Convert a URL path to a filesystem-safe slug."""
    path = urlparse(url.rstrip("/")).path.strip("/")
    if not path:
        return "index"
    slug = path.replace("/", "--")
    slug = re.sub(r"[^a-z0-9\-]", "", slug.lower())
    return slug


def yaml_escape(s: str) -> str:
    """Escape a string for YAML double-quoted scalar."""
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def clean_markdown(md: str) -> str:
    """Strip leading junk lines (SVG icons, consult buttons, nav remnants)."""
    lines = md.split("\n")
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#"):
            return "\n".join(lines[i:])
        if stripped.startswith("[Back"):
            continue
        if stripped.startswith("Consult Now"):
            continue
        if stripped.startswith("Filter"):
            continue
        if len(stripped) > 80 and " " in stripped and not stripped.startswith("!"):
            return "\n".join(lines[i:])
    return md


def wrap_summary(summary: str, indent: int = 2, width: int = 80) -> str:
    """Word-wrap summary text with given indent."""
    prefix = " " * indent
    words = summary.split()
    lines = []
    line = prefix
    for word in words:
        if len(line) + len(word) + 1 > width:
            lines.append(line.rstrip())
            line = prefix + word + " "
        else:
            line += word + " "
    if line.strip():
        lines.append(line.rstrip())
    return "\n".join(lines)


def domain_from_url(url: str) -> str:
    """Extract the domain from a URL."""
    return urlparse(url).netloc


def skill_name_from_domain(domain: str) -> str:
    """Generate a default skill name from a domain."""
    # csaok.com -> csaok-website
    name = domain.replace("www.", "").split(".")[0]
    return f"{name}-website"


# ---------------------------------------------------------------------------
# Step 1: Map — discover all URLs
# ---------------------------------------------------------------------------


def map_website(url: str, api_key: str, limit: int = 5000) -> list[str]:
    """Use Firecrawl Map API to discover all pages on a website."""
    print(f"\n{'='*60}")
    print(f"STEP 1: Map — discovering pages on {url}")
    print(f"{'='*60}")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "url": url,
        "includeSubdomains": False,
        "ignoreQueryParameters": True,
        "limit": limit,
    }

    resp = requests.post(f"{FIRECRAWL_BASE}/v1/map", headers=headers, json=payload)
    resp.raise_for_status()
    data = resp.json()

    if not data.get("success"):
        print(f"Map failed: {json.dumps(data, indent=2)}")
        sys.exit(1)

    urls = data.get("links", [])
    print(f"  Found {len(urls)} URLs (1 credit used)")
    return urls


# ---------------------------------------------------------------------------
# Step 2: Batch Scrape — get markdown + JSON metadata
# ---------------------------------------------------------------------------


def batch_scrape(urls: list[str], api_key: str) -> list[dict]:
    """Scrape all URLs in batches, returning page data with markdown + JSON."""
    print(f"\n{'='*60}")
    print(f"STEP 2: Batch Scrape — scraping {len(urls)} pages")
    print(f"{'='*60}")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    all_pages = []
    batches = [urls[i : i + BATCH_SIZE] for i in range(0, len(urls), BATCH_SIZE)]

    for batch_num, batch_urls in enumerate(batches, 1):
        print(f"\n  Batch {batch_num}/{len(batches)} ({len(batch_urls)} URLs)...")

        payload = {
            "urls": batch_urls,
            "formats": [
                "markdown",
                {
                    "type": "json",
                    "prompt": JSON_PROMPT,
                    "schema": JSON_SCHEMA,
                },
            ],
            "onlyMainContent": True,
        }

        # Submit
        resp = requests.post(
            f"{FIRECRAWL_BASE}/v2/batch/scrape", headers=headers, json=payload
        )
        resp.raise_for_status()
        resp_data = resp.json()

        if not resp_data.get("success"):
            print(f"  Batch submit failed: {json.dumps(resp_data, indent=2)[:500]}")
            continue

        batch_id = resp_data["id"]
        print(f"  Batch ID: {batch_id}")

        # Poll for completion
        start = time.time()
        while True:
            time.sleep(POLL_INTERVAL)
            elapsed = time.time() - start
            if elapsed > MAX_POLL_TIME:
                print(f"  TIMEOUT after {MAX_POLL_TIME}s — skipping batch")
                break

            status_resp = requests.get(
                f"{FIRECRAWL_BASE}/v2/batch/scrape/{batch_id}", headers=headers
            )
            status_data = status_resp.json()
            status = status_data.get("status", "unknown")
            completed = status_data.get("completed", 0)
            total = status_data.get("total", len(batch_urls))
            print(f"    {status} — {completed}/{total} ({int(elapsed)}s)")

            if status in ("completed", "failed"):
                break

        # Collect pages (handle pagination via `next`)
        batch_pages = status_data.get("data", [])
        next_url = status_data.get("next")
        while next_url:
            print(f"    Fetching next page of results...")
            next_resp = requests.get(next_url, headers=headers)
            next_data = next_resp.json()
            batch_pages.extend(next_data.get("data", []))
            next_url = next_data.get("next")

        credits = status_data.get("creditsUsed", "?")
        print(f"  Got {len(batch_pages)} pages ({credits} credits)")
        all_pages.extend(batch_pages)

    print(f"\n  Total pages scraped: {len(all_pages)}")
    return all_pages


# ---------------------------------------------------------------------------
# Step 3: Assemble — build the skill folder
# ---------------------------------------------------------------------------


def assemble_pages(pages: list[dict], pages_dir: str) -> int:
    """Write individual page markdown files with YAML frontmatter."""
    os.makedirs(pages_dir, exist_ok=True)
    count = 0

    for page in pages:
        metadata = page.get("metadata", {})
        json_data = page.get("json", {})
        markdown = page.get("markdown", "")

        if not markdown or not markdown.strip():
            continue

        source_url = metadata.get("ogUrl") or metadata.get("sourceURL", "")
        title = json_data.get("title", metadata.get("title", "Untitled"))
        description = json_data.get("description", "")
        summary = json_data.get("summary", "")

        slug = url_to_slug(source_url)
        filepath = os.path.join(pages_dir, f"{slug}.md")

        clean_md = clean_markdown(markdown)

        with open(filepath, "w", encoding="utf-8") as f:
            f.write("---\n")
            f.write(f'title: "{yaml_escape(title)}"\n')
            f.write(f'description: "{yaml_escape(description)}"\n')
            f.write(f'url: "{source_url}"\n')
            f.write("summary: |\n")
            f.write(wrap_summary(summary) + "\n")
            f.write("---\n\n")
            f.write(clean_md)

        count += 1

    return count


def generate_skill_md(
    output_dir: str,
    skill_name: str,
    domain: str,
    site_description: str,
    page_count: int,
) -> None:
    """Generate the SKILL.md — the only file an agent loads."""

    skill_md = f"""---
name: {skill_name}
description: >
  Searchable reference for {domain}.
  Use this skill to search the website's content when creating blog briefs,
  content outlines, case studies, or any task that needs website context.
---

# Website Search — {domain}

This skill gives you searchable access to {domain} — {site_description}

The website's pages are stored as markdown files in `pages/`, each with
YAML frontmatter (title, description, url, summary). Use `rg` (ripgrep)
to search without loading pages into context.

## Important — resolve the pages path first

The `pages/` directory is **in the same folder as this SKILL.md file**.
Your working directory is probably NOT this skill folder, so bare
`pages/` paths will fail. Before running any search commands, resolve
the absolute path:

```
PAGES_DIR = <directory containing this SKILL.md>/pages
```

Use that absolute path in all commands below. Every time you see
`$PAGES` in the examples, substitute the resolved path.

## Search Flow

```
Query
  → Step 1: Expand query into search keywords
  → Step 2: rg -l "term1|term2|term3" $PAGES        → candidate filenames
  → Step 3: rg -l "..." $PAGES | xargs head -n 12   → frontmatter of candidates
  → Step 4: Pick relevant pages from summaries
  → Step 5: Load only those pages fully
```

### Step 1 — Expand your query into keywords

Before searching, think about what words the website might use for your topic.
Expand into synonyms, formal terms, informal terms, and related concepts.
This is what makes the search semantic — you bridge the gap between your query
and the website's language.

**Always expand into 3-5 terms covering different variations.**

To see what terms the site actually uses, run a discovery command first:

```bash
# See all page titles — gives you the site's vocabulary
rg "^title:" $PAGES

# See filenames — URL slugs hint at content
ls $PAGES
```

Then expand your query using what you learned:

- Your query uses informal language? → add the formal/technical term
- Your query uses technical language? → add the common/colloquial term
- Looking for a specific topic? → add related subtopics and broader categories
- Not sure what exists? → search a broad category first, then narrow

### Step 2 — Find candidates

```bash
rg -l "term1|term2|term3" $PAGES
```

Returns filenames only. Nothing loaded into context. Too many results? Narrow:

```bash
rg -l "broad_term" $PAGES | xargs rg -l "specific_term"
```

### Step 3 — Screen via frontmatter

```bash
rg -l "term1|term2" $PAGES | xargs head -n 12
```

Shows title, description, url, and summary of each candidate. Read the
summaries to judge relevance. Skip pages where the keyword appears
incidentally. Pick pages where the summary confirms the topic.

### Step 4 — Load relevant pages

Read only the files you chose (using their full paths from Step 2/3 output).

## Page Structure

Every file in `pages/` has:

```yaml
---
title: "Page Title"
description: "1-2 sentence description"
url: "https://..."
summary: |
  3-5 sentence content manifest describing what information
  this page contains. Keyword-rich for search matching.
---

# Full markdown content...
```

## Discovery Commands

When you need to understand what's on the site before searching:

```bash
# List all page titles
rg "^title:" $PAGES

# List all pages (filenames hint at content)
ls $PAGES

# Count pages
ls $PAGES | wc -l
```

## Tips

- **Resolve the path first.** `$PAGES` = the `pages/` directory next to this file.
- **Always expand keywords first.** Never search with just one term.
- **Discover first if unsure.** Run `rg "^title:" $PAGES` to see what exists.
- **Use the pipe pattern** to intersect: `rg -l "A" $PAGES | xargs rg -l "B"`
- **Frontmatter is the search surface.** Summaries are keyword-rich. A hit
  in the summary is a stronger relevance signal than a hit in the body.
- **Read before loading.** Check frontmatter (`head -n 12`) when you have
  more than 5 candidates.
"""

    skill_path = os.path.join(output_dir, "SKILL.md")
    with open(skill_path, "w", encoding="utf-8") as f:
        f.write(skill_md)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Convert a website into an AI-searchable skill folder."
    )
    parser.add_argument("url", help="The website URL to convert")
    parser.add_argument(
        "--name",
        help="Skill folder name (default: derived from domain)",
    )
    parser.add_argument(
        "--description",
        help="One-line site description (shown in SKILL.md header)",
        default="",
    )
    parser.add_argument(
        "--output",
        help="Output directory (default: ./output/{name})",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5000,
        help="Max URLs to discover in map step (default: 5000)",
    )
    parser.add_argument(
        "--skip-scrape",
        action="store_true",
        help="Skip map+scrape, reuse cached data from workspace",
    )

    args = parser.parse_args()

    # Derive names
    domain = domain_from_url(args.url)
    skill_name = args.name or skill_name_from_domain(domain)
    output_dir = args.output or os.path.join("output", skill_name)
    workspace_dir = os.path.join("_workspace", domain)

    api_key = get_api_key()

    print(f"Website-to-Skill Pipeline")
    print(f"  URL:         {args.url}")
    print(f"  Domain:      {domain}")
    print(f"  Skill name:  {skill_name}")
    print(f"  Output:      {output_dir}")
    print(f"  Workspace:   {workspace_dir}")

    os.makedirs(workspace_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    if args.skip_scrape:
        # Load cached scrape data
        cache_path = os.path.join(workspace_dir, "batch-response.json")
        if not os.path.exists(cache_path):
            print(f"ERROR: No cached data at {cache_path}")
            print("Run without --skip-scrape first.")
            sys.exit(1)
        print(f"\nSkipping map+scrape, loading cached data from {cache_path}")
        with open(cache_path, encoding="utf-8") as f:
            scrape_data = json.load(f)
        pages = scrape_data if isinstance(scrape_data, list) else scrape_data.get("data", [])
    else:
        # Step 1: Map
        urls = map_website(args.url, api_key, limit=args.limit)

        # Save URL list
        map_path = os.path.join(workspace_dir, "map-urls.txt")
        with open(map_path, "w", encoding="utf-8") as f:
            f.write("\n".join(urls))
        print(f"  Saved URL list to {map_path}")

        # Step 2: Batch Scrape
        pages = batch_scrape(urls, api_key)

        # Cache the raw scrape response
        cache_path = os.path.join(workspace_dir, "batch-response.json")
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(pages, f, indent=2, ensure_ascii=False)
        print(f"  Cached scrape data to {cache_path}")

    # Step 3: Assemble
    print(f"\n{'='*60}")
    print(f"STEP 3: Assemble — building skill folder")
    print(f"{'='*60}")

    pages_dir = os.path.join(output_dir, "pages")
    page_count = assemble_pages(pages, pages_dir)
    print(f"  Wrote {page_count} page files to {pages_dir}/")

    # Generate SKILL.md
    site_description = args.description or f"a website at {domain}."
    generate_skill_md(output_dir, skill_name, domain, site_description, page_count)
    print(f"  Wrote SKILL.md")

    # Summary
    print(f"\n{'='*60}")
    print(f"DONE")
    print(f"{'='*60}")
    print(f"  Skill folder: {output_dir}/")
    print(f"  Pages:        {page_count}")
    print(f"  SKILL.md:     {os.path.join(output_dir, 'SKILL.md')}")
    print(f"\n  Estimated cost: 1 + {page_count} × 5 = {1 + page_count * 5} credits")


if __name__ == "__main__":
    main()
