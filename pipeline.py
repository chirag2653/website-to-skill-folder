"""
Website-to-Skill Pipeline
==========================
Takes a website URL and produces a skill folder that AI agents can search
using ripgrep. Each page becomes a markdown file with YAML frontmatter.

Usage:
    python pipeline.py https://csaok.com
    python pipeline.py csaok.com
    python pipeline.py https://csaok.com/about --description "Cosmetic surgery practice"
    python pipeline.py https://csaok.com --skip-scrape   # reuse cached scrape

Input handling:
    The script accepts any of these and resolves to the same domain:
      https://csaok.com            → domain: csaok.com
      http://csaok.com/about       → domain: csaok.com
      csaok.com                    → domain: csaok.com
      www.csaok.com                → domain: csaok.com (www. stripped)
      blog.example.com             → domain: blog.example.com (subdomain kept)

    The domain becomes: skill name, output folder name, workspace key,
    and the {domain} variable in skill-md.template.
"""

import argparse
import json
import os
import re
import sys
import time
from urllib.parse import urlparse

import requests
from pydantic import BaseModel, field_validator

# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


class PipelineInput(BaseModel):
    """Validates and normalizes the user's input into a clean domain.

    Accepts any URL-like string and resolves it to a domain.
    The domain is the single key that drives everything:
    - Skill name (D6: skill name = domain)
    - Map API URL (https://{domain})
    - Output directory (output/{domain})
    - Workspace directory (_workspace/{domain})
    - Template variable ({domain} in skill-md.template)

    Subdomain handling (per D6):
    - www.example.com  → example.com (www. is cosmetic, stripped)
    - blog.example.com → blog.example.com (different website, kept)
    - docs.stripe.com  → docs.stripe.com (different website, kept)
    """

    url: str
    description: str = ""
    output: str | None = None
    limit: int = 5000
    skip_scrape: bool = False

    # Resolved fields (set by validators)
    domain: str = ""
    map_url: str = ""

    @field_validator("url")
    @classmethod
    def normalize_url(cls, v: str) -> str:
        """Accept any URL-like input and normalize to https://domain."""
        v = v.strip()
        if not v:
            raise ValueError("URL cannot be empty. Pass a website URL like: https://example.com")

        # Add scheme if missing (bare domain like "csaok.com")
        if not v.startswith(("http://", "https://")):
            v = f"https://{v}"

        parsed = urlparse(v)
        if not parsed.netloc:
            raise ValueError(
                f"Could not parse domain from '{v}'.\n"
                f"Expected a URL like: https://example.com or just: example.com"
            )

        # Reject obvious non-website inputs
        if "." not in parsed.netloc:
            raise ValueError(
                f"'{parsed.netloc}' doesn't look like a domain.\n"
                f"Expected something like: example.com, docs.stripe.com"
            )

        return v

    @field_validator("limit")
    @classmethod
    def validate_limit(cls, v: int) -> int:
        if v < 1:
            raise ValueError("Limit must be at least 1")
        if v > 100_000:
            raise ValueError("Limit cannot exceed 100,000 (Firecrawl API max)")
        return v

    def model_post_init(self, __context) -> None:
        """Resolve domain and map_url from the validated URL."""
        parsed = urlparse(self.url)
        netloc = parsed.netloc.lower()

        # Strip www. — it's cosmetic, not a real subdomain
        if netloc.startswith("www."):
            netloc = netloc[4:]

        # Strip port if present (e.g. localhost:3000 during testing)
        if ":" in netloc:
            netloc = netloc.split(":")[0]

        self.domain = netloc
        self.map_url = f"https://{self.domain}"

        # Set defaults that depend on domain
        if not self.output:
            self.output = os.path.join("output", self.domain)
        if not self.description:
            self.description = f"a website at {self.domain}."


