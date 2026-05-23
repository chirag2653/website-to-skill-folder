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
│   (runs use a temp dir for the clone/build; nothing is written to the repo root)
│
└── skills/
    └── website-to-skill-folder/        ← THE SKILL (what npx skills add installs)
        ├── SKILL.md                    ← agent-facing instructions
        └── scripts/
            ├── pipeline.py             ← the pipeline (~2400 lines)
            ├── preflight.py            ← stdlib-only environment check (run before the pipeline)
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
  --skip-scrape        Reassemble from the repo's committed cache (no scrape, no Firecrawl key)
  --force-refresh      Ignore all cache, re-scrape everything
  --dry-run            Sync + map only (1 credit), show cost estimate, no scrape/push
  --yes / -y           Auto-approve cost + visibility prompts (for scripts/agents)
  --description TEXT   Override auto-extracted site description

GitHub (always — GitHub is the source of truth):
  --owner NAME         Account/org that owns the repo (default: authenticated gh user)
  --visibility V       public|private for a NEW repo (default: prompt, or private with --yes)
  --no-install         Push to GitHub but skip the npx install step
  --work-dir PATH      Persistent local working dir (default: temp dir, deleted after run)
  --keep-temp          Keep the temp working dir after the run (debugging)
```

There is exactly one output path now: **GitHub**. Every run targets
`github.com/{owner}/skill-folder-{skill_name}`. There is no flat/local-only mode.

## Architecture: GitHub-first

The pipeline treats the GitHub repo as the durable artifact and local disk as scratch:

```
resolve owner (gh api user, or --owner)
  → clone github.com/{owner}/skill-folder-{skill_name} into a temp dir
    (or `git init` a fresh temp dir if the repo doesn't exist yet)
  → map the site, compare against the repo's committed dev/_workspace/state.json
  → scrape only NEW pages; delete page files for URLs gone 3+ runs (update-and-delete)
  → assemble skill folder + SKILL.md + scaffolding
  → (new repos only) resolve visibility: --visibility, else prompt, else private
  → commit + push (gh repo create --{visibility} for new repos)
  → npx skills add {owner}/{repo} -g --all   (unless --no-install)
  → delete the temp dir   (unless --work-dir / --keep-temp)
```

Repo layout pushed to GitHub:
```
skill-folder-{skill_name}/   ← git repo root
├── {skill_name}/       ← installable skill (SKILL.md here) ← npx skills installs THIS
│   ├── SKILL.md
│   └── pages/
├── dev/
│   ├── _workspace/     ← scrape cache (state.json, map-urls.txt) — COMMITTED; the
│   │                      source of truth that makes incremental re-runs work anywhere
│   └── notes.md        ← auto-generated run log
├── README.md          ← single root doc: GitHub landing page (install / share / update);
│                         renders on GitHub and is readable by agents. NOT installed.
└── .gitignore          ← excludes dev/_workspace/batch-response.json
```

Install (any machine): `npx skills add <owner>/skill-folder-{skill_name} -g --all`

**Why committed `state.json` matters:** the cache travels with the repo, so a fresh
clone on any machine knows what was already scraped — updates stay incremental and
orphaned pages are detected regardless of where the previous run happened.

## How to Make Changes

### Editing the pipeline (scripts/pipeline.py)

This is the main codebase. `main()` resolves the owner, calls `prepare_work_dir()`
(clone/init in a temp dir), then runs `_run_pipeline()` inside a `try/finally` that
cleans up the temp dir. Key sections:
- `PipelineInput` — input validation; resolves `domain`, `skill_name`, `repo_name`
- `resolve_owner()` — `--owner` or `gh api user`
- `repo_exists()` / `prepare_work_dir()` — Step 0: clone the repo (source of truth) or git init
- `filter_content_urls()` — strips static asset URLs (CSS/JS/fonts/images) from map results
- `map_website()` — Step 1: discover URLs via Firecrawl
- `batch_scrape()` — Step 2: scrape pages in batches of 100
- `assemble_pages()` — Step 3: write markdown files with frontmatter
- `generate_skill_md()` — render the SKILL.md template
- `prompt_visibility()` / `get_repo_visibility()` — resolve public/private (chosen for new repos, looked up for existing) before scaffolding/push
- `_generate_repo_scaffolding()` — Step 4: write README.md (the single root doc), .gitignore, dev/notes.md; removes any stale CLAUDE.md left by older generator versions
- `_share_note()` — visibility-aware one-liner used in the README + final summary
- `_run_git_push()` — Step 5: commit + push; `gh repo create --{visibility}` for new repos
- `_run_install()` — Step 6: npx skills remove + add (from GitHub)

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

### Quick validation (no API calls, no network)
```bash
# Syntax check (both scripts)
python -c "import py_compile; py_compile.compile('skills/website-to-skill-folder/scripts/preflight.py', doraise=True); py_compile.compile('skills/website-to-skill-folder/scripts/pipeline.py', doraise=True)"

# Verify --help works (imports all dependencies)
python skills/website-to-skill-folder/scripts/pipeline.py --help

# Environment pre-flight (stdlib only — runs even with deps missing)
python skills/website-to-skill-folder/scripts/preflight.py        # report
python skills/website-to-skill-folder/scripts/preflight.py --fix  # auto-install pip deps
```

### Graceful-failure design
The pipeline must never dump a traceback or argparse usage on a missing prerequisite:
- `preflight.py` is **stdlib-only** so it runs even when requests/pydantic/tenacity are absent.
- `pipeline.py` wraps its third-party imports (clean message + exit), gates required tools
  via `preflight.*` helpers (`_tool_missing`), checks **git identity before scraping** (so a
  misconfigured git never wastes Firecrawl credits), and `resolve_owner`/`get_api_key` already
  handle `gh`-not-authed and missing-key gracefully.
- When adding a new prerequisite, add the check to `preflight.collect()` AND gate it in
  `pipeline.py` so direct runs stay graceful.

Live runs require the `gh` CLI (authenticated) and a Firecrawl key, since every run
syncs with GitHub. To exercise the file-producing logic offline, drive `assemble_pages()`,
`generate_skill_md()`, and `_generate_repo_scaffolding()` against fake page dicts in a
temp dir (see the offline integration test pattern used during the GitHub-first refactor).

### Preview cost without scraping (1 credit)
```bash
python skills/website-to-skill-folder/scripts/pipeline.py example.com --dry-run
```
(Syncs with GitHub + maps; reports only NEW pages for an existing repo.)

### Full test run (costs Firecrawl credits; needs gh auth)
```bash
# Create/update a PRIVATE repo under your gh account and install it
python skills/website-to-skill-folder/scripts/pipeline.py example.com --max-pages 20 --yes

# Public repo, custom owner, no install
python skills/website-to-skill-folder/scripts/pipeline.py example.com --max-pages 20 --yes --visibility public --owner my-org --no-install

# Inspect the built tree without pushing churn: keep the working dir
python skills/website-to-skill-folder/scripts/pipeline.py example.com --yes --work-dir /tmp/wsf-debug --keep-temp

# Zero-credit reassemble from the repo's committed cache (no Firecrawl key)
python skills/website-to-skill-folder/scripts/pipeline.py example.com --yes --skip-scrape
```

### After editing the workshop skill: reinstall and test
```bash
# Push changes to THIS repo
git add skills/ && git commit -m "..." && git push

# Reinstall the workshop skill in agents
rm -rf "$HOME/.agents/skills/website-to-skill-folder"
npx skills add chirag2653/website-to-skill-folder -g -y

# Test in a new agent session
```

## Self-Referencing Paths in pipeline.py

`pipeline.py` uses `__file__`-relative paths in exactly 2 places:
1. `generate_skill_md()` — finds `skill-md.template` as a sibling of `pipeline.py`
2. `get_api_key()` — finds `.env.local` as a sibling of `pipeline.py`

**These files must stay siblings.** If you move `pipeline.py`, move `skill-md.template` and `.env.local.example` with it.

Everything else is created inside the per-run working directory (a temp dir, or `--work-dir`):
the skill at `{work_dir}/{skill_name}/` and the cache at `{work_dir}/dev/_workspace/`. Nothing
is written to `os.getcwd()` anymore, and the temp dir is deleted at the end of the run.

## Local Footprint (what touches the user's machine)

When a user runs the installed skill from a project folder, the local file I/O is:

- **Their project folder (cwd): nothing.** No file in `os.getcwd()` is ever read or written.
- **System temp:** exactly one dir, `tempfile.mkdtemp(prefix="website-to-skill-")`, holding
  the clone + scrape cache. Removed in `main()`'s `finally` — covering success, `--dry-run`
  exit, cost decline, exceptions, and KeyboardInterrupt. `prepare_work_dir()` also cleans its
  own temp dir if `git clone` fails (it `sys.exit`s before that `finally` is armed). Survivors:
  only `--work-dir` / `--keep-temp`, or a hard kill / power loss (OS reclaims `/tmp`).
- **Installed skill dir (`~/.agents/skills/website-to-skill-folder/`): nothing.** It's read
  only (template + `.env.local` are read). `pipeline.py` sets `sys.dont_write_bytecode = True`
  before importing `preflight`, so not even a `__pycache__/*.pyc` is left behind — keep that line.
- **Durable, intended:** the produced skill installed at `~/.agents/skills/{skill_name}/`
  (the deliverable) and the repo on GitHub (the source of truth). Tool caches like `~/.npm`
  and `~/.config/gh` are managed by those tools, not us.

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
