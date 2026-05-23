#!/usr/bin/env python3
"""
Environment pre-flight for website-to-skill-folder.
=================================================
Run this BEFORE the pipeline. It probes the environment, auto-fixes what it
safely can (with --fix), and prints clear guidance for the rest — so the user
is never left with a cryptic mid-run failure or a wasted Firecrawl charge.

Stdlib-only on purpose: it must run even when the pipeline's own dependencies
(requests/pydantic/tenacity) are missing, since reporting that is its job.

Each check is tagged:
  OK     — present, nothing to do
  FIX    — auto-fixable; re-run with --fix (or run the printed command)
  GUIDE  — you need to run a command / install something (we give the exact one)
  ASK    — you need to provide a value at runtime (e.g. the Firecrawl API key)

Exit code:
  0  READY    — nothing blocking (ASK items are provided at runtime, not failures)
  1  BLOCKED  — required tools missing/misconfigured; resolve before running

Usage:
  python preflight.py            # report
  python preflight.py --fix      # install missing Python packages, then report
"""

import argparse
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Force UTF-8 on stdout/stderr so the report's em-dashes render correctly (and never
# crash with UnicodeEncodeError) on Windows consoles defaulting to cp1252. No-op where
# stdout is already UTF-8 or not reconfigurable.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

PACKAGES = ["requests", "pydantic", "tenacity"]

TAGS = {"ok": "OK", "fix": "FIX", "guide": "GUIDE", "ask": "ASK"}


def _run(cmd: list[str]) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    except (FileNotFoundError, OSError):
        return None


def missing_packages() -> list[str]:
    return [p for p in PACKAGES if importlib.util.find_spec(p) is None]


def git_installed() -> bool:
    return shutil.which("git") is not None


def git_identity() -> tuple[bool, str, str]:
    """Return (configured, name, email) from effective git config."""
    if not git_installed():
        return (False, "", "")
    n = _run(["git", "config", "user.name"])
    e = _run(["git", "config", "user.email"])
    name = n.stdout.strip() if n and n.returncode == 0 else ""
    email = e.stdout.strip() if e and e.returncode == 0 else ""
    return (bool(name and email), name, email)


def gh_installed() -> bool:
    return shutil.which("gh") is not None


def gh_auth() -> tuple[bool, str | None]:
    """Return (authenticated, login). login is the gh account name if known."""
    if not gh_installed():
        return (False, None)
    status = _run(["gh", "auth", "status"])
    authed = status is not None and status.returncode == 0
    login = None
    if authed:
        u = _run(["gh", "api", "user", "--jq", ".login"])
        if u and u.returncode == 0:
            login = u.stdout.strip() or None
    return (authed, login)


def node_available() -> bool:
    return shutil.which("npx") is not None and shutil.which("node") is not None


def firecrawl_key_present() -> bool:
    if os.environ.get("FIRECRAWL_API_KEY", "").strip():
        return True
    env_local = Path(__file__).parent / ".env.local"
    if env_local.exists():
        try:
            for line in env_local.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("FIRECRAWL_API_KEY") and "=" in line:
                    _, val = line.split("=", 1)
                    if val.strip().strip('"').strip("'"):
                        return True
        except OSError:
            pass
    creds = os.path.join(os.environ.get("APPDATA", ""), "firecrawl-cli", "credentials.json")
    if os.path.exists(creds):
        try:
            import json
            data = json.load(open(creds, encoding="utf-8"))
            if data.get("apiKey") or data.get("api_key") or data.get("key"):
                return True
        except (OSError, ValueError):
            pass
    return False


def install_hint(tool: str) -> str:
    """Platform-aware install guidance."""
    plat = sys.platform
    if tool == "gh":
        url = "https://cli.github.com"
        if plat == "darwin":
            return f"brew install gh   (or {url})"
        if plat == "win32":
            return f"winget install --id GitHub.cli   (or {url})"
        if plat.startswith("linux"):
            return f"{url}  (Debian/Ubuntu: install via GitHub's apt repo)"
        return url
    if tool == "node":
        url = "https://nodejs.org"
        if plat == "darwin":
            return f"brew install node   (or {url})"
        if plat == "win32":
            return f"winget install --id OpenJS.NodeJS   (or {url})"
        if plat.startswith("linux"):
            return f"{url}  (or e.g. sudo apt install nodejs npm)"
        return url
    if tool == "git":
        return "https://git-scm.com/downloads"
    return ""


