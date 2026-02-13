# Website-to-Skill Folder Pipeline

## Goal

A Python script that takes any website URL and produces a **website search
skill** — a folder where an AI agent can search a website's content without
loading all pages into context.

---

## Project Structure

```
website-to-skill-folder/
├── skill-md.template          # SKILL.md template — single source of truth
├── pipeline.py                # Reads template, scrapes site, assembles folder
├── plan.md                    # Design decisions with rationale (this file)
├── sample-skill-folder/       # Reference output — regenerated, not hand-edited
│   ├── SKILL.md               # Rendered from skill-md.template
│   └── pages/                 # 10 test pages from csaok.com
└── _workspace/                # Cached API responses (gitignored)
    └── csaok.com/
        ├── 1-map.txt
        └── batch-response.json
```

### What each file does

| File | Role | When to edit |
|------|------|-------------|
| `skill-md.template` | SKILL.md content with `{domain}` and `{site_description}` placeholders | When changing what agents see (search protocol, tips, wording) |
| `pipeline.py` | Map → Batch Scrape → Assemble pipeline | When changing page format, frontmatter, cleanup, or API logic |
| `plan.md` | Design decisions (D1–D9) with rationale | When a decision changes (not for wording tweaks) |
| `sample-skill-folder/` | Rendered reference output | Never edit directly — regenerate with pipeline.py |

### Iteration workflow

```
1. Edit skill-md.template (or pipeline.py for page format changes)
2. Regenerate:  python pipeline.py https://csaok.com \
                  --description "Cosmetic Surgery Affiliates, ..." \
                  --output sample-skill-folder --skip-scrape
3. Test sample-skill-folder/ with real agents
4. Repeat until agents use it smoothly
5. If a design decision changed, update plan.md
```

One file to edit → one command to regenerate → test → repeat.

---

## Phases

**Phase 1 (current):** Iterate on the sample skill folder until agents use it
smoothly. Zero credits burned — uses cached 10-page scrape data.

**Phase 2:** Run pipeline on all 247 csaok.com pages. Validate at scale.

**Phase 3:** Package as reusable skill in `personal-ai-agent-toolkit`.
Test on a second website (different industry) to confirm generality.

---

## Design Decisions

Every decision here informs pipeline.py. When we change a decision, we
update pipeline.py to match.

### D1: Skill folder structure

```
{domain}/
├── SKILL.md          # The only file the agent loads on activation
└── pages/            # One .md per page (frontmatter + markdown body)
```

**Why:** SKILL.md is ~130 lines — lightweight. Pages are never bulk-loaded.
The agent searches them with ripgrep and loads only what it needs. Context
stays clean regardless of website size.

**Rejected: manifest.yaml.** We tried a separate file listing all page
metadata. Cut it — the agent would load it every search (context overhead),
and ripgrep already searches frontmatter directly in page files.

### D2: Four frontmatter fields

```yaml
---
title: "Rhinoplasty in Oklahoma City"
description: "Detailed overview of rhinoplasty procedures..."
url: "https://csaok.com/services/rhinoplasty-in-oklahoma-city/"
summary: |
  This page provides comprehensive information about rhinoplasty...
---
```

- **title** — primary search surface. Clean, no site name suffix.
- **description** — 1-2 sentence identity for quick screening.
- **url** — source link. Free (HTML metadata, no LLM cost).
- **summary** — 3-5 sentence "content manifest." The critical field (see D3).

**Rejected: category, tags, page_type.** Redundant with summary. A good
summary already contains the keywords. Fewer fields = less noise in
frontmatter = faster screening with `head -n 12`.

### D3: Summary = content manifest, not content recap

The summary describes **what information is on the page**, not the
information itself. Card catalog, not book report.

**Good** (content manifest):
> This page covers rhinoplasty procedures including duration, anesthesia
> options, downtime, before-and-after photos, pre/post-care instructions,
> FAQs about insurance and combining procedures.

**Bad** (content recap):
> Rhinoplasty reshapes the nose by removing or adding cartilage. The
> procedure takes 1-4 hours under IV sedation or general anesthesia.

**Why:** The agent decides "should I load this page?" — not "what does it
say?" A manifest answers the relevance question. A recap wastes summary
space on info the agent gets anyway when it loads the page.

