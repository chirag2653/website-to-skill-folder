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
    python pipeline.py https://csaok.com --max-pages 100  # limit skill folder to 100 pages

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

    The skill name is derived from domain as: {domain}-website-search-skill 
    (e.g. csaok-com-website-search-skill). The output folder uses the skill name.
    The workspace uses the domain as the key. The {domain} variable in 
    skill-md.template uses the domain.
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
from pathlib import Path
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
    - Output directory (output/{skill_name})
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
    limit: int = 100_000  # Max discovery (Firecrawl API max, effectively unlimited)
    max_pages: int | None = None  # Max pages to scrape (controls final skill folder size)
    skip_scrape: bool = False
    force_refresh: bool = False
    yes: bool = False  # Auto-approve cost prompt (skip interactive confirmation)

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
            # Output goes to the current working directory — wherever the user
            # or agent is running the script from, not inside the script itself.
            self.output = os.path.join(os.getcwd(), "output", self.skill_name)
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
            "  python pipeline.py docs.stripe.com --max-pages 100\n"
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
        help="Output directory (default: ./output/{skill_name})",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100_000,
        help="Max URLs to discover in map step (default: 100000, effectively unlimited)",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Max pages to scrape and include in skill folder (default: all discovered URLs). Controls final skill folder size. UI-exposable parameter.",
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
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Auto-approve cost prompt and proceed without asking (for scripts/agents)",
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
            max_pages=args.max_pages,
            skip_scrape=args.skip_scrape,
            force_refresh=args.force_refresh,
            yes=args.yes,
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
REQUEST_TIMEOUT = (10, 30)  # (connect_timeout, read_timeout) in seconds
DELETION_MISS_THRESHOLD = 3  # Consecutive map misses before deleting a page file
MAX_SLUG_LEN = 80         # Max slug length to avoid Windows MAX_PATH (260 char) crashes

# JSON extraction prompt -- tells Firecrawl's LLM what we want (see plan.md D3)
# Optimized for hybrid keyword (ripgrep) + semantic (agent reasoning) search
JSON_PROMPT = (
    "Extract structured metadata from this web page. This metadata will serve "
    "as frontmatter in a reference file that AI agents search through using "
    "ripgrep (literal keyword matching) to find relevant pages.\n\n"
    "IMPORTANT: Return ONLY plain text. Do NOT include any HTML tags, markdown "
    "syntax, or formatting codes in your extracted values. Convert HTML tags "
    "like <br> to spaces or newlines as appropriate.\n\n"
    "The summary field is critical for search quality. It must:\n"
    "1. Describe WHAT INFORMATION IS ON THIS PAGE (content manifest, not recap)\n"
    "2. Be keyword-rich with multiple term variations for ripgrep matching\n"
    "3. Include synonyms, formal/informal terms, and related concepts\n"
    "4. Mention specific searchable terms users might use\n\n"
    "For example, if a page covers 'pricing', the summary should mention "
    "'pricing', 'price', 'cost', 'fees', 'rates', 'how much', 'payment' "
    "so searches for any of these terms will match.\n\n"
    "If a page covers 'rhinoplasty', mention both 'rhinoplasty' and 'nose job'. "
    "If a page covers 'contact', mention 'contact', 'reach', 'phone', 'email', "
    "'address', 'get in touch', 'location'.\n\n"
    "Use 3-5 sentences. Be specific about topics, data points, and unique "
    "content. An AI agent reading only the summary should be able to decide "
    "whether this page is relevant to their search query."
)

JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {
            "type": "string",
            "description": "The page title, clean and concise (without the site name suffix). Plain text only - no HTML tags or markdown.",
        },
        "description": {
            "type": "string",
            "description": "A concise 1-2 sentence description of what this page is. Plain text only - no HTML tags or markdown.",
        },
        "summary": {
            "type": "string",
            "description": (
                "A 3-5 sentence content manifest optimized for keyword search. "
                "Describe what information this page contains, using multiple "
                "term variations (synonyms, formal/informal, related concepts) "
                "so ripgrep searches will match. For example, mention 'pricing' "
                "AND 'cost' AND 'fees', 'contact' AND 'phone' AND 'email', "
                "'procedure' AND 'treatment' AND 'service'. Include specific "
                "topics, data points, and unique content. This enables both "
                "keyword matching (ripgrep) and semantic understanding (agent reasoning). "
                "Plain text only - no HTML tags or markdown syntax."
            ),
        },
    },
    "required": ["title", "description", "summary"],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------



