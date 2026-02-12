# Website-to-Skill Folder Pipeline

## Goal

A Python script that takes any website URL and produces a **website search
skill** — a folder where an AI agent can search a website's content without
loading all pages into context.

```
plan.md          → WHY: design decisions and rationale
                      ↓ informs
pipeline.py      → HOW: code that implements those decisions
                      ↓ produces
skill folder     → WHAT: clean artifact the agent uses (sample-skill-folder/)
```

---

## Development Approach — Output First, Pipeline Second

We work backwards: perfect the template skill folder by hand, test it with
real agents, then build pipeline.py to reproduce that output automatically.

### Phase 1: Perfect the template (current)

The 10-page test skill folder (`sample-skill-folder/`) is the live prototype.
Iterate directly on the output files — no pipeline, no credits burned.

1. Hand-edit SKILL.md — refine the search protocol, fix agent friction
2. Test with real agents — collect feedback on what's clunky or missing
3. Refine page frontmatter — tune summary quality, test relevance judgment
4. Refine markdown cleanup — strip trailing CTA/popup junk

The template folder is both the prototype and the spec.

### Phase 2: Build pipeline.py to match the template

1. Diff the template against what pipeline.py currently generates
2. Update pipeline.py — SKILL.md template, JSON extraction prompt,
   assembly logic, markdown cleanup — until output matches template exactly
3. Run on all 247 csaok.com pages
4. Validate at scale

### Phase 3: Package

1. Package as a reusable skill in `personal-ai-agent-toolkit`
2. Test on a second website (different industry) to confirm generality

---

## Design Decisions

Every decision here informs pipeline.py. When we change a decision, we
update pipeline.py to match.

### D1: Skill folder structure

```
{skill-name}/
├── SKILL.md          # The only file the agent loads on activation
└── pages/            # One .md per page (frontmatter + markdown body)
    ├── index.md
    ├── services--rhinoplasty-in-oklahoma-city.md
    └── ...
```

**Why this structure**: SKILL.md is lightweight (~130 lines) and teaches the
agent how to search. Pages are never bulk-loaded — the agent searches them
with ripgrep and only loads the ones it needs. This keeps context clean
regardless of how many pages the website has.

**Why no manifest.yaml**: We tried a separate manifest file listing all page
metadata. Rejected because: (a) the agent would have to load it for every
search, adding context overhead, and (b) ripgrep already searches frontmatter
directly in the page files, making a manifest redundant.

### D2: Four frontmatter fields — title, description, url, summary

```yaml
---
title: "Rhinoplasty in Oklahoma City"
description: "Detailed overview of rhinoplasty procedures..."
url: "https://csaok.com/services/rhinoplasty-in-oklahoma-city/"
summary: |
  This page provides comprehensive information about rhinoplasty...
---
```

**Why these four and nothing else**:

- **title**: Primary search surface. Agent discovers the site's vocabulary
  by running `rg "^title:" $PAGES`. Clean title without the site name suffix
  (e.g. "Rhinoplasty in Oklahoma City" not "Rhinoplasty | CSA OKC").
- **description**: 1-2 sentence page identity. Gives quick context when
  screening candidates.
- **url**: Source URL. Agent can reference or link back to the live page.
  Free — comes from HTML metadata, no LLM cost.
- **summary**: The critical field. 3-5 sentence "content manifest" — tells
  the agent what information they'd find if they loaded the full page.
  This is what makes frontmatter screening work for broad queries.

**Why not category/tags/page_type**: We tried adding `page_type` (service,
blog, team, etc.) and `topics` (array of keywords). Removed because:
(a) these are redundant with the summary — a good summary already contains
the keywords an agent would search for, and (b) fewer fields = less noise
in frontmatter = faster screening with `head -n 12`.

### D3: Summary as "content manifest" (not content recap)

The summary describes **what information is on the page**, not the
information itself. Think card catalog, not book report.

**Good summary** (content manifest):
> This page provides information about rhinoplasty procedures including
> duration, anesthesia options, downtime, consultation process, before-and-
> after photos, pre/post-care instructions, FAQs about insurance coverage
> and combining procedures, and links to revision and ethnic rhinoplasty.

