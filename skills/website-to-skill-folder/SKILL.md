---
name: website-to-skill-folder
description: >
  Converts any website into an installable AI skill folder by crawling all pages
  and packaging them as searchable markdown with frontmatter summaries. Use when
  asked to: create a website search skill, index a website for AI agents, scrape
  a site into a searchable knowledge base, turn a website into an offline-searchable
  skill, make website content available to AI agents without live browsing, crawl
  a site, download a website for AI, convert website to markdown, build a knowledge
  base from a URL, or make a site searchable offline. Also use when the user provides
  a URL and wants it indexed, wants offline docs from a live site, or asks to
  "turn this website into a skill". The skill is hosted in the user's GitHub
  account and installed from there via npx.
---

# Website-to-Skill Pipeline

Runs `scripts/pipeline.py` to crawl a website and produce an installable skill folder.
The script handles everything — no need to read it.

**GitHub is the source of truth.** Each run clones the user's skill repo from
GitHub into a temp directory, updates it incrementally (scrape new pages, delete
pages that disappeared from the site), pushes it back, and installs it via
`npx skills add`. The temp directory is deleted afterward — nothing durable is
left on the local machine. Re-running the same command later updates the same repo.

## 1. Locate the Skill

```bash
SKILL_DIR="$HOME/.agents/skills/website-to-skill-folder"
[ -d "$SKILL_DIR" ] || SKILL_DIR=$(find "$HOME/.agents/skills" "$HOME/.claude/skills" \
  -maxdepth 2 -type d -name "website-to-skill-folder" 2>/dev/null | head -1)
echo "Skill dir: $SKILL_DIR"
```

## 2. Pre-flight — run one check, then act on it

Don't probe tools one-by-one. Run the bundled pre-flight script **once**. It checks
everything (Python, packages, git + identity, `gh` + auth, Node/npx, Firecrawl key) and
prints a tagged report with a final `VERDICT`.

```bash
python "$SKILL_DIR/scripts/preflight.py"
```

Each line is tagged: `[OK]`, `[FIX]` (auto-fixable), `[GUIDE]` (a command to run), or
`[ASK]` (a value to provide at runtime). Act on the `VERDICT`:

- **`VERDICT: READY`** → proceed. Ask the user only for the minimum: the **target URL**,
  the **Firecrawl API key** (only if it's tagged `[ASK]`), and their **public/private**
  preference. If the report shows `gh authenticated as <name>`, tell the user the repo
  will be created under that account (or offer `--owner <org>`).

- **`VERDICT: BLOCKED`** → help the user clear each flagged item, then re-run preflight:
  - `[FIX]` Python packages → offer to run it for them: `python "$SKILL_DIR/scripts/preflight.py" --fix`
  - `[GUIDE]` git identity → if they give you a name/email, run the printed
    `git config --global ...` commands for them.
  - `[GUIDE]` `gh` not installed → share the printed install command for their OS.
  - `[GUIDE]` `gh` not authenticated → ask the user to run `gh auth login` themselves
    (it's interactive — you can't do it for them).
  - `[GUIDE]` Node missing → either help install it, or note you'll run with `--no-install`.

  **Do not run the pipeline while BLOCKED** — it will fail or waste Firecrawl credits.

Be proactive but not noisy: when everything is `OK`, just confirm you're set and ask for
the URL + key. Only surface setup steps for the items that are actually missing.

When you need the key, ask in one line: "What website do you want to convert, and what's
your Firecrawl API key? Get a free key at https://firecrawl.dev — no credit card required."

> The pipeline self-checks too: if it's run with a tool missing, it exits with the same
> guidance instead of a stack trace. Pre-flight just lets you catch everything up front.

## 3. Confirm Visibility and Scope

Before running, confirm two things with the user (skip whichever they've already specified):

1. **Visibility** — should the GitHub skill repo be **private** (default) or **public**?
   Public repos can be installed by teammates with no auth; private repos require each
   teammate to have GitHub access. To share with a team, you can also create the repo
   under an org with `--owner <org>`.
2. **Owner** — defaults to their own GitHub account. Use `--owner <org-or-user>` to host
   it elsewhere (e.g. a shared org).

**How the pipeline handles URLs:** It extracts the domain from any URL. A path like
`/blog` or `/docs/api` is ignored — the **full domain** is always crawled. Subdomains
like `blog.example.com` ARE different domains and produce separate skills.

**Always run `--dry-run` first** to discover the page count and cost (costs 1 map credit).
The dry-run also syncs with GitHub, so for an existing repo it reports only *new* pages.

```bash
FIRECRAWL_API_KEY="fc-key" python "$SKILL_DIR/scripts/pipeline.py" https://example.com --dry-run
# with a page limit:
FIRECRAWL_API_KEY="fc-key" python "$SKILL_DIR/scripts/pipeline.py" https://example.com --dry-run --max-pages 50
```

Read `Total URLs` / `New` and the estimated cost, present them to the user, and only
proceed after they approve.

## 4. Run the Pipeline

Inline the skill path and API key so the command is self-contained. Use `--yes` when
running as an agent (it auto-approves the cost prompt AND defaults new repos to private).

```bash
FIRECRAWL_API_KEY="fc-their_key" python "$SKILL_DIR/scripts/pipeline.py" https://example.com --yes
```

To make a new repo public, or host it under an org:

```bash
FIRECRAWL_API_KEY="fc-their_key" python "$SKILL_DIR/scripts/pipeline.py" https://example.com --yes --visibility public
FIRECRAWL_API_KEY="fc-their_key" python "$SKILL_DIR/scripts/pipeline.py" https://example.com --yes --owner my-org
```

The pipeline clones (or creates) `github.com/{owner}/skill-folder-{skill_name}`, updates it,
pushes, and installs it — all in one run.

**IMPORTANT:**
- Always include `--yes` when running from an AI agent. Without it, the pipeline prompts
  for interactive cost and visibility confirmation, which will time out and cancel the run.
- `--visibility` only applies when the repo is created the first time; it's ignored on
  later updates (visibility is managed on GitHub after that).
- Set a **10-minute timeout** on the Bash call. Example: `timeout: 600000` in tool params.

**Options:**

| Flag | Purpose |
|------|---------|
| `--owner NAME` | GitHub account/org to own the repo (default: the authenticated gh user) |
| `--visibility public\|private` | Visibility for a **new** repo (default: private). Ignored on updates |
| `--description "..."` | One-line site description for the generated SKILL.md |
| `--max-pages N` | Limit pages scraped — directly controls Firecrawl credit cost |
| `--yes` / `-y` | **Always use from agents.** Auto-approve cost + visibility prompts |
| `--dry-run` | Sync + map + show cost estimate, then exit (no scrape, no push) |
| `--skip-scrape` | Rebuild the skill from the repo's committed cache and push — no scrape, no Firecrawl key |
| `--force-refresh` | Ignore cache, re-scrape all pages |
| `--no-install` | Push to GitHub but skip the npx install step |
| `--work-dir PATH` | Use a persistent local dir instead of a temp dir (debugging) |

## 5. After the Run

The pipeline ends with a `DONE` block containing everything needed — relay it to the
user, don't paraphrase the commands. It includes:

- **Repo URL + visibility** (e.g. `https://github.com/{owner}/skill-folder-{skill_name}  (private)`).
  The repo also has a generated `README.md` landing page with the same install/share info.
- **Install status** — unless `--no-install`, the skill is already installed at
  `~/.agents/skills/{skill_name}/`, so the user's agents can search the site offline now.
- **Share command** — the single `npx skills add {owner}/skill-folder-{skill_name} -g --all`
  to hand to teammates.

Report it to the user roughly like this:

> "Done — your {domain} skill is live at {repo_url} ({visibility}) and installed locally.
> To share it, send teammates: `npx skills add {owner}/skill-folder-{skill_name} -g --all`
> — {public: anyone can run it / private: they'll need read access to the repo first}.
> Re-run me any time to update it; I'll only scrape new pages."

If the repo is **private** and the user wants teammates to install it, remind them to grant
access (add collaborators, or have used `--owner <org>` so the team already has access).
If they want a **public**, no-auth-needed share link, the repo can be recreated with
`--visibility public` (or flipped on GitHub).

## Troubleshooting & Recovery

**Pipeline crashed or timed out mid-scrape?**
Just rerun the same command. Progress is saved after each batch to the committed
`dev/_workspace/state.json`; completed batches are skipped — you only pay for the rest.

**Want to rebuild the skill folder without re-scraping?**
Use `--skip-scrape`. It clones the repo, reassembles from the committed cache (zero
Firecrawl credits, no API key needed), and pushes. Useful after a template change.

**Pages seem stale or site was redesigned?**
Use `--force-refresh` to ignore the cache and re-scrape everything.

**Pages disappeared from the site?**
The pipeline tracks URLs that vanish from the map and deletes their page files after
3 consecutive runs confirm them gone (guards against transient crawl failures).

**`gh` auth or push errors?**
Run `gh auth status`; if not logged in, `gh auth login`. The owner must have permission
to create/push the repo (use `--owner` for orgs you can write to).

**Firecrawl rate limit (HTTP 429)?**
The pipeline retries with exponential backoff. If it still fails, wait and rerun —
cached batches won't repeat.

**"API key missing" or 401?**
Check the key starts with `fc-`. Get a free key at https://firecrawl.dev.

## Cost

1 Firecrawl credit (map) + ~5 credits per page scraped.
Example: 100-page site ≈ 501 credits. Incremental re-runs only pay for new pages.
`--skip-scrape` costs 0 credits.