**pipeline.py implementation:** The JSON extraction prompt tells Firecrawl's
LLM: "Describe WHAT INFORMATION IS ON THIS PAGE, like a card catalog entry.
Do not repeat the page content."

### D4: Keyword expansion makes ripgrep semantic

Ripgrep is literal matching. The agent is an LLM. The bridge: expand
queries into synonyms and related terms before searching.

```
Query: "nose job recovery"
  → Expand: "rhinoplasty|septoplasty" + "recovery|downtime|aftercare"
  → rg -l "rhinoplasty|septoplasty" $PAGES
```

**Why:** The LLM is the semantic layer — it knows "nose job" = rhinoplasty.
Ripgrep handles the filesystem. Combined = semantic search with zero
infrastructure (no embeddings, no vector DB).

**SKILL.md implementation:** Step 1 teaches expansion patterns:
informal → formal, technical → colloquial, specific → broader category.

**Rejected: hardcoded vocabulary in SKILL.md.** Would go stale when pages
change. The agent discovers vocabulary dynamically via `rg "^title:" $PAGES`.

### D5: $PAGES path resolution

Agent's working directory ≠ skill folder. Bare `pages/` paths fail.

**Fix:** SKILL.md tells the agent to resolve the absolute path from the
SKILL.md file location. All command examples use `$PAGES` placeholder.

**Origin:** Found by a real agent that stumbled through failed searches.

### D6: Skill name = domain, 2 template variables

The skill name IS the domain: `csaok.com`, `docs.stripe.com`,
`blog.example.com`. Strip `www.` only.

Only two variables in skill-md.template:

| Variable | Example |
|----------|---------|
| `{domain}` | `csaok.com` |
| `{site_description}` | `Cosmetic Surgery Affiliates, a cosmetic surgery and med spa practice...` |

**Why domain as name:** Unambiguous. Agent needs info from csaok.com →
searches "csaok.com" → finds the skill.

**Why only 2 variables:** Everything else in SKILL.md (search protocol,
tips, discovery commands) is identical across all websites. When pages
change, SKILL.md doesn't need to change.

### D7: Frontmatter screening for scale

Narrow queries (2-5 results) → load candidates directly.
Broad queries (10+ results) → screen frontmatter first:

```bash
rg -l "term" $PAGES | xargs head -n 12
```

Shows ~12 lines per candidate (title + description + summary) without
loading full page content. Agent picks relevant pages from summaries.

### D8: Markdown cleanup

Raw scraped markdown has junk: nav remnants, CTAs, exit-intent popups.

**Current rules:**
- Strip leading junk until first heading or substantial paragraph
- Skip known patterns: `[Back...`, `Consult Now`, `Filter`

**Known gaps:** trailing CTA/popup content not yet stripped.

### D9: Slug generation

URL path → filesystem-safe filename:
- `/` → `index`
- `/about` → `about`
- `/services/botox-in-oklahoma-city` → `services--botox-in-oklahoma-city`

`/` becomes `--` to preserve hierarchy in flat filenames.

---

## Pipeline Steps

### Step 1: Map (1 credit)

`POST https://api.firecrawl.dev/v1/map` — returns deduplicated URL list.

### Step 2: Batch Scrape (5 credits/page)

`POST https://api.firecrawl.dev/v2/batch/scrape` — markdown + JSON extraction
in one call. JSON uses inline format object in the `formats` array (NOT
top-level `jsonOptions` — that returns 400).

Poll `GET /v2/batch/scrape/{id}` every 5s. Follow `next` for pagination.

### Step 3: Assemble (free)

Local file generation. Reads `skill-md.template` for SKILL.md, writes
`pages/{slug}.md` with YAML frontmatter + cleaned markdown body.

**Cost formula:** 1 + 5N credits (N = number of pages).

---

## Test Data: csaok.com

- **Map:** 247 URLs, 0 duplicates
- **Scrape:** 10 pages tested, 50 credits, ~50 seconds
- **JSON quality:** titles clean, summaries are keyword-rich content manifests
- **Agent test:** real agent used skill successfully; found $PAGES issue (D5)

---

## Open Issues

- [ ] Trailing CTA/popup cleanup (D8)
- [ ] Summary prompt tuning — more agent testing needed (D3)
- [ ] Agent tool compatibility — SKILL.md assumes bash (`rg` + `head`),
  some agents use dedicated Read/Grep tools (D5)
- [ ] Scale validation with 247 pages (D7)