**Bad summary** (content recap):
> Rhinoplasty reshapes the nose by removing or adding cartilage. The
> procedure takes 1-4 hours under IV sedation or general anesthesia.
> Recovery takes 2-4 days.

**Why this matters**: The agent's job is to decide "should I load this page?"
not "what does this page say?" A content manifest answers the relevance
question. A recap wastes the summary on information the agent will get
anyway if it loads the page.

**How pipeline.py produces this**: The JSON extraction prompt explicitly
instructs: "Describe WHAT INFORMATION IS ON THIS PAGE, like a card catalog
entry. Do not repeat the page content. Instead, tell the reader what they
would find if they loaded the full page."

### D4: Keyword expansion makes ripgrep semantic

Ripgrep is literal string matching. The agent is an LLM. The bridge:
before searching, the agent expands queries into synonyms, formal/informal
terms, and related concepts, then searches with regex OR patterns.

```
Query: "nose job recovery"
  → Agent expands: "rhinoplasty|nose surgery|septoplasty"
    AND "recovery|downtime|aftercare|healing"
  → rg -l "rhinoplasty|septoplasty" $PAGES
  → rg -l "recovery|downtime|aftercare" $PAGES
```

**Why this works**: The LLM is the semantic layer. It knows that "nose job"
= "rhinoplasty" and "recovery" ≈ "downtime" ≈ "aftercare". Ripgrep
just does the filesystem search. Combined, you get semantic search without
embeddings, vector DBs, or infrastructure.

**How pipeline.py produces this**: SKILL.md template includes Step 1 with
explicit expansion instructions and thinking patterns:
- Informal → add formal/technical term
- Technical → add common/colloquial term
- Specific → add related subtopics and broader categories

**Why not hardcode a vocabulary in SKILL.md**: We considered listing
service names, doctor names, and brands in SKILL.md to help with expansion.
Rejected because: (a) it makes SKILL.md stale when pages change, and
(b) the agent can discover the vocabulary dynamically via
`rg "^title:" $PAGES`. The pages folder is the source of truth.

### D5: Path resolution — $PAGES convention

The agent's working directory is NOT the skill folder. Bare `pages/` paths
fail. SKILL.md instructs the agent to resolve the absolute path from the
SKILL.md location before running any commands.

**How it was discovered**: A real agent tested the skill and stumbled through
failed searches because `pages/` didn't exist relative to its workspace root.

**Convention**: All command examples in SKILL.md use `$PAGES` as a
placeholder. The agent substitutes the resolved absolute path.

### D6: SKILL.md is lean and generic — only 4 template variables

SKILL.md contains no hardcoded website content (no service lists, doctor
names, brand names). Only four things change per website:

| Variable | Example | Source |
|----------|---------|--------|
| `{skill_name}` | `csaok-website` | Derived from domain |
| `{domain}` | `csaok.com` | From input URL |
| `{site_description}` | `Cosmetic Surgery Affiliates, a cosmetic surgery and med spa practice...` | User-provided or auto-generated |
| (frontmatter `name` + `description`) | | For skill discovery |

Everything else — the search protocol, keyword expansion instructions,
discovery commands, tips — is identical across all website skills.

**Why lean**: When pages are added, removed, or updated, SKILL.md doesn't
need to change. The agent discovers the site's vocabulary through the pages
themselves. This makes the skill maintainable and the pipeline simpler.

### D7: Frontmatter screening for scale

For narrow queries (2-5 results), the agent loads candidates directly.
For broad queries (10+ results), the agent reads frontmatter first:

```bash
rg -l "term" $PAGES | xargs head -n 12
```

This shows title + description + summary (~12 lines) per candidate without
loading the full page content. The agent reads summaries, picks relevant
pages, then loads only those.

**Why 12 lines**: The YAML frontmatter block (---, 4 fields, ---) plus a
blank line fits in ~12 lines. `head -n 12` captures exactly the metadata.

### D8: Markdown cleanup rules

Raw scraped HTML→markdown contains junk: navigation remnants, CTA buttons,
exit-intent popups, SVG icon text, cookie notices. The assembly step cleans
markdown before writing page files.

