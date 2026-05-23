# Changelog

All notable changes to the website-to-skill-folder skill are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Changed (BREAKING) — GitHub-first architecture
- The pipeline is now **GitHub-first**. GitHub is the source of truth: every run clones
  `github.com/{owner}/skill-folder-{skill_name}` into a temp directory, updates it
  incrementally, pushes it back, and installs it via `npx skills add`. The temp directory
  is deleted afterward — nothing durable is written to the local working directory.
- Removed the flat local-only output mode and the `--repo-ready` / `--init-github` /
  `--output` flags. There is exactly one output target: the GitHub repo.

### Added
- `--owner NAME` — GitHub account/org for the repo (defaults to the authenticated `gh` user).
- `--visibility public|private` — visibility for a newly created repo. Defaults to a prompt
  (or `private` with `--yes`). Ignored when the repo already exists.
- `--no-install` — push to GitHub but skip the `npx skills add` step.
- `--work-dir PATH` / `--keep-temp` — use/keep a persistent working directory (debugging).
- Owner auto-derivation via `gh api user`, so the minimum inputs are URL + Firecrawl key.
- New helpers: `resolve_owner()`, `repo_exists()`, `prepare_work_dir()`, `prompt_visibility()`.

### Changed
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
