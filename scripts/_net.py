"""Tiny shared helper: GET json with timeout, clear errors, never prints secrets."""
import json, sys, urllib.parse, urllib.request

def get_json(url, params=None, timeout=30):
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "fishmarket-ai-student-project"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:  # network blocked, 4xx, bad json
        sys.exit(f"Could not fetch {url}: {type(e).__name__}: {e}")
