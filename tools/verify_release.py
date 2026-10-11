"""Download the published release asset and verify it runs.

Uses the project's own transport (radio.net / radio.proxy) so the same TLS and
proxy handling that makes the app work is used to fetch the artifact.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
import time
import zipfile

sys.path.insert(0, r"E:\KU\AI\deepseek-harness\network-radio")
from radio.net import open_stream  # noqa: E402
from radio.proxy import system_proxy  # noqa: E402

URL = "https://github.com/martjay/network-radio/releases/download/v1.0.0/Broadcast-1.0.0-win64.zip"
DEST = os.path.join(tempfile.gettempdir(), "bcast_release.zip")
EXTRACT = os.path.join(tempfile.gettempdir(), "bcast_release_check")

proxy = system_proxy()
print(f"proxy: {proxy.describe()}")

t0 = time.time()
r = open_stream(URL, timeout=30, proxy=proxy)
total = 0
h = hashlib.sha256()
with open(DEST, "wb") as fh:
    while True:
        chunk = r.read(65536)
        if not chunk:
            break
        fh.write(chunk)
        h.update(chunk)
        total += len(chunk)
        if total % (20 * 1024 * 1024) < 65536:
            print(f"  {total/1048576:6.1f} MB ...", flush=True)
r.close()

size = os.path.getsize(DEST)
print(f"\ndownloaded {size/1048576:.1f} MB in {time.time()-t0:.0f}s")
print(f"sha256   {h.hexdigest()}")

print("\nextracting ...")
if os.path.isdir(EXTRACT):
    import shutil
    shutil.rmtree(EXTRACT, ignore_errors=True)
os.makedirs(EXTRACT, exist_ok=True)
with zipfile.ZipFile(DEST) as z:
    names = z.namelist()
    z.extractall(EXTRACT)
print(f"  {len(names)} entries")

exe = os.path.join(EXTRACT, "Broadcast.exe")
print(f"  Broadcast.exe present: {os.path.isfile(exe)}")

print("\nrunning --selftest on the downloaded build ...")
p = subprocess.run([exe, "--selftest"], capture_output=True, text=True, timeout=180)
for line in p.stdout.strip().splitlines():
    print("   ", line)
print(f"  exit code: {p.returncode}")

print("\nrunning --playtest (live station through the packaged decoder) ...")
p2 = subprocess.run([exe, "--playtest"], capture_output=True, text=True, timeout=180)
for line in p2.stdout.strip().splitlines():
    print("   ", line)
print(f"  exit code: {p2.returncode}")

ok = p.returncode == 0 and p2.returncode == 0
print("\n" + ("DOWNLOADED ARTIFACT VERIFIED OK" if ok else "VERIFICATION FAILED"))
sys.exit(0 if ok else 1)