**Current rules** (to be expanded):
- Strip leading junk: skip lines until first heading (`#`) or substantial
  paragraph (>80 chars with spaces)
- Skip known patterns: `[Back...`, `Consult Now`, `Filter`

**Known gaps**:
- Trailing CTA/popup content not yet stripped (e.g. "Wait! You can begin
  your journey..." exit-intent popups)
- Image-heavy sections could be collapsed

### D9: Slug generation

URL path → filesystem-safe filename:
- `/` → `index`
- `/about` → `about`
- `/services/botox-in-oklahoma-city` → `services--botox-in-oklahoma-city`

`/` in paths becomes `--` to preserve hierarchy info in flat filenames.
All non-alphanumeric-or-hyphen characters stripped. Lowercased.

---

## Pipeline Steps (for pipeline.py)

### Step 1: Map — discover all URLs

**Endpoint**: `POST https://api.firecrawl.dev/v1/map`

```json
{
  "url": "https://example.com",
  "includeSubdomains": false,
  "ignoreQueryParameters": true,
  "limit": 5000
}
```

Returns a clean, deduplicated URL list. No filtering needed.
**Cost**: 1 credit.

### Step 2: Batch Scrape — get markdown + structured metadata

**Endpoint**: `POST https://api.firecrawl.dev/v2/batch/scrape`

The `formats` array requests both markdown and JSON extraction in one call.
JSON extraction uses an inline format object (NOT a top-level `jsonOptions`
key — that was a failed attempt that returned 400).

```json
{
  "urls": ["..."],
  "formats": [
    "markdown",
    {
      "type": "json",
      "prompt": "<the extraction prompt — see D3 for rationale>",
      "schema": {
        "type": "object",
        "properties": {
          "title": { "type": "string", "description": "..." },
          "description": { "type": "string", "description": "..." },
          "summary": { "type": "string", "description": "..." }
        },
        "required": ["title", "description", "summary"]
      }
    }
  ],
  "onlyMainContent": true
}
```

**Polling**: `GET /v2/batch/scrape/{id}` every 5s. Follow `next` URL if
response is paginated (>10MB).

**Field sources**:

| Field | Source | Cost |
|-------|--------|------|
| `title` | `json.title` | LLM (included in JSON extraction) |
| `description` | `json.description` | LLM (included in JSON extraction) |
| `url` | `metadata.ogUrl` or `metadata.sourceURL` | Free (HTML metadata) |
| `summary` | `json.summary` | LLM (included in JSON extraction) |

**Cost**: 5 credits per page (1 markdown + 4 JSON extraction).

### Step 3: Assemble — build the skill folder

No API calls. Local file generation:

1. For each page: create `pages/{slug}.md` with YAML frontmatter + cleaned
   markdown body (see D2, D3, D8, D9)
2. Generate SKILL.md from template (see D4, D5, D6)

---

## Cost per website

| Step | Credits | Formula |
|------|---------|---------|
| Map | 1 | Fixed |
| Batch scrape | N × 5 | N = number of pages |
| **Total** | **1 + 5N** | |

---

## Test Run: csaok.com

- **Map**: 247 URLs, 0 duplicates
- **Test batch** (10 pages): 50 credits, ~50 seconds
- **JSON extraction quality**: Good — titles clean, summaries are
  keyword-rich content manifests
- **Ripgrep search test**: Narrow queries return 2-4 files. Broad queries
  return most files — frontmatter screening handles this.
- **Agent test**: Real agent used the skill successfully. Found the $PAGES
  path resolution issue (D5), now fixed.

---

## Open Issues

- [ ] **Markdown cleanup**: trailing CTA/popup content still in pages (D8)
- [ ] **Summary prompt tuning**: need more agent testing to validate
  summaries help agents pick the right pages (D3)
- [ ] **Agent tool compatibility**: SKILL.md assumes bash (`rg` + `head` +
  `xargs`). Some agents use dedicated Read/Grep tools. Should the protocol
  accommodate both? (D5)
- [ ] **Scale validation**: does the skill work as well with 247 pages
  as with 10? Frontmatter screening (D7) becomes critical.