def get_api_key() -> str:
    """Read Firecrawl API key with multi-source fallback.
    
    Priority order:
    1. FIRECRAWL_API_KEY environment variable
    2. .env.local file in project root
    3. Firecrawl CLI credentials file (for compatibility)
    
    Returns:
        API key string
        
    Raises:
        SystemExit if no key found
    """
    # Priority 1: Environment variable
    api_key = os.environ.get("FIRECRAWL_API_KEY")
    if api_key and api_key.strip():
        return api_key.strip()
    
    # Priority 2: .env.local file in project root
    script_dir = Path(__file__).parent
    env_local_path = script_dir / ".env.local"
    if env_local_path.exists():
        try:
            with open(env_local_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        if "=" in line:
                            key, value = line.split("=", 1)
                            key = key.strip()
                            value = value.strip().strip('"').strip("'")
                            if key == "FIRECRAWL_API_KEY" and value:
                                return value
        except (OSError, ValueError) as e:
            logger.warning(f"Could not read .env.local: {e}")
    
    # Priority 3: Firecrawl CLI credentials file (fallback for compatibility)
    if os.path.exists(CREDS_PATH):
        try:
            with open(CREDS_PATH, encoding="utf-8") as f:
                creds = json.load(f)
            key = creds.get("apiKey") or creds.get("api_key") or creds.get("key")
            if key and key.strip():
                return key.strip()
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(f"Could not read CLI credentials: {e}")
    
    # No key found
    print("ERROR: Firecrawl API key not found.")
    print("\nPlease provide the API key using one of these methods:")
    print("  1. Set environment variable: FIRECRAWL_API_KEY=your_key")
    print(f"  2. Create .env.local file with: FIRECRAWL_API_KEY=your_key")
    print(f"  3. Run `firecrawl login` (stores key at {CREDS_PATH})")
    sys.exit(1)


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
    """Convert a URL path to a filesystem-safe slug (see plan.md D9).

    Truncates to MAX_SLUG_LEN chars and appends an 8-char URL hash to
    prevent Windows MAX_PATH (260 char) crashes on long blog/doc URLs.
    Truncated slugs remain unique because the hash is derived from the
    full original URL.
    """
    path = urlparse(url.rstrip("/")).path.strip("/")
    if not path:
        return "index"
    slug = path.replace("/", "--")
    slug = re.sub(r"[^a-z0-9\-]", "", slug.lower())
    if len(slug) > MAX_SLUG_LEN:
        url_hash = hashlib.sha256(url.encode()).hexdigest()[:8]
        slug = slug[:MAX_SLUG_LEN] + "-" + url_hash
    return slug


def yaml_escape(s: str) -> str:
    """Escape a string for YAML double-quoted scalar."""
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def strip_html_tags(text: str) -> str:
    """Remove HTML tags from text, converting <br> tags to spaces.
    
    LLM JSON extraction may include HTML tags from source content.
    This cleans them up for clean markdown frontmatter.
    """
    if not text:
        return text
    
    # Convert <br> and <br/> to spaces (preserve word boundaries)
    text = re.sub(r'<br\s*/?>', ' ', text, flags=re.IGNORECASE)
    
    # Remove all other HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    
    # Clean up multiple spaces
    text = re.sub(r'\s+', ' ', text)
    
    return text.strip()


def clean_markdown(md: str) -> str:
    """Minimal cleanup - strips leading empty lines and obvious technical artifacts.
    
    Relies on Firecrawl's onlyMainContent and excludeTags for content quality.
    Only removes obvious technical artifacts (icon class names, SVG references)
    that are clearly not content. Let the AI agent use judgment for navigation
    elements (see SKILL.md guidance).
    """
    lines = md.split("\n")
    cleaned_lines = []
    
    for line in lines:
        stripped = line.strip()
        
        # Skip empty lines at the start
        if not stripped and not cleaned_lines:
            continue
        
        # Skip obvious technical artifacts: long concatenated class names (icon fonts, SVG classes)
        # Pattern: Multiple words connected by dashes/underscores, no spaces, very long
        # This catches things like "Book-Open-1--Streamline-UltimatesvgCheck-Circle..."
        if (
            len(stripped) > 100 
            and not " " in stripped 
            and (stripped.count("-") > 10 or stripped.count("_") > 10)
            and any(char.isupper() for char in stripped)  # Has capital letters (class name pattern)
        ):
            continue
        
        cleaned_lines.append(line)
    
    result = "\n".join(cleaned_lines)
    
    # Remove leading/trailing whitespace
    return result.strip()


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


def update_deletion_candidates(
    state: dict,
    deleted_urls: list[str],
    active_urls: list[str],
) -> list[str]:
    """Track map misses per URL and return URLs ready for deletion.

    A URL must be absent from DELETION_MISS_THRESHOLD consecutive map runs
    before its page file is actually deleted. This prevents data loss from
    transient crawl failures, Firecrawl rate limiting, or temporary sitemap
    omissions.

    Logic:
    - URLs in active_urls that were candidates: clear their miss count (returned)
    - URLs in deleted_urls: increment their miss count
    - URLs hitting threshold: returned for deletion, removed from candidates

    Mutates state["deletion_candidates"] in place.

    Returns:
        List of URLs confirmed absent for DELETION_MISS_THRESHOLD runs.
    """
    if "deletion_candidates" not in state:
        state["deletion_candidates"] = {}

    candidates = state["deletion_candidates"]
    active_set = set(active_urls)
    now = datetime.now(timezone.utc).isoformat()

    # Clear candidates that returned to the map (transient miss, URL is back)
    for url in list(candidates.keys()):
        if url in active_set:
            del candidates[url]

    # Increment miss counts for currently-absent URLs
    for url in deleted_urls:
        if url in candidates:
            candidates[url]["consecutive_misses"] += 1
            candidates[url]["last_missing_at"] = now
        else:
            candidates[url] = {
                "consecutive_misses": 1,
                "first_missing_at": now,
                "last_missing_at": now,
            }

    # Collect URLs that have hit the deletion threshold
    urls_to_delete = [
        url
        for url, data in candidates.items()
        if data["consecutive_misses"] >= DELETION_MISS_THRESHOLD
    ]

    # Remove threshold-hit URLs from candidates (their files will be deleted)
    for url in urls_to_delete:
        del candidates[url]

    return urls_to_delete


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
def _map_website_api_call(
    map_url: str, api_key: str, limit: int, ignore_cache: bool = False
) -> list[str]:
    """Make the Map API call with automatic retries.

    Retries on transient failures (network, rate limit, server errors).
    Raises immediately on permanent failures (400, 401, 403, 404).

    ignore_cache: pass True on --force-refresh so Firecrawl bypasses its
    own cached sitemap data and returns a genuinely fresh URL list.
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
        "ignoreCache": ignore_cache,
    }

    resp = requests.post(
        f"{FIRECRAWL_BASE}/v1/map", headers=headers, json=payload,
        timeout=REQUEST_TIMEOUT,
    )
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
        new_urls = _map_website_api_call(map_url, api_key, limit, ignore_cache=True)
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
        "excludeTags": [
            "nav",
            "aside",
            "header",
            "footer",
            "sidebar",
            "menu",
            "navigation",
            "filter",
            "widget",
            "widget-area",
            "sidebar-widget",
        ],
        "removeBase64Images": True,
        "blockAds": True,
    }

    resp = requests.post(
        f"{FIRECRAWL_BASE}/v2/batch/scrape", headers=headers, json=payload,
        timeout=REQUEST_TIMEOUT,
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
        f"{FIRECRAWL_BASE}/v2/batch/scrape/{batch_id}", headers=headers,
        timeout=REQUEST_TIMEOUT,
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

    resp = requests.get(next_url, headers=headers, timeout=REQUEST_TIMEOUT)
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
        # Prioritize SEO meta tags over LLM extraction (SEO team's work is authoritative)
        title = metadata.get("title") or json_data.get("title", "Untitled")
        description = metadata.get("description") or metadata.get("ogDescription") or json_data.get("description", "")
        summary = json_data.get("summary", "")
        
        # Clean HTML tags from LLM-extracted fields (may contain <br> tags from source HTML)
        if not metadata.get("title"):  # Only clean if from LLM extraction
            title = strip_html_tags(title)
        if not metadata.get("description") and not metadata.get("ogDescription"):  # Only clean if from LLM extraction
            description = strip_html_tags(description)
        summary = strip_html_tags(summary)  # Summary is always LLM-extracted

        slug = url_to_slug(source_url)
        filepath = os.path.join(pages_dir, f"{slug}.md")

        # Convert <br> tags to newlines in markdown (Firecrawl may preserve some HTML)
        markdown = re.sub(r'<br\s*/?>', '\n', markdown, flags=re.IGNORECASE)
        
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


def extract_site_description(
    pages: list[dict],
    domain: str,
    manual_description: str | None = None,
) -> str:
    """Extract site description with multi-tier fallback.
    
    Priority order:
    1. Manual override (if provided)
    2. Homepage metadata (json.description, metadata.description, ogDescription)
    3. Infer from page titles (simple pattern matching)
    4. Generic fallback
    
    Args:
        pages: List of scraped page dictionaries
        domain: Website domain
        manual_description: Optional manual description override
        
    Returns:
        Site description string
    """
    # Tier 1: Manual override (highest priority)
    if manual_description and manual_description.strip():
        return manual_description.strip()
    
    # Tier 2: Extract from homepage metadata
    homepage_url = f"https://{domain}"
    homepage_url_alt = f"http://{domain}"
    
    homepage = None
    for page in pages:
        metadata = page.get("metadata", {})
        source_url = (
            metadata.get("ogUrl", "") or metadata.get("sourceURL", "")
        ).rstrip("/")
        
        if source_url in (homepage_url.rstrip("/"), homepage_url_alt.rstrip("/")):
            homepage = page
            break
    
    if homepage:
        json_data = homepage.get("json", {})
        metadata = homepage.get("metadata", {})
        
        # Priority: json.description > condensed json.summary > metadata.description > ogDescription
        # json.description is LLM-extracted 1-2 sentences (already perfect length)
        if json_data.get("description"):
            desc = json_data["description"].strip()
            if desc and len(desc) > 20:  # Minimum length check
                return desc
        
        # json.summary is LLM-extracted 3-5 sentences (very rich, condense to 1-2 sentences)
        # Note: Summary describes PAGE CONTENT, not business identity, but contains business info
        if json_data.get("summary"):
            summary = json_data["summary"].strip()
            if summary and len(summary) > 50:
                # Extract business identity from summary (remove page-focused language)
                sentences = [s.strip() for s in summary.split(". ") if s.strip()]
                
                # Filter out page-structure sentences, keep business-focused ones
                business_sentences = []
                for sentence in sentences:
                    # Skip sentences about page structure/navigation
                    if any(phrase in sentence.lower() for phrase in [
                        "this page", "the page", "additional resources", "includes links",
                        "provides links", "contains links", "links to", "page also"
                    ]):
                        continue
                    business_sentences.append(sentence)
                
                # If no business sentences after filtering, use original sentences
                if not business_sentences:
                    business_sentences = sentences
                
                # Build condensed description from complete sentences (max 250 chars)
                condensed_parts = []
                current_length = 0
                max_length = 250
                
                for sentence in business_sentences[:3]:  # Max 3 sentences
                    # Add period if not last sentence
                    sentence_with_period = sentence + "."
                    potential_length = current_length + len(sentence_with_period)
                    if len(condensed_parts) > 0:
                        potential_length += 1  # +1 for space between sentences
                    
                    if potential_length <= max_length:
                        condensed_parts.append(sentence_with_period)
                        current_length = potential_length
                    else:
                        break
                
                if condensed_parts:
                    condensed = " ".join(condensed_parts)
                    # Ensure we don't exceed limit (safety check)
                    if len(condensed) > max_length:
                        # Truncate at last complete sentence
                        if len(condensed_parts) > 1:
                            condensed = " ".join(condensed_parts[:-1])
                        else:
                            # Single sentence too long - truncate at word boundary
                            words = condensed_parts[0].split()
                            truncated = []
                            for word in words:
                                if len(" ".join(truncated + [word])) <= max_length - 3:
                                    truncated.append(word)
                                else:
                                    break
                            condensed = " ".join(truncated) + "..."
                    return condensed
        
        if metadata.get("description"):
            desc = metadata["description"].strip()
            if desc and len(desc) > 20:
                return desc
        
        if metadata.get("ogDescription"):
            desc = metadata["ogDescription"].strip()
            if desc and len(desc) > 20:
                return desc
    
    # Tier 3: Infer from page titles
    titles = []
    for page in pages[:20]:  # First 20 pages
        json_data = page.get("json", {})
        metadata = page.get("metadata", {})
        title = json_data.get("title") or metadata.get("title", "")
        if title:
            titles.append(title.lower())
    
    # Simple pattern matching
    all_titles = " ".join(titles)
    
    if any(term in all_titles for term in ["api", "reference", "documentation", "docs", "guide"]):
        return "API documentation and developer resources"
    
    if any(term in all_titles for term in ["service", "treatment", "procedure", "services"]):
        return "Service-based business"
    
    if any(term in all_titles for term in ["doctor", "surgeon", "clinic", "medical", "healthcare", "patient"]):
        return "Medical practice or healthcare provider"
    
    if any(term in all_titles for term in ["product", "feature", "saas", "platform", "software"]):
        return "Product or SaaS platform"
    
    if any(term in all_titles for term in ["portfolio", "work", "projects", "agency", "design"]):
        return "Creative agency or service provider"
    
    # Tier 4: Generic fallback
    return f"a website at {domain}"


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
# Cost approval
# ---------------------------------------------------------------------------


def prompt_cost_approval(
    urls_to_scrape: list[str],
    output_dir: str,
    auto_approve: bool,
    max_pages: int | None = None,
) -> bool:
    """Show estimated Firecrawl credit cost and ask user to approve.

    Called after the map step (1 credit already spent) and before the
    expensive batch scrape step.  Returns True if approved, False if
    the user declines.

    Cost model:
      - Map:   1 credit (already spent by this point)
      - Scrape: ~5 credits per page
    """
    scrape_count = len(urls_to_scrape)
    scrape_cost = scrape_count * 5
    total_cost = 1 + scrape_cost

    # Detect new vs update by checking for existing SKILL.md
    skill_md_path = os.path.join(output_dir, "SKILL.md")
    is_update = os.path.exists(skill_md_path)
    action = "Update existing" if is_update else "Create new"

    print(f"\n{'='*60}")
    print(f"COST ESTIMATE")
    print(f"{'='*60}")
    print(f"  Action:           {action} skill folder")
    print(f"  Pages to scrape:  {scrape_count}")
    if max_pages:
        print(f"  Max pages limit:  {max_pages}")
    print(f"")
    print(f"  Credits already used:  1  (map)")
    print(f"  Credits remaining:     ~{scrape_cost}  ({scrape_count} pages x 5 credits)")
    print(f"  Total estimated cost:  ~{total_cost} credits")
    print(f"{'='*60}")

    if auto_approve:
        print(f"  Auto-approved (--yes flag)")
        return True

    try:
        answer = input(f"\n  Proceed with scraping? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        # Non-interactive stdin or Ctrl+C
        print("")
        return False

    return answer in ("y", "yes")


def print_cancelled_message(output_dir: str, domain: str) -> None:
    """Print a descriptive message when the user declines the cost approval."""
    print(f"\n{'='*60}")
    print(f"PIPELINE CANCELLED")
    print(f"{'='*60}")
    print(f"  What happened:")
    print(f"    - The map step completed (1 credit used)")
    print(f"    - Discovered URLs are cached in _workspace/{domain}/")
    print(f"    - No pages were scraped (no additional credits used)")
    print(f"")
    print(f"  What was NOT done:")
    print(f"    - Pages were not scraped")
    print(f"    - Skill folder was not created/updated at {output_dir}/")
    print(f"")
    print(f"  To proceed later:")
    print(f"    - Re-run the same command and approve when prompted")
    print(f"    - Use --yes to skip the approval prompt")
    print(f"    - Use --max-pages N to limit scope and reduce cost")
    print(f"{'='*60}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    config = parse_args()

    workspace_dir = os.path.join(os.getcwd(), "_workspace", config.domain)

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

    urls_to_delete: list[str] = []  # URLs confirmed absent enough times to delete

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

        # Save map state + update deletion candidates in one write
        state = load_state(workspace_dir)
        state["map"] = {
            "urls": map_result["urls"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": {"url": config.map_url, "limit": config.limit},
        }
        urls_to_delete = update_deletion_candidates(
            state,
            map_result["deleted_urls"],
            map_result["urls"],
        )
        save_state(workspace_dir, state)

        # Log deletion candidate status
        pending = state.get("deletion_candidates", {})
        if pending:
            print(f"\n  {len(pending)} URL(s) absent from map (not yet deleted):")
            for url, data in list(pending.items())[:5]:
                remaining = DELETION_MISS_THRESHOLD - data["consecutive_misses"]
                print(f"    [{data['consecutive_misses']}/{DELETION_MISS_THRESHOLD} misses] {url}")
            if len(pending) > 5:
                print(f"    ... and {len(pending) - 5} more")
            print(f"    (will delete after {DELETION_MISS_THRESHOLD} consecutive misses)")
        if urls_to_delete:
            print(f"\n  {len(urls_to_delete)} URL(s) confirmed absent for {DELETION_MISS_THRESHOLD}+ runs -- will delete page files")

        # Delete orphaned page files immediately (before approval gate,
        # since update_deletion_candidates already removed them from state)
        if urls_to_delete:
            pages_dir = os.path.join(config.output, "pages")
            deleted_file_count = 0
            for url in urls_to_delete:
                slug = url_to_slug(url)
                filepath = os.path.join(pages_dir, f"{slug}.md")
                if os.path.exists(filepath):
                    os.remove(filepath)
                    deleted_file_count += 1
                    logger.info(f"Deleted orphaned page: {url}")
            if deleted_file_count:
                print(f"  Deleted {deleted_file_count} orphaned page file(s)")

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

        # Apply max_pages limit if set (controls final skill folder size)
        if config.max_pages and len(urls_to_scrape) > config.max_pages:
            original_count = len(urls_to_scrape)
            urls_to_scrape = urls_to_scrape[:config.max_pages]
            print(
                f"\n  Max pages limit: limiting to first {config.max_pages} pages "
                f"(discovered {original_count} URLs, will scrape {len(urls_to_scrape)} pages)"
            )

        # Cost approval gate: ask before the expensive scrape step
        if urls_to_scrape:
            approved = prompt_cost_approval(
                urls_to_scrape,
                config.output,
                auto_approve=config.yes,
                max_pages=config.max_pages,
            )
            if not approved:
                print_cancelled_message(config.output, config.domain)
                sys.exit(0)

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

    # Extract site description with auto-extraction fallback
    site_description = extract_site_description(
        pages,
        config.domain,
        config.description if config.description else None,
    )
    print(f"  Site description: {site_description}")

    generate_skill_md(
        config.output, config.domain, config.skill_name, site_description
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
        print(f"\n  Credits used: ~1 (map only, no new pages)")
    else:
        print(
            f"\n  Credits used: ~{1 + new_page_count * 5} "
            f"(1 map + {new_page_count} pages x 5 scrape)"
        )

    # Install commands
    # npx skills copies output/ into ~/.agents/skills/ on install.
    # Re-run this command after every pipeline update to refresh the installed skill.
    abs_output = os.path.abspath(config.output)
    print(f"\n  Install / update skill in agents:")
    print(f"    (run this after every pipeline rerun to refresh installed skill)")
    print(f"")
    print(f"    Claude Code:")
    print(f'    npx skills add "{abs_output}" -g -y -a claude-code')
    print(f"")
    print(f"    All agents:")
    print(f'    npx skills add "{abs_output}" -g -y')
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
