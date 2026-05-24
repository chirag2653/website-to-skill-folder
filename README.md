# website-to-skill-folder

**Turn any website into an installable AI agent skill that lives in your own GitHub — one command, fully offline search.**

Point it at a URL. It crawls the site, packages every page as searchable markdown, pushes the result to a repo in **your** GitHub account, and installs it via `npx skills add`. Your AI agents (Claude Code, Gemini CLI, Cursor, Codex, and more) can then answer questions about that website — no live browsing, no API calls at query time. Re-run later and it updates the same repo incrementally.

---

## How It Works

GitHub is the source of truth. A single run:

1. Resolves your GitHub account (`gh api user`, or `--owner`).
2. Clones `github.com/{owner}/skill-folder-{skill_name}` into a temp directory — or starts a fresh one if it doesn't exist yet.
3. Maps the site and compares against the repo's committed cache, so it scrapes only **new** pages and deletes pages that disappeared from the site.
4. Assembles the skill folder and pushes it back to GitHub (creating the repo, private by default, the first time).
5. Installs it with `npx skills add`.
6. Deletes the temp directory. Nothing durable is left on your machine.

```bash
python skills/website-to-skill-folder/scripts/pipeline.py https://docs.example.com --yes
```

At the end it prints the repo URL and the install command teammates can use:

```
  GitHub repo:  https://github.com/you/skill-folder-docs-example-com-website-search-skill
  Installed:    ~/.agents/skills/docs-example-com-website-search-skill/

  Install in any agent:
    npx skills add you/skill-folder-docs-example-com-website-search-skill -g --all
```

Ask your agent anything about the site:

> *"What are the authentication options?"*
> *"How do I configure webhooks?"*
> *"What changed in the latest release?"*

The agent searches the skill folder offline — fast, accurate, with source citations back to the original page URLs.

---

## Public, Private, and Teams

New repos are **private by default**. You're prompted at creation time (or pass a flag):

```bash
# Public — anyone can install with no auth
python .../pipeline.py https://example.com --yes --visibility public

# Host under a shared org so your team has access
python .../pipeline.py https://example.com --yes --owner my-org
```

For a private repo, teammates install with their own GitHub access:

```bash
npx skills add my-org/skill-folder-example-com-website-search-skill -g --all
```

`--visibility` only applies when the repo is first created; after that, manage visibility on GitHub.

---

## Install This Tool as an Agent Skill

The pipeline itself is packaged as an agent skill. Install it once and ask your agent to run it:

```bash
# All agents (Claude Code, Gemini CLI, Codex, Cursor, etc.):
npx skills add chirag2653/website-to-skill-folder -g -y

# Claude Code only:
npx skills add chirag2653/website-to-skill-folder -g -y -a claude-code
```

Then from any project, just ask:

> *"Create a website search skill for https://example.com"*

The agent runs the pipeline, pushes the skill to your GitHub, and installs it.

---

## Manual Setup

### Prerequisites

1. **Python 3.8+** — the bundled `preflight.py` installs the rest (`requests`, `pydantic`, `tenacity`) for you when you run it. To install manually: `pip install requests pydantic tenacity`.
2. **GitHub CLI**, authenticated — install [`gh`](https://cli.github.com), then `gh auth login`. GitHub is where the skill lives.
3. **Node.js** (for `npx skills add`) — [nodejs.org](https://nodejs.org). Skip with `--no-install`.
4. **Firecrawl API key** — free at [firecrawl.dev](https://firecrawl.dev). Set it via:
   ```bash
   export FIRECRAWL_API_KEY="fc-your_key_here"
   # or: cp scripts/.env.local.example scripts/.env.local  (then edit it)
   ```

### Run

```bash
python skills/website-to-skill-folder/scripts/pipeline.py https://example.com --yes
```

### Options

| Flag | Purpose |
|------|---------|
| `--owner NAME` | GitHub account/org that owns the repo (default: the authenticated `gh` user) |
| `--visibility public\|private` | Visibility for a **new** repo (default: private). Ignored on updates |
| `--description "..."` | One-line site description added to the generated SKILL.md |
| `--max-pages 100` | Cap pages scraped — directly controls Firecrawl credit cost |
| `--yes` / `-y` | Auto-approve cost + visibility prompts (use from scripts/agents) |
| `--dry-run` | Sync + map + show cost estimate, then exit (no scrape, no push) |
| `--skip-scrape` | Rebuild from the repo's committed cache and push — no scrape, no Firecrawl key |
| `--force-refresh` | Ignore cache and re-scrape all pages |
| `--no-install` | Push to GitHub but skip the install step |
| `--work-dir PATH` | Use a persistent local dir instead of a temp dir (debugging) |

---

## What Gets Produced

The repo pushed to GitHub:

```
skill-folder-{skill_name}/   ← git repo in your GitHub account
├── {skill_name}/            ← the installable skill (npx installs THIS)
│   ├── SKILL.md             ← agent instructions + keyword index
│   └── pages/               ← one .md file per scraped page
├── dev/
│   ├── _workspace/          ← scrape cache (state.json) — committed, powers incremental re-runs
│   └── notes.md
├── README.md                ← GitHub landing page (install / share / update); the single root doc
└── .gitignore
```

Each page is a `.md` file with YAML frontmatter optimised for `grep`/`ripgrep`:

```yaml
---
title: "Page Title"
description: "1-2 sentence description"
url: "https://example.com/page"
summary: |
  3-5 sentence keyword-rich summary for search matching
---
```

---

## Features

- **GitHub-hosted** — The skill lives in a repo you own; install and update from anywhere.
- **Incremental updates** — Clones the repo and re-scrapes only new pages on each run.
- **Update-and-delete** — Pages removed from the site are deleted after 3 consecutive map misses (guards against transient failures).
- **Resumable** — Progress is saved to the committed cache; an interrupted run picks up where it stopped.
- **Public or private** — Your choice at creation; host under an org to share with a team.
- **SEO-aware extraction** — Prefers `<meta>` tags over LLM extraction for title and description.
- **Source citations** — Every answer links back to the original page URL.

---

## Cost

Powered by [Firecrawl](https://firecrawl.dev):

| Operation | Credits |
|-----------|---------|
| Map (per run) | 1 |
| Scrape (per page) | ~5 |
| 100-page site | ~501 total |

Incremental re-runs only pay for new pages. `--skip-scrape` costs 0 credits.

---

## Requirements

- Python 3.8+ (the bundled `preflight.py` auto-installs `requests`, `pydantic`, `tenacity`)
- [`gh`](https://cli.github.com) CLI, authenticated (`gh auth login`)
- [Node.js](https://nodejs.org) (for `npx skills add`)
- [Firecrawl](https://firecrawl.dev) API key

---

## License

[MIT](LICENSE) — free to use, modify, and distribute.
