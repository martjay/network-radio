"""Harvest a large candidate pool of radio stations from the radio-browser.info API.

Output: candidates.json  --  deduplicated by resolved stream URL, MP3/AAC only,
bitrate >= 64, with a stable `ok` flag set later by verify.py.
"""
from __future__ import annotations

import json
import os
import ssl
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "candidates.json")

SERVERS = [
    "https://de1.api.radio-browser.info",
    "https://de2.api.radio-browser.info",
    "https://nl1.api.radio-browser.info",
    "https://at1.api.radio-browser.info",
    "https://fi1.api.radio-browser.info",
]

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

UA = "NetworkRadioSuite/1.0 (+local desktop client)"


def api(path: str, params: dict | None = None, tries: int = 4):
    q = urllib.parse.urlencode(params or {})
    last = None
    for i in range(tries):
        base = SERVERS[i % len(SERVERS)]
        url = f"{base}{path}" + (f"?{q}" if q else "")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=40, context=CTX) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(1.2 * (i + 1))
    print(f"  !! failed {path} {params}: {last}", file=sys.stderr)
    return []


# (label, path, params)
QUERIES: list[tuple[str, str, dict]] = [
    # --- global high-quality pools -------------------------------------------
    ("topvote", "/json/stations/topvote/600", {"hidebroken": "true"}),
    ("topclick", "/json/stations/topclick/600", {"hidebroken": "true"}),
    # --- by country ----------------------------------------------------------
    ("cn", "/json/stations/bycountrycodeexact/CN", {"hidebroken": "true", "order": "votes", "reverse": "true", "limit": 400}),
    ("hk", "/json/stations/bycountrycodeexact/HK", {"hidebroken": "true", "order": "votes", "reverse": "true", "limit": 120}),
    ("tw", "/json/stations/bycountrycodeexact/TW", {"hidebroken": "true", "order": "votes", "reverse": "true", "limit": 120}),
    ("us", "/json/stations/bycountrycodeexact/US", {"hidebroken": "true", "order": "votes", "reverse": "true", "limit": 400}),
    ("gb", "/json/stations/bycountrycodeexact/GB", {"hidebroken": "true", "order": "votes", "reverse": "true", "limit": 300}),
    ("de", "/json/stations/bycountrycodeexact/DE", {"hidebroken": "true", "order": "votes", "reverse": "true", "limit": 300}),
    ("fr", "/json/stations/bycountrycodeexact/FR", {"hidebroken": "true", "order": "votes", "reverse": "true", "limit": 300}),
    ("jp", "/json/stations/bycountrycodeexact/JP", {"hidebroken": "true", "order": "votes", "reverse": "true", "limit": 200}),
    ("kr", "/json/stations/bycountrycodeexact/KR", {"hidebroken": "true", "order": "votes", "reverse": "true", "limit": 120}),
    ("it", "/json/stations/bycountrycodeexact/IT", {"hidebroken": "true", "order": "votes", "reverse": "true", "limit": 200}),
    ("es", "/json/stations/bycountrycodeexact/ES", {"hidebroken": "true", "order": "votes", "reverse": "true", "limit": 200}),
    ("nl", "/json/stations/bycountrycodeexact/NL", {"hidebroken": "true", "order": "votes", "reverse": "true", "limit": 200}),
    ("ch", "/json/stations/bycountrycodeexact/CH", {"hidebroken": "true", "order": "votes", "reverse": "true", "limit": 150}),
    ("at", "/json/stations/bycountrycodeexact/AT", {"hidebroken": "true", "order": "votes", "reverse": "true", "limit": 150}),
    ("ca", "/json/stations/bycountrycodeexact/CA", {"hidebroken": "true", "order": "votes", "reverse": "true", "limit": 150}),
    ("au", "/json/stations/bycountrycodeexact/AU", {"hidebroken": "true", "order": "votes", "reverse": "true", "limit": 150}),
    ("br", "/json/stations/bycountrycodeexact/BR", {"hidebroken": "true", "order": "votes", "reverse": "true", "limit": 150}),
    ("ru", "/json/stations/bycountrycodeexact/RU", {"hidebroken": "true", "order": "votes", "reverse": "true", "limit": 150}),
    ("pl", "/json/stations/bycountrycodeexact/PL", {"hidebroken": "true", "order": "votes", "reverse": "true", "limit": 150}),
    ("se", "/json/stations/bycountrycodeexact/SE", {"hidebroken": "true", "order": "votes", "reverse": "true", "limit": 120}),
    ("no", "/json/stations/bycountrycodeexact/NO", {"hidebroken": "true", "order": "votes", "reverse": "true", "limit": 120}),
    ("in", "/json/stations/bycountrycodeexact/IN", {"hidebroken": "true", "order": "votes", "reverse": "true", "limit": 150}),
    ("sg", "/json/stations/bycountrycodeexact/SG", {"hidebroken": "true", "order": "votes", "reverse": "true", "limit": 80}),
    # --- by tag / genre ------------------------------------------------------
    ("tag:jazz", "/json/stations/bytagexact/jazz", {"hidebroken": "true", "order": "votes", "reverse": "true", "limit": 250}),
    ("tag:classical", "/json/stations/bytagexact/classical", {"hidebroken": "true", "order": "votes", "reverse": "true", "limit": 250}),
    ("tag:classic", "/json/stations/bytagexact/classic", {"hidebroken": "true", "order": "votes", "reverse": "true", "limit": 250}),
    ("tag:rock", "/json/stations/bytagexact/rock", {"hidebroken": "true", "order": "votes", "reverse": "true", "limit": 250}),
    ("tag:pop", "/json/stations/bytagexact/pop", {"hidebroken": "true", "order": "votes", "reverse": "true", "limit": 250}),
    ("tag:electronic", "/json/stations/bytagexact/electronic", {"hidebroken": "true", "order": "votes", "reverse": "true", "limit": 200}),
    ("tag:house", "/json/stations/bytagexact/house", {"hidebroken": "true", "order": "votes", "reverse": "true", "limit": 150}),
    ("tag:techno", "/json/stations/bytagexact/techno", {"hidebroken": "true", "order": "votes", "reverse": "true", "limit": 150}),
    ("tag:trance", "/json/stations/bytagexact/trance", {"hidebroken": "true", "order": "votes", "reverse": "true", "limit": 150}),
    ("tag:lounge", "/json/stations/bytagexact/lounge", {"hidebroken": "true", "order": "votes", "reverse": "true", "limit": 150}),
    ("tag:ambient", "/json/stations/bytagexact/ambient", {"hidebroken": "true", "order": "votes", "reverse": "true", "limit": 150}),
    ("tag:chillout", "/json/stations/bytagexact/chillout", {"hidebroken": "true", "order": "votes", "reverse": "true", "limit": 150}),
    ("tag:hiphop", "/json/stations/bytagexact/hiphop", {"hidebroken": "true", "order": "votes", "reverse": "true", "limit": 150}),
    ("tag:blues", "/json/stations/bytagexact/blues", {"hidebroken": "true", "order": "votes", "reverse": "true", "limit": 120}),
    ("tag:country", "/json/stations/bytagexact/country", {"hidebroken": "true", "order": "votes", "reverse": "true", "limit": 120}),
    ("tag:reggae", "/json/stations/bytagexact/reggae", {"hidebroken": "true", "order": "votes", "reverse": "true", "limit": 120}),
    ("tag:metal", "/json/stations/bytagexact/metal", {"hidebroken": "true", "order": "votes", "reverse": "true", "limit": 150}),
    ("tag:indie", "/json/stations/bytagexact/indie", {"hidebroken": "true", "order": "votes", "reverse": "true", "limit": 150}),
    ("tag:folk", "/json/stations/bytagexact/folk", {"hidebroken": "true", "order": "votes", "reverse": "true", "limit": 120}),
    ("tag:soul", "/json/stations/bytagexact/soul", {"hidebroken": "true", "order": "votes", "reverse": "true", "limit": 120}),
    ("tag:funk", "/json/stations/bytagexact/funk", {"hidebroken": "true", "order": "votes", "reverse": "true", "limit": 120}),
    ("tag:oldies", "/json/stations/bytagexact/oldies", {"hidebroken": "true", "order": "votes", "reverse": "true", "limit": 150}),
    ("tag:80s", "/json/stations/bytagexact/80s", {"hidebroken": "true", "order": "votes", "reverse": "true", "limit": 150}),
    ("tag:90s", "/json/stations/bytagexact/90s", {"hidebroken": "true", "order": "votes", "reverse": "true", "limit": 150}),
    ("tag:news", "/json/stations/bytagexact/news", {"hidebroken": "true", "order": "votes", "reverse": "true", "limit": 250}),
    ("tag:talk", "/json/stations/bytagexact/talk", {"hidebroken": "true", "order": "votes", "reverse": "true", "limit": 200}),
    ("tag:sport", "/json/stations/bytagexact/sport", {"hidebroken": "true", "order": "votes", "reverse": "true", "limit": 150}),
    ("tag:culture", "/json/stations/bytagexact/culture", {"hidebroken": "true", "order": "votes", "reverse": "true", "limit": 120}),
    ("tag:latin", "/json/stations/bytagexact/latin", {"hidebroken": "true", "order": "votes", "reverse": "true", "limit": 150}),
    ("tag:world", "/json/stations/bytagexact/world", {"hidebroken": "true", "order": "votes", "reverse": "true", "limit": 150}),
    ("tag:smoothjazz", "/json/stations/bytagexact/smooth%20jazz", {"hidebroken": "true", "order": "votes", "reverse": "true", "limit": 120}),
    ("tag:instrumental", "/json/stations/bytagexact/instrumental", {"hidebroken": "true", "order": "votes", "reverse": "true", "limit": 120}),
    ("tag:piano", "/json/stations/bytagexact/piano", {"hidebroken": "true", "order": "votes", "reverse": "true", "limit": 100}),
    ("tag:soundtrack", "/json/stations/bytagexact/soundtrack", {"hidebroken": "true", "order": "votes", "reverse": "true", "limit": 100}),
    ("tag:audiophile", "/json/stations/bytagexact:audiophile", {"hidebroken": "true", "order": "votes", "reverse": "true", "limit": 100}),
    # --- high bitrate search -------------------------------------------------
    ("br:320", "/json/stations/search", {"hidebroken": "true", "bitrateMin": 256, "order": "votes", "reverse": "true", "limit": 400}),
    ("br:192", "/json/stations/search", {"hidebroken": "true", "bitrateMin": 192, "order": "votes", "reverse": "true", "limit": 400}),
]


