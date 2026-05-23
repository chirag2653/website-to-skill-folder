# Changelog

All notable changes to the website-to-skill-folder skill are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Fixed
- **Dry-run cost estimate now includes the unscraped backfill.** When an earlier run mapped
  URLs but never scraped them (e.g. a capped `--max-pages` run), the real run backfills them —
  but `--dry-run` ignored them and under-quoted (a "~6 credit" dry-run became a ~386 credit
  run). Dry-run and the real run now share one `unscraped_unchanged_urls()` helper, so the
  estimate matches; a `Backfill: N` line is shown when relevant.
- **No more `UnicodeDecodeError` traceback on Windows.** The `gh`/`git` subprocess calls
  (`gh api user`, `gh repo view` ×2, `git commit`) and `preflight.py`'s `_run` now decode child
  output as UTF-8 (`errors="replace"`) instead of the cp1252 locale default, which crashed a
  reader thread on any non-cp1252 byte (e.g. a `←`/em-dash in the repo README) and dumped a
  traceback ahead of every run's real output.
- **Dry-run "0 new" now says "Already up to date — nothing to scrape or remove"** instead of
  the misleading "rerun without --dry-run".
- **SKILL.md guidance:** new-vs-update is keyed off GitHub repo existence (not local install
  presence); the agent no longer re-asks an already-given page cap or bundles it with the
  visibility question; `--max-pages` is documented as "first N in map order" (non-curated,
  order can drift); Step 5 adds an optional Claude Code symlink check and runs the install
  validation as its own command so it isn't buried in `npx` spinner output.
- **Incremental re-runs now detect just-published pages.** The map step always requests a
  fresh URL list (`ignoreCache: true`) instead of only on `--force-refresh`. Firecrawl's
  `/map` caches results for several minutes, so a re-run shortly after publishing a page
  previously reported "0 new" and missed it. The map costs 1 credit either way, so there's
  no cost downside to always-fresh discovery. (Root cause confirmed against the live
  Firecrawl API; the page was live, sitemapped, and scrapable — only discovery was stale.)
- **Output pluralization** — counts now read "1 page" / "1 new URL" instead of "1 pages" /
  "1 new URLs" via a `_plural()` helper, applied across the map/scrape/assemble/cost lines.
- **Windows console encoding** — `pipeline.py` and `preflight.py` now force UTF-8 on
  stdout/stderr at startup, so status lines containing em-dashes/arrows/box-drawing
  characters render correctly (previously `�`) and never crash with `UnicodeEncodeError`
  on Windows consoles defaulting to cp1252.
- **Dry-run cost label** — the dry-run summary's cost breakdown now reports the *capped*
  page count when `--max-pages` applies (e.g. "~50 for 10 pages") instead of contradicting
  its own credit figure by printing the total discovered URL count.

### Changed
- **Generated repos now ship a single root doc: `README.md`.** CLAUDE.md is no longer
  generated (it was ~80% redundant with README and, unlike README, doesn't render on the
  GitHub repo page). The scaffolding step also removes any stale CLAUDE.md left by older
  generator versions, so updated repos converge on the README-only layout.
- **This repo consolidated to a single root doc too.** The dev `CLAUDE.md` was folded into a
  `## Development` section in `README.md` and removed, so the shared GitHub repo presents one
  clean, production-ready landing page.

### Added
- **`tests/test_pipeline.py`** — lightweight, network-free regression tests (no pytest
  dependency) covering the always-fresh map behavior and output pluralization.

### Changed (BREAKING) — GitHub-first architecture
- The pipeline is now **GitHub-first**. GitHub is the source of truth: every run clones
  `github.com/{owner}/skill-folder-{skill_name}` into a temp directory, updates it
  incrementally, pushes it back, and installs it via `npx skills add`. The temp directory
  is deleted afterward — nothing durable is written to the local working directory.
- Removed the flat local-only output mode and the `--repo-ready` / `--init-github` /
  `--output` flags. There is exactly one output target: the GitHub repo.

### Added
- **`preflight.py`** — a stdlib-only environment check that runs before the pipeline. It
  probes Python, packages, git + commit identity, `gh` + auth (and shows which account repos
  land under), Node/npx, and the Firecrawl key; tags each as OK/FIX/GUIDE/ASK with
  platform-aware install hints and a clear READY/BLOCKED verdict. `--fix` auto-installs the
  Python packages. SKILL.md now drives onboarding from this single report.
