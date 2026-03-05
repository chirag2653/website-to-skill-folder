# Changelog

All notable changes to the website-to-skill-folder skill are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

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
