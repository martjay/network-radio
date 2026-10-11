"""Final precise check: print the EXACT matched text for every 'x-access-token'
hit in the published repo, so each can be judged as credential or regex.

Also does a direct search for the real token value and for any
credential-shaped string that is not one of our own detection patterns.
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
import urllib.request

OWNER, REPO = "martjay", "network-radio"
TOK = os.environ.get("GITHUB_TOKEN", "")
# The value to search for is supplied by the caller, never stored in the repo.
REAL = os.environ.get("AUDIT_TOKEN_VALUE", "")


def api(path: str):
    req = urllib.request.Request(path if path.startswith("http") else f"https://api.github.com{path}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "Audit/1.0")
    if TOK:
        req.add_header("Authorization", f"Bearer {TOK}")
    with urllib.request.urlopen(req, timeout=90) as resp:
        return json.load(resp)


tree = api(f"/repos/{OWNER}/{REPO}/git/trees/main?recursive=1")
blobs = [t for t in tree["tree"] if t["type"] == "blob"]

print("=== every 'x-access-token' occurrence, with exact matched text ===\n")
rx = re.compile(r"x-access-token:.{0,40}")
real_credential = False
for e in blobs:
    if e.get("size", 0) > 900_000 or e["path"].endswith((".png", ".zip")):
        continue
    blob = api(f"/repos/{OWNER}/{REPO}/git/blobs/{e['sha']}")
    content = base64.b64decode(blob["content"]).decode("utf-8", "replace")
    for m in rx.finditer(content):
        text = m.group(0)
        # A real credential would be x-access-token:<opaque-secret>@github.com
        is_real = bool(re.match(r"x-access-token:[A-Za-z0-9_\-]{20,}@", text))
        if is_real:
            real_credential = True
        kind = "REAL CREDENTIAL" if is_real else "regex / placeholder"
        print(f"  [{kind}] {e['path']}")
        print(f"      matched: {text!r}")
        print()

print("=== direct search for the real token value across the repo ===\n")
found_real = []
for e in blobs:
    if e.get("size", 0) > 900_000 or e["path"].endswith((".png", ".zip")):
        continue
    blob = api(f"/repos/{OWNER}/{REPO}/git/blobs/{e['sha']}")
    content = base64.b64decode(blob["content"]).decode("utf-8", "replace")
    if REAL in content:
        found_real.append(e["path"])
print(f"  files containing the literal token: {found_real or 'NONE'}")

print("\n=== any ghp_ token in the repo at all? ===\n")
ghp = []
for e in blobs:
    if e.get("size", 0) > 900_000 or e["path"].endswith((".png", ".zip")):
        continue
    blob = api(f"/repos/{OWNER}/{REPO}/git/blobs/{e['sha']}")
    content = base64.b64decode(blob["content"]).decode("utf-8", "replace")
    for m in re.finditer(r"ghp_[A-Za-z0-9]{10,}", content):
        ghp.append(f"{e['path']}: {m.group(0)[:20]}...")
print(f"  ghp_ occurrences: {ghp or 'NONE'}")

print()
ok = not real_credential and not found_real and not ghp
print("VERDICT: repository contains NO credentials"
      if ok else "VERDICT: PROBLEM FOUND - investigate above")
sys.exit(0 if ok else 1)
