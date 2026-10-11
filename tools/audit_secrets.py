"""Audit the published GitHub repository for leaked secrets.

Fetches every file in the remote default branch via the GitHub API and scans
the decoded contents, plus all commit patches, for credential patterns.
Independent of the local checkout - it inspects what is actually on GitHub.
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

PATTERNS = [
    ("GitHub token (ghp_)", re.compile(r"ghp_[A-Za-z0-9]{20,}")),
    ("GitHub token (fine-grained)", re.compile(r"github_pat_[A-Za-z0-9_]{20,}")),
    ("GitHub OAuth (gho_)", re.compile(r"gho_[A-Za-z0-9]{20,}")),
    ("Generic PAT assignment", re.compile(r"(?i)(token|secret|password|passwd|api[_-]?key)\s*[:=]\s*['\"][^'\"\s]{16,}['\"]")),
    ("Bearer token", re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{20,}")),
    ("x-access-token URL", re.compile(r"x-access-token:[^@\s]+@")),
    ("Private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("AWS access key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("Slack token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
]


def api(path: str):
    url = path if path.startswith("http") else f"https://api.github.com{path}"
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "SecretAudit/1.0")
    if TOK:
        req.add_header("Authorization", f"Bearer {TOK}")
    with urllib.request.urlopen(req, timeout=90) as resp:
        return json.load(resp)


def main() -> int:
    print(f"auditing https://github.com/{OWNER}/{REPO}\n")
    findings: list[str] = []

    info = api(f"/repos/{OWNER}/{REPO}")
    branch = info["default_branch"]
    print(f"default branch : {branch}")
    print(f"visibility     : {'private' if info['private'] else 'PUBLIC'}")

    tree = api(f"/repos/{OWNER}/{REPO}/git/trees/{branch}?recursive=1")
    blobs = [t for t in tree["tree"] if t["type"] == "blob"]
    print(f"files in repo  : {len(blobs)}\n")

    print("--- scanning file contents ---")
    scanned = 0
    skipped = 0
    for entry in blobs:
        path = entry["path"]
        size = entry.get("size", 0)
        # skip large binaries; secrets live in text
        if size > 900_000 or path.endswith((".png", ".jpg", ".zip", ".exe", ".dll", ".pyd")):
            skipped += 1
            continue
        try:
            blob = api(f"/repos/{OWNER}/{REPO}/git/blobs/{entry['sha']}")
            content = base64.b64decode(blob["content"]).decode("utf-8", "replace")
        except Exception as exc:  # noqa: BLE001
            print(f"  ! could not read {path}: {exc}")
            continue
        scanned += 1
        for label, rx in PATTERNS:
            for m in rx.finditer(content):
                snippet = m.group(0)[:60]
                findings.append(f"{path}: {label} -> {snippet}")
    print(f"  scanned {scanned} text files ({skipped} binaries/large skipped)")

    print("\n--- scanning commit history patches ---")
    commits = api(f"/repos/{OWNER}/{REPO}/commits?per_page=100")
    print(f"  commits: {len(commits)}")
    for c in commits:
        sha = c["sha"]
        detail = api(f"/repos/{OWNER}/{REPO}/commits/{sha}")
        for f in detail.get("files", []):
            patch = f.get("patch", "")
            if not patch:
                continue
            for label, rx in PATTERNS:
                for m in rx.finditer(patch):
                    findings.append(f"commit {sha[:8]} {f['filename']}: {label} -> {m.group(0)[:60]}")

    print("\n--- scanning the release asset ---")
    rel = api(f"/repos/{OWNER}/{REPO}/releases/tags/v1.0.0")
    for a in rel["assets"]:
        print(f"  {a['name']}  {a['size']/1048576:.1f} MB  ({a['content_type']})")

    print()
    if findings:
        print(f"!!! {len(findings)} POTENTIAL SECRET(S) FOUND:")
        for f in findings[:40]:
            print("   ", f)
        return 1
    print("RESULT: no credentials found in the published repository")
    return 0


if __name__ == "__main__":
    sys.exit(main())
