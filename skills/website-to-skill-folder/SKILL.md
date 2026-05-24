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
pages that disappeared from the site), and pushes it back. Installing it locally
via `npx skills add` is a quick, opt-in last step (Step 5). The temp directory is
deleted afterward — nothing durable is left on the local machine, and the folder you
run from is never touched. Re-running the same command later updates the same repo.

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

> Use `python3` instead of `python` if `python` is missing (common on macOS/Linux), and
> use the **same interpreter** for every command in this guide.

```bash
python "$SKILL_DIR/scripts/preflight.py"
```

Each line is tagged: `[OK]`, `[FIX]` (auto-fixable), `[GUIDE]` (a command to run), or
`[ASK]` (a value to provide at runtime). Act on the `VERDICT`:

- **`VERDICT: READY`** → proceed to the cost estimate (Step 3). Ask the user for the
  minimum needed to dry-run: the **target URL** and the **Firecrawl API key** (only if
  it's tagged `[ASK]`). Visibility and owner are decided just before the run (Step 4).
  If the report shows `gh authenticated as <name>`, that's the account the repo lands under.

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

## 3. Estimate Cost First (dry-run)

**How the pipeline handles URLs:** It extracts the domain from any URL. A path like
`/blog` or `/docs/api` is ignored — the **full domain** is always crawled. Subdomains
like `blog.example.com` ARE different domains and produce separate skills. Do not try to
limit to a subdirectory or grep the URL list.

**Always run `--dry-run` first** to discover the page count and cost (≤1 map credit). It
syncs with GitHub too, so for an existing repo it reports only *new* pages — **a dry-run
creates and changes nothing** on GitHub.

> **About the key prefix:** only inline `FIRECRAWL_API_KEY="..."` (with the user's real
> key) when pre-flight tagged the key `[ASK]`. If it was `[OK]`, the key is already
> configured — **omit the prefix entirely**; passing a placeholder would override the real
> key and cause a 401. This applies to every command below, including the run in Step 4.

```bash
FIRECRAWL_API_KEY="fc-key" python "$SKILL_DIR/scripts/pipeline.py" https://example.com --dry-run
# with a page cap:
FIRECRAWL_API_KEY="fc-key" python "$SKILL_DIR/scripts/pipeline.py" https://example.com --dry-run --max-pages 50
```

Read `Total URLs`, `New`, any `Backfill` line, and the estimated cost; present them and
continue only once the user approves the spend. Notes:

- **"Already up to date"** in the summary (0 new, 0 backfill, 0 deleted) means the skill is
  current — tell the user and **stop**. Don't run, don't prompt for a spend.
- **A `Backfill: N` line** means N pages were mapped on an earlier run but never scraped
  (e.g. a prior `--max-pages` run). The real run *will* scrape them and the estimate already
  includes them — so the credit figure can be much larger than `New` alone implies. Relay the
  total, not just the new-page count.
- **`--max-pages N` keeps the first N URLs in map order — not a curated "most important" set,
  and map order can drift slightly between runs.** Capping a large site leaves the remaining
  pages to be backfilled on a later uncapped run. Only cap when the user explicitly wants to
  limit cost or size.

## 4. Run the Pipeline

**New vs. update is decided by whether the GitHub repo exists** — the dry-run already showed
this (it printed `GitHub repo: …` and either cloned it or said it "will create" the repo).
Do NOT infer it from whether the skill is installed locally: a local install can exist for a
repo that was since deleted.

For a **brand-new** skill, confirm just the one undecided axis: **private** (default) or
**public**? (Public installs need no auth; private needs repo access. `--visibility public`
for public; `--owner <org>` to host under a shared org.) For an **update** to a repo that
already exists, **don't re-ask** — visibility is fixed; just run.

Don't re-ask the **page cap** if the user already gave one, and don't bundle the cap into the
visibility question — they're independent axes. Ask visibility on its own; treat a cap the
user already stated as settled.

Run it non-interactively so nothing blocks the terminal. Pass `--yes` (auto-approves the
cost you already previewed) and **`--no-install`** — the run pushes to GitHub now; installing
locally is a separate, opt-in step you handle in Step 5:

```bash
# default: private, the authenticated account
FIRECRAWL_API_KEY="fc-their_key" python "$SKILL_DIR/scripts/pipeline.py" https://example.com --yes --no-install
# public, under an org
FIRECRAWL_API_KEY="fc-their_key" python "$SKILL_DIR/scripts/pipeline.py" https://example.com --yes --no-install --visibility public --owner my-org
```

The run clones (or creates) `github.com/{owner}/skill-folder-{skill_name}`, scrapes only new
pages, deletes pages removed from the site, and **pushes** — fast, no prompts, nothing
installed on the machine yet.

**IMPORTANT:**
- Always pass `--yes` and `--no-install` from an agent: the run stays non-interactive and
  doesn't touch the user's machine. You install conversationally in Step 5 — don't make the
  user wait at a terminal prompt.
- `--visibility` only applies when the repo is first created; it's ignored on later updates.
- Set a **10-minute timeout** on the Bash call (e.g. `timeout: 600000`). Large sites take
  several minutes (scraping + API polling).

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
| `--allow-mass-deletion` | Bypass the safety guard that blocks deletions when a map run would remove ≥30% of known pages. Use only for a *real* mass removal or site migration |
| `--no-install` | Push to GitHub but skip the npx install step |
| `--work-dir PATH` | Use a persistent local dir instead of a temp dir (debugging) |
| `--keep-temp` | Keep the temp working dir after the run (debugging) |

## 5. Summarize, Then Install on Request

The run prints a `DONE` block with the repo URL + visibility, the install command, the
share command, and the update command. Give the user a short, flow-aware summary:

- **Always:** "Done — your {domain} skill is live at {repo_url} ({visibility})."
- **Public repo:** add "Anyone can install it — share this: `npx skills add {owner}/skill-folder-{skill_name} -g --all`."
- **Private repo:** add "To share, give teammates repo access (or host under an org), then they run the same command."

Then ask **once**: *"Want me to install it on this machine now so you can use it?"*

If **yes**, install it from GitHub:

```bash
npx skills add {owner}/skill-folder-{skill_name} -g --all
```

Then **validate** it actually landed — don't trust the exit code alone. Run the check as its
**own** Bash call so its one-line result isn't buried in the `npx` spinner output:

```bash
ls "$HOME/.agents/skills/{skill_name}/SKILL.md" >/dev/null 2>&1 && echo "INSTALLED" || echo "NOT FOUND"
```

- **INSTALLED** → "All set ✓ — the {domain} search skill is installed. Open a **new session**
  and just ask me about {domain} (e.g. *'what does {domain} say about pricing?'*). I'll search
  it offline and cite the source pages."
- **NOT FOUND** → share the manual command, confirm Node is present (`node --version`), and
  see Troubleshooting.

The real skill lives in `~/.agents/skills/{skill_name}/`; each agent (Claude Code, etc.) gets
a symlink into it. If the user asks specifically about the **Claude Code symlink** (or "is it
wired into Claude Code / a new session?"), confirm it resolves:

```bash
readlink "$HOME/.claude/skills/{skill_name}" 2>/dev/null && echo "symlink OK" || echo "Claude Code reads ~/.agents directly"
```

If **no**, leave it — the skill is safe on GitHub and can be installed any time with the
command above. (Repo URL → `{owner}/skill-folder-{skill_name}`; the skill installs to
`~/.agents/skills/{skill_name}/`. `{skill_name}` is the domain with dots as hyphens, e.g.
`example.com` → `example-com-website-search-skill`.)

**Updating later** is the same run (Step 4, no need to re-ask visibility). For the install
step, check first: if `~/.agents/skills/{skill_name}/` already exists, just reinstall
silently to refresh it — don't re-ask. Only ask when it isn't installed yet.

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
The pipeline tracks URLs that vanish from the map and deletes their page files only after
3 consecutive runs confirm them gone (guards against transient crawl failures).

**Saw a `[SYNC GUARD]` warning, or expected deletions didn't happen?**
A circuit breaker treats a map as untrustworthy when a single run would remove ≥30% of known
pages (or returns 0 URLs against a non-empty cache) — almost always a glitch: the site was down,
behind an anti-bot/maintenance page, or its sitemap broke. On an untrusted run the pipeline keeps
the last-known-good page set, scrapes only genuinely-new URLs, and takes **no** deletions. If the
removal was real (a deliberate purge or a site migration), re-run with `--allow-mass-deletion`.

**"Map returned 0 URLs … skill would be empty" error?**
A first run found no pages and has no cache to fall back on — usually a wrong domain, an outage, or
a site that blocks crawling. Verify the URL in a browser; the pipeline refuses to publish an empty skill.

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
