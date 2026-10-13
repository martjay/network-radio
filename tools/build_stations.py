"""Turn verified probe results into the curated station database shipped
with the application.

Classification and caps live in `radio.taxonomy` so a later in-app sync
uses the same genre rules as this snapshot.
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from radio.taxonomy import (  # noqa: E402
    SHIP_MAX, SHIP_PER_COUNTRY, SHIP_PER_GENRE, SHIP_PER_GENRE_HARD,
    SHIP_PRIORITY, countries_meta, genres_meta, select_additions,
    station_from_source,
)

SRC = os.path.join(HERE, "verified.json")
OUT = os.path.join(ROOT, "assets", "stations.json")


def main() -> None:
    with open(SRC, encoding="utf-8") as fh:
        raw = json.load(fh)

    live = [r for r in raw if r.get("ok")]
    print(f"live streams: {len(live)}")

    pool = []
    for row in live:
        rec = station_from_source(row)
        if rec is None:
            continue
        rec["extra"] = False
        pool.append(rec)
    print(f"after cleaning/dedupe: {len(pool)}")
    pool.sort(key=lambda r: -r["score"])

    chosen = select_additions(
        pool,
        existing=[],
        max_total=SHIP_MAX,
        per_genre=SHIP_PER_GENRE,
        per_genre_hard=SHIP_PER_GENRE_HARD,
        per_country=SHIP_PER_COUNTRY,
        priority=SHIP_PRIORITY,
    )
    # select_additions dedupes against existing only; pool itself may still
    # contain url/name duplicates. Re-run through an empty-existing select
    # already skips duplicates inside the candidate loop.
    print(f"selected: {len(chosen)}")

    payload = {
        "generated": __import__("datetime").date.today().isoformat(),
        "source": "radio-browser.info (community database) - every stream verified with ffprobe",
        "total": len(chosen),
        "genres": genres_meta(chosen),
        "countries": countries_meta(chosen),
        "stations": sorted(chosen, key=lambda r: (r["genre"], -r["score"])),
    }
    for rec in payload["stations"]:
        rec.pop("extra", None)
        rec.pop("custom", None)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1, separators=(",", ": "))
    size = os.path.getsize(OUT) / 1024
    print(f"\nwrote {OUT}  ({size:.0f} KB, {len(chosen)} stations)")
    print(f"chinese-language stations: {sum(1 for r in chosen if r['zh'])}")


if __name__ == "__main__":
    main()
