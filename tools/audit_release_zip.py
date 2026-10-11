"""Scan the published release ZIP for credentials, and check the remote for
any other refs, branches, or files that might hold one."""
from __future__ import annotations

import io
import json
import os
import re
import sys
import urllib.request
import zipfile

sys.path.insert(0, r"E:\KU\AI\deepseek-harness\network-radio")
from radio.net import open_stream  # noqa: E402
from radio.proxy import system_proxy  # noqa: E402

OWNER, REPO = "martjay", "network-radio"
TOK = os.environ.get("GITHUB_TOKEN", "")
URL = f"https://github.com/{OWNER}/{REPO}/releases/download/v1.0.0/Broadcast-1.0.0-win64.zip"

PATTERNS = [
    ("GitHub token", re.compile(rb"ghp_[A-Za-z0-9]{20,}")),
    ("fine-grained PAT", re.compile(rb"github_pat_[A-Za-z0-9_]{20,}")),
    ("x-access-token URL", re.compile(rb"x-access-token:[^@\s]{8,}@")),
    ("Bearer token", re.compile(rb"(?i)bearer\s+[A-Za-z0-9._\-]{20,}")),
    ("private key", re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("AWS key", re.compile(rb"AKIA[0-9A-Z]{16}")),
]


def api(path: str):
    req = urllib.request.Request(path if path.startswith("http") else f"https://api.github.com{path}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "SecretAudit/1.0")
    if TOK:
        req.add_header("Authorization", f"Bearer {TOK}")
    with urllib.request.urlopen(req, timeout=90) as resp:
        return json.load(resp)


print("=== 1. all refs on the remote ===")
refs = api(f"/repos/{OWNER}/{REPO}/git/refs")
for r in refs:
    print(f"  {r['ref']}  ->  {r['object']['sha'][:10]}")
print(f"  branches: {[b['name'] for b in api(f'/repos/{OWNER}/{REPO}/branches')]}")
print(f"  tags    : {[t['name'] for t in api(f'/repos/{OWNER}/{REPO}/tags')]}")

print("\n=== 2. all releases (any extra assets?) ===")
for rel in api(f"/repos/{OWNER}/{REPO}/releases"):
    print(f"  {rel['tag_name']}: {len(rel['assets'])} asset(s)")
    for a in rel["assets"]:
        print(f"      {a['name']}  {a['size']/1048576:.1f} MB")

print("\n=== 3. repo metadata that could leak a secret ===")
info = api(f"/repos/{OWNER}/{REPO}")
for field in ("description", "homepage", "has_pages", "deployments_url"):
    print(f"  {field}: {info.get(field)}")

print("\n=== 4. downloading and scanning the release ZIP ===")
proxy = system_proxy()
r = open_stream(URL, timeout=60, proxy=proxy)
buf = bytearray()
while True:
    chunk = r.read(262144)
    if not chunk:
        break
    buf += chunk
r.close()
print(f"  downloaded {len(buf)/1048576:.1f} MB")

z = zipfile.ZipFile(io.BytesIO(bytes(buf)))
names = z.namelist()
print(f"  entries: {len(names)}")

findings = []
text_ext = (".py", ".json", ".txt", ".md", ".cfg", ".ini", ".toml", ".bat", ".ps1", ".yml", ".yaml")
scanned = 0
for n in names:
    if not n.lower().endswith(text_ext):
        continue
    try:
        data = z.read(n)
    except Exception:  # noqa: BLE001
        continue
    scanned += 1
    for label, rx in PATTERNS:
        for m in rx.finditer(data):
            findings.append(f"{n}: {label} -> {m.group(0)[:70]!r}")

# also scan the raw bytes of every entry (catches secrets in any file type)
raw_scanned = 0
for n in names:
    info_z = z.getinfo(n)
    if info_z.file_size > 8_000_000:
        continue
    try:
        data = z.read(n)
    except Exception:  # noqa: BLE001
        continue
    raw_scanned += 1
    for label, rx in PATTERNS:
        for m in rx.finditer(data):
            findings.append(f"{n} (raw): {label} -> {m.group(0)[:70]!r}")

print(f"  text files scanned: {scanned}; all entries raw-scanned: {raw_scanned}")

print()
if findings:
    print(f"!!! {len(findings)} POTENTIAL SECRET(S) IN THE ZIP:")
    for f in findings[:30]:
        print("   ", f)
    sys.exit(1)
print("RESULT: release ZIP contains no credentials")
