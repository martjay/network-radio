"""Verify every candidate stream with ffprobe.

A station is kept only if ffprobe can open the stream AND decode at least one
real audio packet within the probe window. Results are merged back into
candidates.json (fields: ok, probe_error, real_codec, sample_rate, channels,
icy_name) so the picker can rank on hard evidence.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "candidates.json")
FFPROBE = os.environ.get("FFPROBE", "ffprobe")

TIMEOUT = 18  # seconds per station
WORKERS = 48

_print_lock = threading.Lock()
_counter = {"done": 0, "ok": 0, "total": 0}
_t0 = time.time()


def probe(url: str) -> dict:
    """Return {ok, error, codec, sample_rate, channels, icy_name}."""
    cmd = [
        FFPROBE,
        "-hide_banner",
        "-v", "error",
        "-rw_timeout", "14000000",
        "-probesize", "250000",
        "-analyzeduration", "3000000",
        "-icy", "1",
        "-show_entries",
        "stream=codec_type,codec_name,sample_rate,channels,bit_rate:format_tags=icy-name,icy-description,icy-genre,StreamTitle",
        "-of", "json",
        url,
    ]
    creation = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            timeout=TIMEOUT,
            creationflags=creation,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"spawn:{exc}"[:80]}

    raw = (p.stdout or b"").decode("utf-8", "replace").strip()
    if not raw:
        err = (p.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        return {"ok": False, "error": (err[-1][:110] if err else "no-output")}

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"ok": False, "error": "bad-json"}

    audio = [s for s in data.get("streams", []) if s.get("codec_type") == "audio"]
    if not audio:
        return {"ok": False, "error": "no-audio-stream"}
    a = audio[0]
    tags = data.get("format", {}).get("tags", {}) or {}
    return {
        "ok": True,
        "error": "",
        "codec": (a.get("codec_name") or "").lower(),
        "sample_rate": a.get("sample_rate") or "",
        "channels": a.get("channels") or 0,
        "bit_rate": a.get("bit_rate") or "",
        "icy_name": (tags.get("icy-name") or tags.get("StreamTitle") or "").strip(),
        "icy_genre": (tags.get("icy-genre") or "").strip(),
    }


def work(item: tuple[int, dict]) -> tuple[int, dict]:
    idx, rec = item
    res = probe(rec["url"])
    with _print_lock:
        _counter["done"] += 1
        if res["ok"]:
            _counter["ok"] += 1
        d, t = _counter["done"], _counter["total"]
        if d % 100 == 0 or d == t:
            el = time.time() - _t0
            rate = d / el if el else 0
            eta = (t - d) / rate if rate else 0
            print(
                f"  {d:5d}/{t}  ok={_counter['ok']:5d}  "
                f"{rate:5.1f}/s  eta={eta/60:4.1f}m",
                flush=True,
            )
    return idx, res


def main() -> None:
    with open(SRC, encoding="utf-8") as fh:
        recs = json.load(fh)

    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    if limit:
        recs = recs[:limit]

    _counter["total"] = len(recs)
    print(f"probing {len(recs)} streams with {WORKERS} workers (timeout {TIMEOUT}s) ...", flush=True)

    results: dict[int, dict] = {}
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for idx, res in ex.map(work, list(enumerate(recs))):
            results[idx] = res

    for i, rec in enumerate(recs):
        r = results.get(i, {"ok": False, "error": "missing"})
        rec["ok"] = bool(r.get("ok"))
        rec["probe_error"] = r.get("error", "")
        rec["real_codec"] = r.get("codec", "")
        rec["sample_rate"] = r.get("sample_rate", "")
        rec["channels"] = r.get("channels", 0)
        rec["icy_name"] = r.get("icy_name", "")
        rec["icy_genre"] = r.get("icy_genre", "")

    out = os.path.join(HERE, "verified.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(recs, fh, ensure_ascii=False, indent=1)

    live = sum(1 for r in recs if r["ok"])
    print(f"\ndone in {(time.time()-_t0)/60:.1f} min: {live}/{len(recs)} live -> {out}")


if __name__ == "__main__":
    main()
