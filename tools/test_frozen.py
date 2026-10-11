"""Verify recording works in the FROZEN build, for both an MP3 station and the
Ogg/Opus station that was reported. The packaged build is what users run, and
the recorder shells out to ffmpeg, so this is where packaging could break it.
"""
from __future__ import annotations

import subprocess
import sys

EXE = r"E:\KU\AI\deepseek-harness\network-radio\dist\Broadcast\Broadcast.exe"

# The frozen build cannot import our test modules, so drive it through a small
# script executed by the packaged interpreter is not possible either. Instead
# use the app's own --playtest for playback and verify the recorder separately
# by checking the frozen self-test reports the recorder module healthy.
print("=== frozen --selftest ===")
p = subprocess.run([EXE, "--selftest"], capture_output=True, text=True, timeout=180)
out = p.stdout
for line in out.strip().splitlines():
    if any(k in line for k in ("recorder", "SELF-TEST", "FAIL", "icon", "tray", "dpi", "high-DPI")):
        print("  ", line.strip())
print(f"  exit: {p.returncode}")

print("\n=== frozen --playtest on the reported Opus station ===")
p2 = subprocess.run([EXE, "--playtest", "https://listen.moe/kpop/stream"],
                    capture_output=True, text=True, timeout=180)
for line in p2.stdout.strip().splitlines():
    print("  ", line.strip())
print(f"  exit: {p2.returncode}")

print("\n=== frozen --playtest on an MP3 station ===")
p3 = subprocess.run([EXE, "--playtest", "https://ice5.somafm.com/reggae-256-mp3"],
                    capture_output=True, text=True, timeout=180)
for line in p3.stdout.strip().splitlines():
    print("  ", line.strip())
print(f"  exit: {p3.returncode}")

print("\n=== frozen --rectest on the reported Opus station ===")
p4 = subprocess.run([EXE, "--rectest", "https://listen.moe/kpop/stream"],
                    capture_output=True, text=True, timeout=240)
for line in p4.stdout.strip().splitlines():
    print("  ", line.strip())
print(f"  exit: {p4.returncode}")

print("\n=== frozen --rectest on an MP3 station ===")
p5 = subprocess.run([EXE, "--rectest", "https://ice5.somafm.com/reggae-256-mp3"],
                    capture_output=True, text=True, timeout=240)
for line in p5.stdout.strip().splitlines():
    print("  ", line.strip())
print(f"  exit: {p5.returncode}")

ok = all(p.returncode == 0 for p in (p, p2, p3, p4, p5))
print("\n" + ("FROZEN BUILD OK" if ok else "FROZEN BUILD FAILED"))
sys.exit(0 if ok else 1)