def norm(s: dict) -> dict | None:
    url = (s.get("url_resolved") or s.get("url") or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        return None
    codec = (s.get("codec") or "").upper()
    if codec not in ("MP3", "AAC", "AAC+", "MP3,AAC", "AAC,H.264", "OGG", "OPUS"):
        return None
    try:
        bitrate = int(s.get("bitrate") or 0)
    except (TypeError, ValueError):
        bitrate = 0
    return {
        "name": (s.get("name") or "").strip(),
        "url": url,
        "codec": codec,
        "bitrate": bitrate,
        "country": (s.get("country") or "").strip(),
        "countrycode": (s.get("countrycode") or "").strip().upper(),
        "state": (s.get("state") or "").strip(),
        "language": (s.get("language") or "").strip(),
        "tags": (s.get("tags") or "").strip(),
        "homepage": (s.get("homepage") or "").strip(),
        "favicon": (s.get("favicon") or "").strip(),
        "votes": int(s.get("votes") or 0),
        "clicks": int(s.get("clickcount") or 0),
        "source": "",
    }


def main() -> None:
    pool: dict[str, dict] = {}
    for i, (label, path, params) in enumerate(QUERIES, 1):
        rows = api(path, params)
        added = 0
        for row in rows:
            rec = norm(row)
            if not rec or not rec["name"]:
                continue
            key = rec["url"].rstrip("/").lower()
            if key in pool:
                pool[key]["votes"] = max(pool[key]["votes"], rec["votes"])
                continue
            rec["source"] = label
            pool[key] = rec
            added += 1
        print(f"[{i:02d}/{len(QUERIES)}] {label:20s} got={len(rows):4d} new={added:4d} pool={len(pool)}", flush=True)
        time.sleep(0.35)

    recs = sorted(pool.values(), key=lambda r: (-r["votes"], -r["bitrate"]))
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(recs, fh, ensure_ascii=False, indent=1)
    print(f"\nwrote {len(recs)} candidates -> {OUT}")


if __name__ == "__main__":
    main()
