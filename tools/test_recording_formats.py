"""Verify the recording fix across the stream formats in the catalogue.

The reported failure was an Ogg/Opus station recorded into an .mp3 file.
About a quarter of the catalogue is AAC/Opus/Vorbis, so this checks every
source format the app can encounter.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, r"E:\KU\AI\deepseek-harness\network-radio")
from radio.net import open_stream  # noqa: E402
from radio.proxy import system_proxy  # noqa: E402
from radio.recorder import CREATE_NO_WINDOW, Recorder, ffmpeg_path  # noqa: E402

OUT = tempfile.mkdtemp(prefix="bcast_fix_")
PROXY = system_proxy()

# One station per source format.
CASES = [
    ("Ogg/Opus  (container: needs priming)", "https://listen.moe/kpop/stream", "mp3"),
    ("MP3       (raw frames: no priming)", "https://ice5.somafm.com/reggae-256-mp3", "mp3"),
    ("MP3       (another, 128k)", "https://ice1.somafm.com/groovesalad-128-mp3", "aac"),
    ("AAC/Opus  (mixed catalogue)", "https://listen.moe/stream", "mp3"),
]

fails = []


def record(url: str, requested: str, seconds: float = 8.0) -> tuple[Recorder, str, int]:
    r = open_stream(url, timeout=20, proxy=PROXY)
    rec = Recorder(directory=OUT, filename=f"rec_{abs(hash(url)) % 10000}.{requested}",
                   source_url=url, title="test", bitrate_kbps=192,
                   container=requested, auto_container=True)
    rec.start()
    t0 = time.time()
    fed = 0
    while time.time() - t0 < seconds:
        d = r.read(16384)
        if not d:
            break
        rec.write(d)
        fed += len(d)
    r.close()
    path = rec.stop()
    return rec, path, fed


def decodes(path: str) -> tuple[bool, str]:
    if not path or not os.path.exists(path):
        return False, "no file"
    if os.path.getsize(path) == 0:
        return False, "0 bytes"
    p = subprocess.run([ffmpeg_path(), "-hide_banner", "-v", "error", "-i", path,
                        "-f", "null", "-"], capture_output=True, timeout=90,
                       creationflags=CREATE_NO_WINDOW)
    err = p.stderr.decode("utf-8", "replace").strip()
    return (p.returncode == 0 and not err), err[:110]


for label, url, requested in CASES:
    print(f"\n=== {label} ===")
    print(f"  url={url}  requested={requested}")
    try:
        rec, path, fed = record(url, requested)
    except Exception as exc:  # noqa: BLE001
        print(f"  EXCEPTION: {exc}")
        fails.append(label)
        continue

    name = os.path.basename(path) if path else "(none)"
    size = os.path.getsize(path) if path and os.path.exists(path) else 0
    print(f"  source format : {rec.source}")
    print(f"  container     : {rec.container}  (transcoded={rec.transcoded})")
    print(f"  file          : {name}  {size/1024:.1f} KB")
    print(f"  recorder error: {rec.error[:80] or '(none)'}")
    ok, err = decodes(path)
    print(f"  decodes       : {ok}  {'' if ok else err}")
    if not ok:
        fails.append(label)

print()
if fails:
    print(f"FAILED: {', '.join(fails)}")
    sys.exit(1)
print("all formats record and decode correctly")
print(f"files in {OUT}")
