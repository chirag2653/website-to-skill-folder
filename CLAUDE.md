# Website-to-Skill-Folder — Project Guide

## What This Project Is

A Python pipeline that converts any website into an installable AI agent skill folder. The skill folder contains searchable markdown pages with YAML frontmatter — agents search it offline using ripgrep.

**This repo is a "skill workshop"** — you cd into it to improve the skill, push to GitHub, then install the updated skill in other agent sessions via `npx skills add`.

## Repo Layout

```
repo root/                              ← dev scaffolding (NOT installed)
├── CLAUDE.md                           ← you are here
├── README.md                           ← public-facing docs
├── CHANGELOG.md                        ← version history
├── requirements.txt                    ← pip dependencies
├── .gitignore
│
├── _dev-notes/                         ← design docs (gitignored)
│   ├── ARCHITECTURE.md                 ← design decisions, pipeline flow, key concepts
│   └── DECISIONS.md                    ← historical change log of what was tried/rejected
│
├── _workspace/                         ← runtime cache (gitignored, created by pipeline)
├── output/                             ← generated skill folders (gitignored, created by pipeline)
│
└── skills/
    └── website-to-skill-folder/        ← THE SKILL (what npx skills add installs)
        ├── SKILL.md                    ← agent-facing instructions
        └── scripts/
            ├── pipeline.py             ← the pipeline (~2200 lines)
            ├── skill-md.template       ← template for generated skills' SKILL.md
            ├── .env.local              ← API key (gitignored, create from .env.local.example)
            └── .env.local.example      ← API key template
```

## Key Rule: Skill vs Dev Separation

Everything under `skills/website-to-skill-folder/` ships to agents. Everything else stays in the repo for development only.

- **Editing the skill?** Edit files inside `skills/website-to-skill-folder/`.
- **Adding dev docs, tests, CI?** Add them at the repo root or in `_dev-notes/`.
- **Never put dev-only files inside `skills/`** — they'd ship to every agent.

## Pipeline CLI Flags

```
python pipeline.py <url> [options]

Core flags:
  --max-pages N        Cap skill folder at N pages (scrape only first N)
  --skip-scrape        Reassemble from cache, zero API calls (idempotent)
  --force-refresh      Ignore all cache, re-scrape everything
  --dry-run            Map only (1 credit), show cost estimate, no scraping
  --yes / -y           Auto-approve cost prompt (for scripts/agents)
  --description TEXT   Override auto-extracted site description

Output modes:
  (default)            Flat skill folder at ./output/{skill_name}/
  --repo-ready         Git-ready repo with skill nested inside subfolder
  --output PATH        Override output dir (in --repo-ready: overrides repo root)

GitHub automation (requires --repo-ready):
  --init-github OWNER  git init + gh repo create {owner}/skill-folder-{skill_name}
  --install            After GitHub push, npx skills add to install globally
```

## Output Modes

### Flat mode (default)
Output at `./output/{skill_name}/`:
```
output/
└── {skill_name}/
    ├── SKILL.md
    └── pages/
```
Install with local path: `npx skills add "./output/{skill_name}" -g -y`

### --repo-ready mode
Output is a full git repo structure, suitable for pushing to GitHub and installing via `npx skills add owner/repo`:
```
{skill_name}/           ← git repo root (or --output path)
├── {skill_name}/       ← installable skill (SKILL.md here) ← npx skills installs THIS
│   ├── SKILL.md
│   └── pages/
├── dev/
│   ├── _workspace/     ← Firecrawl cache (state.json, map-urls.txt — committed for incremental re-runs)
│   └── notes.md        ← auto-generated run log
├── CLAUDE.md           ← repo dev context, NOT installed
└── .gitignore          ← excludes dev/test-output/ and dev/_workspace/batch-response.json
```
Deploy: `cd {skill_name} && gh repo create <owner>/skill-folder-{skill_name} --private --source . --push`
Install: `npx skills add <owner>/skill-folder-{skill_name} -g --all`

### --repo-ready + --init-github + --install (fully automated)
Runs the entire pipeline including git init, gh repo create, push, and skill install in one command.

## How to Make Changes

### Editing the pipeline (scripts/pipeline.py)

This is the main codebase. Key sections:
- `PipelineInput` — input validation and normalization
- `filter_content_urls()` — strips static asset URLs (CSS/JS/fonts/images) from map results
- `map_website()` — Step 1: discover URLs via Firecrawl
- `batch_scrape()` — Step 2: scrape pages in batches of 100
- `assemble_pages()` — Step 3: write markdown files with frontmatter
- `generate_skill_md()` — render the SKILL.md template
- `_generate_repo_scaffolding()` — Step 4 (--repo-ready): write .gitignore, CLAUDE.md, dev/notes.md
- `_run_git_push()` — Step 5 (--init-github): git init + gh repo create + push
- `_run_install()` — Step 6 (--install): npx skills remove + add

### Editing the generated skill template (scripts/skill-md.template)