- Graceful failures in `pipeline.py`: third-party imports degrade to an actionable message
  instead of a traceback; missing `git`/`gh`/Node exit with guidance (not an argparse dump);
  git commit identity is verified **before** any scraping so a misconfigured git never wastes
  Firecrawl credits.
- Generated repos now include a production-grade **README.md** landing page (install command,
  visibility-aware "share with teammates" section, update instructions, what's-inside).
- Visibility-aware orchestration: the final summary and README state whether the repo is
  public or private (`get_repo_visibility()` for existing repos), and always surface a
  copy-paste **share command** for teammates alongside install + update.
- `--owner NAME` — GitHub account/org for the repo (defaults to the authenticated `gh` user).
- `--visibility public|private` — visibility for a newly created repo. Defaults to a prompt
  (or `private` with `--yes`). Ignored when the repo already exists.
- `--no-install` — push to GitHub but skip the `npx skills add` step.
- `--work-dir PATH` / `--keep-temp` — use/keep a persistent working directory (debugging).
- Owner auto-derivation via `gh api user`, so the minimum inputs are URL + Firecrawl key.
- New helpers: `resolve_owner()`, `repo_exists()`, `prepare_work_dir()`, `prompt_visibility()`.

### Changed
- Agent flow (SKILL.md) now **always pushes** but **installs only on request**: the run is
  non-interactive (`--yes --no-install`) so the user never waits at a terminal prompt; then
  the agent gives a flow-aware summary (with a shareable link for public repos), asks once
  whether to install locally, runs `npx skills add`, **validates** the skill landed in
  `~/.agents/skills/{skill_name}/`, and confirms it's ready to use in a new session. On
  updates it reinstalls silently if already present (no re-ask). Direct CLI runs still
  auto-install unless `--no-install` is passed.
- `--skip-scrape` now reassembles from the repo's committed cache and pushes; it no longer
  requires a Firecrawl API key.
- `--dry-run` now also syncs with GitHub, so it reports only *new* pages for an existing repo.
- `gh` CLI is now always required; Node.js is required unless `--no-install`/`--dry-run`.
- Updated SKILL.md, README.md, and CLAUDE.md for the GitHub-first flow.

## [1.1.0] - 2026-03-05

### Added
- `--dry-run` flag — map the site and show cost estimate without scraping
- `--output` flag documentation in SKILL.md
- API key validation before spending map credits (catches bad keys early)
- Good/bad summary examples in LLM extraction prompt for better search quality
- Site-aware query expansion categories auto-generated from page content
- `{page_count}` variable in generated skills so agents know the skill size
- Troubleshooting & Recovery section in SKILL.md
- Manual `$PAGES` path override documentation in generated skills
- CLAUDE.md project guide for AI agents working on this repo
- CHANGELOG.md (this file)
- requirements.txt for dev convenience

### Changed
- All `rg` commands in generated skills now use `-i` (case-insensitive) by default
- SKILL.md description expanded with more trigger phrases to reduce undertriggering
- Repo restructured: skill files moved to `skills/website-to-skill-folder/` to separate installable skill from dev scaffolding
- Dev notes consolidated from 40+ files into ARCHITECTURE.md and DECISIONS.md

## [1.0.0] - 2026-02-22

### Added
- Core pipeline: Map → Batch Scrape → Assemble
- Pydantic input validation with flexible URL handling
- Automatic retry with exponential backoff (tenacity) on all API calls
- State persistence and crash-resume via state.json
- Incremental updates — only scrapes new pages on re-runs
- `--skip-scrape` mode for zero-API-call reassembly from cache
- `--force-refresh` mode to ignore cache and re-scrape everything
- `--max-pages` to cap skill folder size and control costs
- `--description` for manual site description override
- Cost approval gate before scraping
- Robust orphaned page deletion (3-miss threshold)
- Windows MAX_PATH safety (80-char slug limit + hash suffix)
- SEO meta tag preference over LLM extraction for title/description
- Keyword-rich "content manifest" summaries for search quality
- Site description auto-extraction with 4-tier fallback
- Source citation instructions in generated skills
- Analytical query workflows in generated skills
- Self-contained install commands printed after pipeline completion
- Packaged as installable agent skill via `npx skills add`