def parse_args() -> PipelineInput:
    """Parse CLI arguments and return validated PipelineInput."""
    parser = argparse.ArgumentParser(
        description="Convert a website into an AI-searchable skill folder.",
        epilog=(
            "Examples:\n"
            "  python pipeline.py https://csaok.com\n"
            "  python pipeline.py csaok.com\n"
            "  python pipeline.py https://docs.stripe.com --limit 100\n"
            "  python pipeline.py csaok.com --skip-scrape\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "url",
        help="Website URL or domain (e.g. https://example.com or example.com)",
    )
    parser.add_argument(
        "--description",
        help="One-line site description for SKILL.md header",
        default="",
    )
    parser.add_argument(
        "--output",
        help="Output directory (default: ./output/{domain})",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5000,
        help="Max URLs to discover in map step (default: 5000, max: 100000)",
    )
    parser.add_argument(
        "--skip-scrape",
        action="store_true",
        help="Skip map+scrape, reuse cached data from workspace",
    )

    args = parser.parse_args()

    try:
        return PipelineInput(
            url=args.url,
            description=args.description or "",
            output=args.output,
            limit=args.limit,
            skip_scrape=args.skip_scrape,
        )
    except Exception as e:
        parser.error(str(e))


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

# JSON extraction prompt — tells Firecrawl's LLM what we want (see plan.md D3)
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
    """Convert a URL path to a filesystem-safe slug (see plan.md D9)."""
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
    """Strip leading junk lines (see plan.md D8)."""
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


# ---------------------------------------------------------------------------
# Step 1: Map — discover all URLs
# ---------------------------------------------------------------------------


def map_website(map_url: str, api_key: str, limit: int = 5000) -> list[str]:
    """Use Firecrawl Map API to discover all pages on a website.

    The Map endpoint expects a full URI (format: uri), so we pass
    https://{domain} which was resolved during input validation.
    We set includeSubdomains=False because subdomains are treated
    as separate websites (see plan.md D6).
    """
    print(f"\n{'='*60}")
    print(f"STEP 1: Map — discovering pages on {map_url}")
    print(f"{'='*60}")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "url": map_url,
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
    domain: str,
    site_description: str,
) -> None:
    """Generate SKILL.md by rendering skill-md.template with variables.

    The template file (skill-md.template) is the single source of truth
    for SKILL.md content. Edit the template to change what agents see.
    Only two variables are substituted:
      {domain}           — the website domain (e.g. csaok.com)
      {site_description} — one-line description of the website
    See plan.md D6 for rationale.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    template_path = os.path.join(script_dir, "skill-md.template")

    with open(template_path, encoding="utf-8") as f:
        template = f.read()

    skill_md = template.format(
        domain=domain,
        site_description=site_description,
    )

    skill_path = os.path.join(output_dir, "SKILL.md")
    with open(skill_path, "w", encoding="utf-8") as f:
        f.write(skill_md)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    config = parse_args()

    workspace_dir = os.path.join("_workspace", config.domain)

    api_key = get_api_key()

    print(f"Website-to-Skill Pipeline")
    print(f"  Input:       {config.url}")
    print(f"  Domain:      {config.domain}")
    print(f"  Map URL:     {config.map_url}")
    print(f"  Output:      {config.output}")
    print(f"  Workspace:   {workspace_dir}")

    os.makedirs(workspace_dir, exist_ok=True)
    os.makedirs(config.output, exist_ok=True)

    if config.skip_scrape:
        # Load cached scrape data
        cache_path = os.path.join(workspace_dir, "batch-response.json")
        if not os.path.exists(cache_path):
            print(f"\nERROR: No cached data at {cache_path}")
            print("Run without --skip-scrape first.")
            sys.exit(1)
        print(f"\nSkipping map+scrape, loading cached data from {cache_path}")
        with open(cache_path, encoding="utf-8") as f:
            scrape_data = json.load(f)
        pages = scrape_data if isinstance(scrape_data, list) else scrape_data.get("data", [])
    else:
        # Step 1: Map
        urls = map_website(config.map_url, api_key, limit=config.limit)

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

    pages_dir = os.path.join(config.output, "pages")
    page_count = assemble_pages(pages, pages_dir)
    print(f"  Wrote {page_count} page files to {pages_dir}/")

    generate_skill_md(config.output, config.domain, config.description)
    print(f"  Wrote SKILL.md")

    # Summary
    print(f"\n{'='*60}")
    print(f"DONE")
    print(f"{'='*60}")
    print(f"  Skill folder: {config.output}/")
    print(f"  Pages:        {page_count}")
    print(f"  SKILL.md:     {os.path.join(config.output, 'SKILL.md')}")
    print(f"\n  Estimated cost: 1 + {page_count} x 5 = {1 + page_count * 5} credits")


if __name__ == "__main__":
    main()