This template produces the SKILL.md that goes into every generated website search skill. It has these variables:
- `{domain}` — e.g. `csaok.com`
- `{skill_name}` — e.g. `csaok-com-website-search-skill`
- `{site_description}` — auto-extracted or manual description
- `{page_count}` — number of pages indexed
- `{site_expansions}` — site-specific query expansion hints (may be empty)

**Important:** The template uses Python `.format()` — any literal `{` or `}` in the template must be escaped as `{{` or `}}`. Currently the template has no literal braces, but be careful if adding bash code with `${}` syntax.

### Editing SKILL.md (the tool's own instructions)

`skills/website-to-skill-folder/SKILL.md` tells agents how to run this pipeline. It hardcodes the installed path `$HOME/.agents/skills/website-to-skill-folder/scripts/pipeline.py` — this is correct because agents run the installed copy, not the dev copy.

## How to Test Changes

### Quick validation (no API calls)
```bash
# Syntax check
python -c "import py_compile; py_compile.compile('skills/website-to-skill-folder/scripts/pipeline.py', doraise=True)"

# Verify --help works (imports all dependencies)
python skills/website-to-skill-folder/scripts/pipeline.py --help

# Reassemble from cached data (zero API calls, requires previous run)
python skills/website-to-skill-folder/scripts/pipeline.py example.com --skip-scrape
```

### Preview cost without scraping (1 credit)
```bash
python skills/website-to-skill-folder/scripts/pipeline.py example.com --dry-run
```

### Full test run (costs Firecrawl credits)
```bash
# Flat mode
python skills/website-to-skill-folder/scripts/pipeline.py example.com --max-pages 20 --yes

# --repo-ready mode (generates git repo structure)
python skills/website-to-skill-folder/scripts/pipeline.py example.com --max-pages 20 --yes --repo-ready

# --skip-scrape on an existing --repo-ready output (zero credits, tests cache reuse)
python skills/website-to-skill-folder/scripts/pipeline.py example.com --yes --repo-ready --output output/example-repo-test --skip-scrape
```

### After pushing: reinstall and test
```bash
# Push changes
git add skills/ && git commit -m "..." && git push

# Reinstall in agents
rm -rf "$HOME/.agents/skills/website-to-skill-folder"
npx skills add chirag2653/website-to-skill-folder -g -y

# Test in a new agent session
```

## Self-Referencing Paths in pipeline.py

`pipeline.py` uses `__file__`-relative paths in exactly 2 places:
1. `generate_skill_md()` — finds `skill-md.template` as a sibling of `pipeline.py`
2. `get_api_key()` — finds `.env.local` as a sibling of `pipeline.py`

**These files must stay siblings.** If you move `pipeline.py`, move `skill-md.template` and `.env.local.example` with it.

Everything else (`_workspace/`, `output/`) is created at `os.getcwd()` — the caller's working directory.

In `--repo-ready` mode, workspace goes to `{repo_root}/dev/_workspace/` instead of `_workspace/{domain}/`.

## URL Filtering

`filter_content_urls()` removes static asset URLs from Firecrawl's map results before any scraping occurs. This prevents wasting credits on Next.js/Nuxt build artifacts (`.css`, `.js`, `/_next/static/`, etc.). The function is applied at all three call sites in `map_website()`.

## URL Slug Generation

`assemble_pages()` uses `metadata.sourceURL` (not `ogUrl`) as the canonical URL for slug generation. `ogUrl` is unreliable — some pages set it to the homepage URL, which causes slug collisions. `sourceURL` is always the actual URL Firecrawl scraped.

The same `sourceURL`-first priority applies in `extract_site_description()` for homepage detection, which also checks `www.{domain}` variants.

## Architecture

See `_dev-notes/ARCHITECTURE.md` for design decisions (D1-D9), pipeline flow, and key concepts like "summary = content manifest" and "keyword expansion makes ripgrep semantic".

## Conventions

- **Commit messages:** `feat:`, `fix:`, `refactor:`, `docs:` prefixes
- **Pipeline changes:** Always run `--help` and syntax check before committing
- **Template changes:** Regenerate a test skill with `--skip-scrape` to verify output
- **Design decisions:** If changing a core design decision (D1-D9), update `_dev-notes/ARCHITECTURE.md`
- **Changelog:** Update `CHANGELOG.md` for user-facing changes

## What Not to Do

- Don't put dev files (tests, CI, docs) inside `skills/website-to-skill-folder/`
- Don't break the sibling relationship between `pipeline.py` and `skill-md.template`
- Don't add literal `{` or `}` to `skill-md.template` without escaping
- Don't commit `.env.local` (contains API keys — gitignored)
- Don't run concurrent pipeline instances for the same domain (no file locking)
- Don't use `ogUrl` for slug generation — always use `sourceURL` (ogUrl can point to homepage for non-homepage pages)
- Don't remove `filter_content_urls()` — without it, static assets consume scrape credits and pollute the skill
