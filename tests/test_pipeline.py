"""Lightweight regression tests for pipeline.py (no pytest dependency).

Run from anywhere:  python tests/test_pipeline.py
Exits non-zero if any check fails. These guard the behaviors most likely to
regress silently — they do NOT hit the network (requests.post is monkeypatched).
"""
import os
import sys
import tempfile

_SCRIPTS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "skills", "website-to-skill-folder", "scripts",
)
sys.dont_write_bytecode = True
sys.path.insert(0, _SCRIPTS)
import pipeline  # noqa: E402

results = []


def check(name, cond, detail=""):
    results.append(cond)
    flag = "PASS" if cond else "FAIL"
    print(f"{flag}: {name}" + (f"  [{detail}]" if detail and not cond else ""))


# --- Map always requests a FRESH list (Firecrawl /map caches; a change-detection
#     tool must bypass that cache or it misses pages published moments ago). ---
captured = {}


class _FakeResp:
    status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return {"success": True, "links": ["https://x.com/a", "https://x.com/b"]}


def _fake_post(url, headers=None, json=None, timeout=None):
    captured["url"] = url
    captured["payload"] = json
    return _FakeResp()


pipeline.requests.post = _fake_post

pipeline.map_website("https://x.com", "fc-test", 100000, tempfile.mkdtemp())  # incremental
check("incremental map hits /v1/map", captured.get("url", "").endswith("/v1/map"), captured.get("url"))
check("incremental map sends ignoreCache=True", captured.get("payload", {}).get("ignoreCache") is True, str(captured.get("payload")))

captured.clear()
pipeline.map_website("https://x.com", "fc-test", 100000, tempfile.mkdtemp(), force_refresh=True)
check("force_refresh map sends ignoreCache=True", captured.get("payload", {}).get("ignoreCache") is True, str(captured.get("payload")))

# --- Pluralization of count-bearing output ("1 page", not "1 pages"). ---
check("_plural(1,'page') == '1 page'", pipeline._plural(1, "page") == "1 page", pipeline._plural(1, "page"))
check("_plural(2,'page') == '2 pages'", pipeline._plural(2, "page") == "2 pages", pipeline._plural(2, "page"))
check("_plural(0,'page') == '0 pages'", pipeline._plural(0, "page") == "0 pages", pipeline._plural(0, "page"))

passed = sum(results)
print(f"\n{'='*48}\n{passed}/{len(results)} passed")
sys.exit(0 if passed == len(results) else 1)