def collect() -> list[dict]:
    """Probe the environment; return a list of check-result dicts."""
    checks: list[dict] = []

    # Python version
    v = sys.version_info
    py_ok = v >= (3, 8)
    checks.append({
        "key": "python",
        "label": f"Python {v.major}.{v.minor} (need 3.8+)",
        "status": "ok" if py_ok else "guide",
        "message": "" if py_ok else "Python 3.8+ is required",
        "action": "" if py_ok else "Install Python 3.8+ from https://python.org",
    })

    # Python packages
    miss = missing_packages()
    checks.append({
        "key": "packages",
        "label": "Python packages (requests, pydantic, tenacity)",
        "status": "ok" if not miss else "fix",
        "message": "" if not miss else f"missing: {', '.join(miss)}",
        "action": "" if not miss else (
            f"{sys.executable} -m pip install {' '.join(PACKAGES)}"
            "   (or re-run me with --fix)"
        ),
    })

    # git + identity
    if not git_installed():
        checks.append({
            "key": "git", "label": "git", "status": "guide",
            "message": "not found",
            "action": f"Install git: {install_hint('git')}",
        })
    else:
        ok, name, email = git_identity()
        if ok:
            checks.append({
                "key": "git",
                "label": f"git + commit identity ({name} <{email}>)",
                "status": "ok", "message": "", "action": "",
            })
        else:
            checks.append({
                "key": "git", "label": "git commit identity", "status": "guide",
                "message": "user.name / user.email not set — commits would fail",
                "action": (
                    'git config --global user.name "Your Name" && '
                    'git config --global user.email "you@example.com"'
                ),
            })

    # GitHub CLI + auth (the repo is hosted on GitHub, so this is required)
    if not gh_installed():
        checks.append({
            "key": "gh", "label": "GitHub CLI (gh)", "status": "guide",
            "message": "not found",
            "action": f"Install: {install_hint('gh')}  — then run: gh auth login",
        })
    else:
        authed, login = gh_auth()
        if authed:
            who = f"authenticated as {login}" if login else "authenticated"
            extra = (
                f"new skill repos will be created under github.com/{login}"
                if login else ""
            )
            checks.append({
                "key": "gh", "label": f"GitHub CLI (gh) — {who}",
                "status": "ok", "message": "", "action": extra,
            })
        else:
            checks.append({
                "key": "gh", "label": "GitHub CLI (gh) — not authenticated",
                "status": "guide", "message": "",
                "action": "Run: gh auth login",
            })

    # Node / npx (needed to install the produced skill; optional with --no-install)
    if node_available():
        checks.append({
            "key": "node", "label": "Node.js / npx (to install the skill)",
            "status": "ok", "message": "", "action": "",
        })
    else:
        checks.append({
            "key": "node", "label": "Node.js / npx (to install the skill)",
            "status": "guide", "message": "not found",
            "action": (
                f"Install: {install_hint('node')}"
                "  — or run the pipeline with --no-install"
            ),
        })

    # Firecrawl API key (provided at runtime; not a hard block)
    if firecrawl_key_present():
        checks.append({
            "key": "firecrawl", "label": "Firecrawl API key", "status": "ok",
            "message": "found", "action": "",
        })
    else:
        checks.append({
            "key": "firecrawl", "label": "Firecrawl API key", "status": "ask",
            "message": "not found",
            "action": (
                'Provide it at runtime: FIRECRAWL_API_KEY="fc-..."'
                "  (free key at https://firecrawl.dev)"
            ),
        })

    return checks


def report(checks: list[dict]) -> int:
    """Print the report and return the process exit code (0 ready, 1 blocked)."""
    print("=" * 60)
    print("website-to-skill-folder — environment pre-flight")
    print("=" * 60)
    for c in checks:
        print(f"  [{TAGS[c['status']]:5}] {c['label']}")
        if c["message"]:
            print(f"          {c['message']}")
        if c["action"]:
            print(f"          -> {c['action']}")

    # node is the only non-blocking GUIDE (the pipeline can run with --no-install)
    blocking = [c for c in checks if c["status"] in ("fix", "guide") and c["key"] != "node"]
    asks = [c for c in checks if c["status"] == "ask"]
    node_missing = any(c["key"] == "node" and c["status"] != "ok" for c in checks)

    print("-" * 60)
    if blocking:
        print("  VERDICT: BLOCKED")
        print("  Resolve the [FIX]/[GUIDE] items above, then re-run preflight.")
        print("  Tip: `python preflight.py --fix` installs the Python packages for you.")
    else:
        print("  VERDICT: READY")
        need = (["Firecrawl API key"] if asks else []) + ["target website URL"]
        print(f"  Need from you to run: {', '.join(need)}")
        if node_missing:
            print("  Note: Node.js is missing — run the pipeline with --no-install,")
            print("        or install Node so the skill auto-installs after the push.")
    print("=" * 60)
    return 1 if blocking else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Environment pre-flight for website-to-skill-folder.",
    )
    ap.add_argument(
        "--fix", action="store_true",
        help="Auto-install missing Python packages, then report.",
    )
    args = ap.parse_args(argv)

    if args.fix:
        miss = missing_packages()
        if miss:
            print(f"Auto-fixing: installing {', '.join(PACKAGES)} ...")
            subprocess.run([sys.executable, "-m", "pip", "install", *PACKAGES])
            print()
        else:
            print("Nothing to fix: Python packages already present.\n")

    return report(collect())


if __name__ == "__main__":
    sys.exit(main())
