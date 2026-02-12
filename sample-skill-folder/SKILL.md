---
name: csaok-website
description: >
  Searchable reference for csaok.com (Cosmetic Surgery Affiliates).
  Use this skill to search the website's content when creating blog briefs,
  content outlines, case studies, or any task that needs website context.
---

# Website Search — csaok.com

This skill gives you searchable access to csaok.com — Cosmetic Surgery
Affiliates, a cosmetic surgery and med spa practice with locations in
Oklahoma City, OK and Jacksonville, FL.

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
