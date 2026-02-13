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
    python pipeline.py https://csaok.com --force-refresh  # ignore cache, scrape all

Modes:
    Default (no flags):  Incremental update -- always maps, compares, scrapes only new URLs
    --skip-scrape:       Idempotent -- uses cache, zero API calls
    --force-refresh:     Full refresh -- ignores cache, scrapes everything

Input handling:
    The script accepts any of these and resolves to the same domain:
      https://csaok.com            -> domain: csaok.com
      http://csaok.com/about       -> domain: csaok.com
      csaok.com                    -> domain: csaok.com
      www.csaok.com                -> domain: csaok.com (www. stripped)
      blog.example.com             -> domain: blog.example.com (subdomain kept)

    The domain becomes: output folder name, workspace key, and the {domain}
    variable in skill-md.template. The skill name is derived from domain
    as: {domain}-website-search-skill (e.g. csaok-com-website-search-skill).
"""

import argparse
import hashlib
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests
from pydantic import BaseModel, field_validator
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Retry configuration
# ---------------------------------------------------------------------------


def _is_retryable_error(exception: BaseException) -> bool:
    """Return True for transient errors that should be retried.

    Retries on:
      - Network timeouts
      - Connection errors
      - HTTP 429 (rate limit), 500, 502, 503, 504 (server errors)

    Does NOT retry on:
      - HTTP 400, 401, 403, 404 (permanent client errors)
    """
    if isinstance(
        exception,
        (requests.exceptions.Timeout, requests.exceptions.ConnectionError),
    ):
        return True
    if isinstance(exception, requests.exceptions.HTTPError):
        status = exception.response.status_code if exception.response is not None else 0
        return status in (429, 500, 502, 503, 504)
    return False


RETRY_CONFIG = {
    "stop": stop_after_attempt(5),
    "wait": wait_exponential(multiplier=1, min=2, max=60),
    "retry": retry_if_exception(_is_retryable_error),
    "reraise": True,
    "before_sleep": before_sleep_log(logger, logging.WARNING),
}


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


class PipelineInput(BaseModel):
    """Validates and normalizes the user's input into a clean domain.

    Accepts any URL-like string and resolves it to a domain.
    The domain is the single key that drives everything:
    - Skill name: {domain}-website-search-skill (e.g. csaok-com-website-search-skill)
    - Map API URL (https://{domain})
    - Output directory (output/{domain})
    - Workspace directory (_workspace/{domain})
    - Template variables ({domain} and {skill_name} in skill-md.template)

    Subdomain handling (per D6):
    - www.example.com  -> example.com (www. is cosmetic, stripped)
    - blog.example.com -> blog.example.com (different website, kept)
    - docs.stripe.com  -> docs.stripe.com (different website, kept)
    """

    url: str
    description: str = ""
    output: str | None = None
    limit: int = 5000
    skip_scrape: bool = False
    force_refresh: bool = False

    # Resolved fields (set by validators)
    domain: str = ""
    map_url: str = ""
    skill_name: str = ""

    @field_validator("url")
    @classmethod
    def normalize_url(cls, v: str) -> str:
        """Accept any URL-like input and normalize to https://domain.

        Handles real-world input from UI text fields:
        - Strips whitespace, newlines, tabs
        - Strips trailing punctuation (periods, commas)
        - Adds https:// if no scheme (bare domain input)
        - Accepts any scheme (http, ftp, etc.) -- always uses https
        - Rejects multi-word input (natural language)
        - Rejects strings without a valid TLD
        """
        v = v.strip()
        if not v:
            raise ValueError(
                "URL cannot be empty.\n"
                "Pass a website URL or domain, e.g.: https://example.com or example.com"
            )

        # Reject multi-word input (natural language, not a URL)
        # URLs never have unencoded spaces in the domain portion
        if " " in v.split("//")[-1].split("/")[0]:
            raise ValueError(
                f"'{v}' looks like text, not a URL.\n"
                f"Pass just the website URL or domain, e.g.: example.com"
            )

        # Strip trailing punctuation (copy-paste artifacts)
        v = v.rstrip(".,;:!? ")

        # Normalize scheme -- accept any, always use https
        if "://" in v:
            # Replace any scheme with https
            v = "https://" + v.split("://", 1)[1]
        elif not v.startswith(("http://", "https://")):
            v = f"https://{v}"

        parsed = urlparse(v)
        if not parsed.netloc:
            raise ValueError(
                f"Could not parse a domain from '{v}'.\n"
                f"Expected: https://example.com, example.com, or docs.stripe.com"
            )

        # Validate the domain has a TLD (at least one dot)
        netloc_clean = parsed.netloc.split(":")[0]  # strip port for check
        if "." not in netloc_clean:
            raise ValueError(
                f"'{netloc_clean}' is not a valid domain (no TLD).\n"
                f"Expected something like: example.com, docs.stripe.com"
            )

        # Strip trailing dot from domain (DNS root, copy-paste artifact)
        if parsed.netloc.endswith("."):
            v = v.replace(parsed.netloc, parsed.netloc.rstrip("."), 1)

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

        # Strip www. -- it's cosmetic, not a real subdomain
        if netloc.startswith("www."):
            netloc = netloc[4:]

        # Strip port if present (e.g. localhost:3000 during testing)
        if ":" in netloc:
            netloc = netloc.split(":")[0]

        # Strip trailing dot (DNS root notation artifact)
        netloc = netloc.rstrip(".")

        self.domain = netloc
        self.map_url = f"https://{self.domain}"
        self.skill_name = domain_to_skill_name(self.domain)

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
            "  python pipeline.py docs.stripe.com --limit 100\n"
            "  python pipeline.py csaok.com --skip-scrape\n"
            "  python pipeline.py csaok.com --force-refresh\n"
            "\n"
            "Modes:\n"
            "  Default:          Incremental update (map, compare, scrape new only)\n"
            "  --skip-scrape:    Use cache, zero API calls (idempotent)\n"
            "  --force-refresh:  Ignore cache, scrape everything\n"
            "\n"
            "Subdomain handling:\n"
            "  Domains and subdomains are treated as SEPARATE websites.\n"
            "  example.com and blog.example.com produce two different skill folders.\n"
            "  www. is the only prefix that gets stripped (it's cosmetic, not a real subdomain).\n"
            "\n"
            "  example.com          -> skill: example-com-website-search-skill\n"
            "  www.example.com      -> skill: example-com-website-search-skill (www. stripped)\n"
            "  blog.example.com     -> skill: blog-example-com-website-search-skill\n"
            "  docs.stripe.com      -> skill: docs-stripe-com-website-search-skill\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "url",
        help=(
            "Website URL or domain. Accepts any format: "
            "https://example.com, example.com, or a full page URL. "
            "The domain is extracted and converted to skill name format: "
            "{domain}-website-search-skill."
        ),
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
        help="Skip map+scrape, reuse cached data from workspace (idempotent mode)",
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Ignore all cache, scrape everything from scratch",
    )

    args = parser.parse_args()

    # Validate mutually exclusive flags
    if args.skip_scrape and args.force_refresh:
        parser.error("--skip-scrape and --force-refresh are mutually exclusive")

    try:
        return PipelineInput(
            url=args.url,
            description=args.description or "",
            output=args.output,
            limit=args.limit,
            skip_scrape=args.skip_scrape,
            force_refresh=args.force_refresh,
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

# JSON extraction prompt -- tells Firecrawl's LLM what we want (see plan.md D3)
JSON_PROMPT = (
    "Extract structured metadata from this web page. This metadata will serve "
    "as frontmatter in a reference file that AI agents search through to find "
    "relevant pages. The summary field is critical -- it must describe WHAT "
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


def domain_to_skill_name(domain: str) -> str:
    """Convert domain to skill name format: domain-website-search-skill.

    Examples:
        csaok.com -> csaok-com-website-search-skill
        docs.stripe.com -> docs-stripe-com-website-search-skill
    """
    # Replace dots with hyphens, append suffix
    skill_name = domain.replace(".", "-") + "-website-search-skill"
    return skill_name


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
# State management
# ---------------------------------------------------------------------------


def load_state(workspace_dir: str) -> dict:
    """Load state.json or return empty state.

    Handles corruption gracefully -- falls back to empty state with a warning.
    """
    state_path = os.path.join(workspace_dir, "state.json")
    if os.path.exists(state_path):
        try:
            with open(state_path, encoding="utf-8") as f:
                state = json.load(f)
            if isinstance(state, dict):
                return state
            logger.warning("state.json is not a dict -- treating as first run")
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"state.json corrupted ({e}) -- treating as first run")
    return {"map": {}, "batches": {}}


def save_state(workspace_dir: str, state: dict) -> None:
    """Save state.json atomically using temp file + rename."""
    state_path = os.path.join(workspace_dir, "state.json")
    temp_path = state_path + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    os.replace(temp_path, state_path)


def get_batch_id(urls: list[str]) -> str:
    """Generate deterministic batch ID from sorted URLs.

    Same set of URLs always produces the same batch_id (idempotency).
    """
    urls_str = "\n".join(sorted(urls))
    return hashlib.sha256(urls_str.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Map comparison (incremental update support)
# ---------------------------------------------------------------------------


def compare_maps(new_urls: list[str], cached_urls: list[str]) -> dict:
    """Compare new map vs cached map.

    Returns:
        {
            "new": [...],       # URLs in new but not cache
            "unchanged": [...], # URLs in both
            "deleted": [...]    # URLs in cache but not new
        }
    """
    new_set = set(new_urls)
    cached_set = set(cached_urls)
    return {
        "new": sorted(new_set - cached_set),
        "unchanged": sorted(new_set & cached_set),
        "deleted": sorted(cached_set - new_set),
    }


def load_existing_pages(urls: list[str], workspace_dir: str) -> list[dict]:
    """Load previously scraped pages for the given URLs from cache.

    Tries state.json first (more granular), falls back to batch-response.json.
    """
    if not urls:
        return []

    url_set = set(urls)
    pages = []
    seen_urls: set[str] = set()

    # Try state.json first
    state = load_state(workspace_dir)
    for batch_state in state.get("batches", {}).values():
        if batch_state.get("status") != "completed":
            continue
        for page in batch_state.get("pages", []):
            page_url = page.get("metadata", {}).get("sourceURL", "")
            if page_url in url_set and page_url not in seen_urls:
                pages.append(page)
                seen_urls.add(page_url)

    # Fallback to batch-response.json for any remaining
    if len(seen_urls) < len(url_set):
        cache_path = os.path.join(workspace_dir, "batch-response.json")
        if os.path.exists(cache_path):
            try:
                with open(cache_path, encoding="utf-8") as f:
                    all_pages = json.load(f)
                if isinstance(all_pages, list):
                    for page in all_pages:
                        page_url = page.get("metadata", {}).get("sourceURL", "")
                        if page_url in url_set and page_url not in seen_urls:
                            pages.append(page)
                            seen_urls.add(page_url)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Could not load batch-response.json: {e}")

    return pages


# ---------------------------------------------------------------------------
# Step 1: Map -- discover all URLs
# ---------------------------------------------------------------------------


@retry(**RETRY_CONFIG)
def _map_website_api_call(map_url: str, api_key: str, limit: int) -> list[str]:
    """Make the Map API call with automatic retries.

    Retries on transient failures (network, rate limit, server errors).
    Raises immediately on permanent failures (400, 401, 403, 404).
    """
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
        raise RuntimeError(
            f"Map API returned success=false: {json.dumps(data, indent=2)[:500]}"
        )

    return data.get("links", [])


def map_website(
    map_url: str,
    api_key: str,
    limit: int,
    workspace_dir: str,
    skip_scrape: bool = False,
    force_refresh: bool = False,
) -> dict:
    """Map website with incremental update / idempotency / force-refresh support.

    Behavior by mode:
      Default (incremental): Always call API, compare with cache, identify new URLs.
      --skip-scrape:         Use cache if valid, skip API (idempotency).
      --force-refresh:       Ignore cache, call API, treat all URLs as new.

    Returns:
        {
            "urls": [...],           # All URLs
            "new_urls": [...],       # URLs not in cache (need scraping)
            "unchanged_urls": [...], # URLs already cached
            "deleted_urls": [...],   # URLs removed from site
            "from_cache": bool       # True if map came from cache
        }
    """
    print(f"\n{'='*60}")
    print(f"STEP 1: Map -- discovering pages on {map_url}")
    print(f"{'='*60}")

    map_path = os.path.join(workspace_dir, "map-urls.txt")
    map_request_path = os.path.join(workspace_dir, "map-request.json")

    # --- Force refresh: ignore cache, call API ---
    if force_refresh:
        print("  Force refresh: ignoring cache")
        new_urls = _map_website_api_call(map_url, api_key, limit)
        cached_urls: list[str] = []
        print(f"  Found {len(new_urls)} URLs (1 credit used)")

    # --- Idempotency (--skip-scrape): use cache if available ---
    elif skip_scrape:
        if os.path.exists(map_path) and os.path.exists(map_request_path):
            try:
                with open(map_request_path, encoding="utf-8") as f:
                    cached_request = json.load(f)
                if (
                    cached_request.get("url") == map_url
                    and cached_request.get("limit") == limit
                ):
                    with open(map_path, encoding="utf-8") as f:
                        cached_urls = [line.strip() for line in f if line.strip()]
                    print(f"  Using cached map ({len(cached_urls)} URLs, 0 credits)")
                    return {
                        "urls": cached_urls,
                        "new_urls": [],
                        "unchanged_urls": cached_urls,
                        "deleted_urls": [],
                        "from_cache": True,
                    }
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Cache read failed ({e}) -- calling API")

        # Cache miss or mismatch -- fall through to API call
        print("  No valid cache -- calling Map API")
        new_urls = _map_website_api_call(map_url, api_key, limit)
        cached_urls = []
        print(f"  Found {len(new_urls)} URLs (1 credit used)")

    # --- Default: incremental update ---
    else:
        print("  Incremental update: getting fresh map to detect changes")
        new_urls = _map_website_api_call(map_url, api_key, limit)
        print(f"  Found {len(new_urls)} URLs (1 credit used)")

        # Load cached map for comparison
        cached_urls = []
        if os.path.exists(map_path):
            try:
                with open(map_path, encoding="utf-8") as f:
                    cached_urls = [line.strip() for line in f if line.strip()]
            except OSError:
                cached_urls = []

    # Save new map (always, unless we returned early from cache above)
    with open(map_path, "w", encoding="utf-8") as f:
        f.write("\n".join(new_urls))
    with open(map_request_path, "w", encoding="utf-8") as f:
        json.dump({"url": map_url, "limit": limit}, f)
    print(f"  Saved URL list to {map_path}")

    # Compare for incremental update
    comparison = compare_maps(new_urls, cached_urls)

    if cached_urls:
        print(
            f"  Comparison: {len(comparison['new'])} new, "
            f"{len(comparison['unchanged'])} unchanged, "
            f"{len(comparison['deleted'])} deleted"
        )
    else:
        print(f"  First run -- all {len(new_urls)} URLs are new")

    return {
        "urls": new_urls,
        "new_urls": comparison["new"],
        "unchanged_urls": comparison["unchanged"],
        "deleted_urls": comparison["deleted"],
        "from_cache": False,
    }


# ---------------------------------------------------------------------------
# Step 2: Batch Scrape -- get markdown + JSON metadata
# ---------------------------------------------------------------------------


@retry(**RETRY_CONFIG)
def _batch_submit_api_call(urls: list[str], api_key: str) -> dict:
    """Submit a batch scrape request with automatic retries."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "urls": urls,
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

    resp = requests.post(
        f"{FIRECRAWL_BASE}/v2/batch/scrape", headers=headers, json=payload
    )
    resp.raise_for_status()
    data = resp.json()

    if not data.get("success"):
        raise RuntimeError(
            f"Batch submit failed: {json.dumps(data, indent=2)[:500]}"
        )

    return data


@retry(**RETRY_CONFIG)
def _batch_poll_api_call(batch_id: str, api_key: str) -> dict:
    """Poll batch scrape status with automatic retries."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    resp = requests.get(
        f"{FIRECRAWL_BASE}/v2/batch/scrape/{batch_id}", headers=headers
    )
    resp.raise_for_status()
    return resp.json()


@retry(**RETRY_CONFIG)
def _batch_next_page_api_call(next_url: str, api_key: str) -> dict:
    """Fetch next page of batch results with automatic retries."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    resp = requests.get(next_url, headers=headers)
    resp.raise_for_status()
    return resp.json()


def batch_scrape(
    urls: list[str],
    api_key: str,
    workspace_dir: str,
    force_refresh: bool = False,
) -> list[dict]:
    """Scrape URLs in batches with state persistence and resume capability.

    Features:
      - Checks state.json for completed batches (skip resubmission)
      - Saves state incrementally after each batch completes
      - Resumes incomplete batches (status=polling) on restart
      - All API calls have automatic retry with exponential backoff
    """
    print(f"\n{'='*60}")
    print(f"STEP 2: Batch Scrape -- scraping {len(urls)} pages")
    print(f"{'='*60}")

    state = load_state(workspace_dir)
    if "batches" not in state:
        state["batches"] = {}

    all_pages: list[dict] = []
    batches = [urls[i : i + BATCH_SIZE] for i in range(0, len(urls), BATCH_SIZE)]
    credits_used = 0

    for batch_num, batch_urls in enumerate(batches, 1):
        batch_id = get_batch_id(batch_urls)
        batch_state = state["batches"].get(batch_id, {})

        # --- Check if batch already completed (idempotency) ---
        if not force_refresh and batch_state.get("status") == "completed":
            cached_pages = batch_state.get("pages", [])
            print(
                f"\n  Batch {batch_num}/{len(batches)}: "
                f"Using cached result ({len(cached_pages)} pages, 0 credits)"
            )
            all_pages.extend(cached_pages)
            continue

        print(f"\n  Batch {batch_num}/{len(batches)} ({len(batch_urls)} URLs)...")

        # --- Check if batch was submitted but not completed (resume) ---
        firecrawl_batch_id = batch_state.get("firecrawl_batch_id")

        if (
            not force_refresh
            and batch_state.get("status") == "polling"
            and firecrawl_batch_id
        ):
            print(f"  Resuming polling for batch {firecrawl_batch_id}")
        else:
            # Submit new batch
            try:
                resp_data = _batch_submit_api_call(batch_urls, api_key)
            except Exception as e:
                logger.error(f"Batch {batch_num} submit failed after retries: {e}")
                state["batches"][batch_id] = {
                    "batch_id": batch_id,
                    "urls": batch_urls,
                    "status": "failed",
                    "error": str(e),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                save_state(workspace_dir, state)
                continue

            firecrawl_batch_id = resp_data["id"]
            print(f"  Batch ID: {firecrawl_batch_id}")

            # Save state as polling (for resume on crash)
            state["batches"][batch_id] = {
                "batch_id": batch_id,
                "firecrawl_batch_id": firecrawl_batch_id,
                "urls": batch_urls,
                "status": "polling",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            save_state(workspace_dir, state)

        # --- Poll for completion ---
        start = time.time()
        status_data: dict = {}
        poll_succeeded = False

        while True:
            time.sleep(POLL_INTERVAL)
            elapsed = time.time() - start
            if elapsed > MAX_POLL_TIME:
                print(f"  TIMEOUT after {MAX_POLL_TIME}s -- skipping batch")
                state["batches"][batch_id]["status"] = "failed"
                state["batches"][batch_id]["error"] = "poll_timeout"
                save_state(workspace_dir, state)
                break

            try:
                status_data = _batch_poll_api_call(firecrawl_batch_id, api_key)
            except Exception as e:
                logger.error(f"Poll failed after retries: {e}")
                state["batches"][batch_id]["status"] = "failed"
                state["batches"][batch_id]["error"] = str(e)
                save_state(workspace_dir, state)
                break

            status = status_data.get("status", "unknown")
            completed = status_data.get("completed", 0)
            total = status_data.get("total", len(batch_urls))
            print(f"    {status} -- {completed}/{total} ({int(elapsed)}s)")

            if status == "completed":
                poll_succeeded = True
                break
            if status == "failed":
                state["batches"][batch_id]["status"] = "failed"
                state["batches"][batch_id]["error"] = "batch_failed"
                save_state(workspace_dir, state)
                break

        if not poll_succeeded:
            continue

        # --- Collect pages (handle pagination via `next`) ---
        batch_pages = status_data.get("data", [])
        next_url = status_data.get("next")
        while next_url:
            print(f"    Fetching next page of results...")
            try:
                next_data = _batch_next_page_api_call(next_url, api_key)
                batch_pages.extend(next_data.get("data", []))
                next_url = next_data.get("next")
            except Exception as e:
                logger.error(f"Pagination failed: {e}")
                break

        batch_credits = status_data.get("creditsUsed", 0)
        credits_used += batch_credits if isinstance(batch_credits, int) else 0
        print(f"  Got {len(batch_pages)} pages ({batch_credits} credits)")

        # Save completed batch to state
        state["batches"][batch_id] = {
            "batch_id": batch_id,
            "firecrawl_batch_id": firecrawl_batch_id,
            "urls": batch_urls,
            "status": "completed",
            "pages": batch_pages,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        save_state(workspace_dir, state)

        all_pages.extend(batch_pages)

    print(f"\n  Total pages scraped: {len(all_pages)}")
    if credits_used:
        print(f"  Credits used this run: {credits_used}")
    return all_pages


# ---------------------------------------------------------------------------
# Step 3: Assemble -- build the skill folder
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
    skill_name: str,
    site_description: str,
) -> None:
    """Generate SKILL.md by rendering skill-md.template with variables.

    The template file (skill-md.template) is the single source of truth
    for SKILL.md content. Edit the template to change what agents see.
    Three variables are substituted:
      {domain}           -- the website domain (e.g. csaok.com)
      {skill_name}      -- the skill name (e.g. csaok-com-website-search-skill)
      {site_description} -- one-line description of the website
    See plan.md D6 for rationale.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    template_path = os.path.join(script_dir, "skill-md.template")

    with open(template_path, encoding="utf-8") as f:
        template = f.read()

    skill_md = template.format(
        domain=domain,
        skill_name=skill_name,
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

    # Determine mode label for display
    if config.skip_scrape:
        mode = "skip-scrape (idempotent)"
    elif config.force_refresh:
        mode = "force-refresh"
    else:
        mode = "incremental update"

    print(f"Website-to-Skill Pipeline")
    print(f"  Input:       {config.url}")
    print(f"  Domain:      {config.domain}")
    print(f"  Skill Name:  {config.skill_name}")
    print(f"  Map URL:     {config.map_url}")
    print(f"  Output:      {config.output}")
    print(f"  Workspace:   {workspace_dir}")
    print(f"  Mode:        {mode}")

    os.makedirs(workspace_dir, exist_ok=True)
    os.makedirs(config.output, exist_ok=True)

    if config.skip_scrape:
        # ---------------------------------------------------------------
        # Idempotent mode: use cache, zero API calls
        # ---------------------------------------------------------------
        # Try state.json first (more granular), fall back to batch-response.json
        state = load_state(workspace_dir)

        if state.get("batches"):
            print(f"\nLoading cached data from state.json")
            pages: list[dict] = []
            for batch_state in state["batches"].values():
                if batch_state.get("status") == "completed":
                    pages.extend(batch_state.get("pages", []))
            print(f"  Loaded {len(pages)} pages from state cache")
        else:
            # Backward compatibility: load from batch-response.json
            cache_path = os.path.join(workspace_dir, "batch-response.json")
            if not os.path.exists(cache_path):
                print(f"\nERROR: No cached data at {cache_path}")
                print("Run without --skip-scrape first.")
                sys.exit(1)
            print(f"\nSkipping map+scrape, loading cached data from {cache_path}")
            with open(cache_path, encoding="utf-8") as f:
                scrape_data = json.load(f)
            pages = (
                scrape_data
                if isinstance(scrape_data, list)
                else scrape_data.get("data", [])
            )
            print(f"  Loaded {len(pages)} pages from batch-response.json")

        new_page_count = 0  # Nothing scraped in idempotent mode

    else:
        # ---------------------------------------------------------------
        # Active mode: map + scrape (incremental or force-refresh)
        # ---------------------------------------------------------------

        # Step 1: Map
        map_result = map_website(
            config.map_url,
            api_key,
            limit=config.limit,
            workspace_dir=workspace_dir,
            skip_scrape=False,
            force_refresh=config.force_refresh,
        )

        # Save map state
        state = load_state(workspace_dir)
        state["map"] = {
            "urls": map_result["urls"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": {"url": config.map_url, "limit": config.limit},
        }
        save_state(workspace_dir, state)

        # Step 2: Determine what to scrape
        if config.force_refresh:
            # Force refresh: scrape everything
            urls_to_scrape = map_result["urls"]
            existing_pages: list[dict] = []
            print(
                f"\n  Force refresh: will scrape all {len(urls_to_scrape)} URLs"
            )
        elif map_result["new_urls"]:
            # Incremental: only scrape new URLs, load existing from cache
            urls_to_scrape = map_result["new_urls"]
            existing_pages = load_existing_pages(
                map_result["unchanged_urls"], workspace_dir
            )
            print(
                f"\n  Incremental: scraping {len(urls_to_scrape)} new URLs "
                f"(reusing {len(existing_pages)} cached pages)"
            )
        elif map_result["unchanged_urls"] and not map_result["new_urls"]:
            # No new URLs -- load everything from cache
            urls_to_scrape = []
            existing_pages = load_existing_pages(
                map_result["unchanged_urls"], workspace_dir
            )
            print(
                f"\n  No new URLs -- reusing {len(existing_pages)} cached pages"
            )
        else:
            # First run with no cached URLs: scrape everything
            urls_to_scrape = map_result["urls"]
            existing_pages = []
            print(
                f"\n  First run: will scrape all {len(urls_to_scrape)} URLs"
            )

        # Step 2b: Batch scrape new URLs
        if urls_to_scrape:
            new_pages = batch_scrape(
                urls_to_scrape,
                api_key,
                workspace_dir,
                force_refresh=config.force_refresh,
            )
        else:
            new_pages = []
            print(f"\n  No URLs to scrape -- skipping batch step")

        pages = existing_pages + new_pages
        new_page_count = len(new_pages)

        # Save consolidated batch-response.json (backward compatibility)
        cache_path = os.path.join(workspace_dir, "batch-response.json")
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(pages, f, indent=2, ensure_ascii=False)
        print(f"  Cached scrape data to {cache_path}")

    # -------------------------------------------------------------------
    # Step 3: Assemble
    # -------------------------------------------------------------------
    print(f"\n{'='*60}")
    print(f"STEP 3: Assemble -- building skill folder")
    print(f"{'='*60}")

    pages_dir = os.path.join(config.output, "pages")
    page_count = assemble_pages(pages, pages_dir)
    print(f"  Wrote {page_count} page files to {pages_dir}/")

    generate_skill_md(
        config.output, config.domain, config.skill_name, config.description
    )
    print(f"  Wrote SKILL.md")

    # Summary
    print(f"\n{'='*60}")
    print(f"DONE")
    print(f"{'='*60}")
    print(f"  Skill folder: {config.output}/")
    print(f"  Pages:        {page_count}")
    print(f"  SKILL.md:     {os.path.join(config.output, 'SKILL.md')}")

    if config.skip_scrape:
        print(f"\n  Credits used: 0 (idempotent mode)")
    elif new_page_count == 0 and not config.force_refresh:
        print(f"\n  Credits used: 1 (map only, no new pages)")
    else:
        print(
            f"\n  Estimated cost: 1 (map) + {new_page_count} x 5 (scrape) "
            f"= {1 + new_page_count * 5} credits"
        )


if __name__ == "__main__":
    main()
