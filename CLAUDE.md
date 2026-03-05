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
            ├── pipeline.py             ← the pipeline (~1800 lines)
            ├── skill-md.template       ← template for generated skills' SKILL.md
            └── .env.local.example      ← API key template
```

## Key Rule: Skill vs Dev Separation

Everything under `skills/website-to-skill-folder/` ships to agents. Everything else stays in the repo for development only.

- **Editing the skill?** Edit files inside `skills/website-to-skill-folder/`.
- **Adding dev docs, tests, CI?** Add them at the repo root or in `_dev-notes/`.
- **Never put dev-only files inside `skills/`** — they'd ship to every agent.

## How to Make Changes

### Editing the pipeline (scripts/pipeline.py)

This is the main codebase. Key sections:
- `PipelineInput` — input validation and normalization
- `map_website()` — Step 1: discover URLs via Firecrawl
- `batch_scrape()` — Step 2: scrape pages in batches of 100
- `assemble_pages()` — Step 3: write markdown files with frontmatter
- `generate_skill_md()` — render the SKILL.md template

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
python skills/website-to-skill-folder/scripts/pipeline.py example.com --max-pages 10
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
