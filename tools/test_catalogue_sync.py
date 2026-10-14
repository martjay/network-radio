"""Catalogue classify / select / persist — no live radio-browser calls."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from radio.geo import country_zh, language_zh  # noqa: E402
from radio.taxonomy import (  # noqa: E402
    LIVE_MAX, classify, select_additions, station_from_source,
)


def check(name, got, want):
    ok = got == want
    print(("  OK  " if ok else " FAIL ") + name)
    if not ok:
        print(f"       got={got!r} want={want!r}")
        raise SystemExit(1)


print("=== classify ===")
check("jazz tag", classify({"name": "Smooth Jazz 24", "tags": "smooth jazz"}), "jazz")
check("news tag", classify({"name": "BBC World Service", "tags": "news"}), "news")
check("talk tag", classify({"name": "Night Line", "tags": "talk radio"}), "talk")
check("metal tag", classify({"name": "Caprice", "tags": "black metal"}), "metal")
check("country tag", classify({"name": "Twang FM", "tags": "classic country"}), "country")
check("latin tag", classify({"name": "La Grupo", "tags": "regional mexican"}), "latin")
check("faith tag", classify({"name": "Hope FM", "tags": "christian gospel"}), "faith")
check("blues tag", classify({"name": "Delta Road", "tags": "chicago blues"}), "blues")
check("empty -> varied", classify({"name": "", "tags": ""}), "varied")
check("80s in name", classify({"name": "TOP 80 - Todos Os Exitos De 80 A 2000", "tags": ""}), "oldies")
check("hit word", classify({"name": "100% Radio Hit", "tags": ""}), "pop")
check("accent latin", classify({"name": "La Grupo", "tags": "música mexicana"}), "latin")
check("vallenato", classify({"name": "123 Vallenato", "tags": ""}), "latin")
check("flashback", classify({"name": "Radio Flashback Fm", "tags": "flashback"}), "oldies")
check("disney", classify({"name": "Radio Disney", "tags": ""}), "screen")
check("humor", classify({"name": "Radio Humor", "tags": "humor"}), "culture")
check("dangdut", classify({"name": "RDI FM", "tags": "dangdut"}), "world")
check("kristen", classify({"name": "El Shaddai FM", "tags": "media kristen"}), "faith")
check("eclectic stays varied", classify({"name": "Radio Paradise", "tags": "eclectic,free"}), "varied")
check("filharmonia is classical not film", classify({"name": "Filharmonia Narodowa", "tags": ""}), "classical")
check("rockfm glued", classify({"name": "RockFM", "tags": ""}), "rock")
check("europa plus cyrillic", classify({"name": "Европа Плюс", "tags": ""}), "pop")
check("rfi news", classify({"name": "RFI", "tags": ""}), "news")
check("bollyfm world", classify({"name": "Radio BollyFm", "tags": ""}), "world")
check("cadena 100 pop", classify({"name": "Cadena 100", "tags": "music"}), "pop")
check("mix only stays varied", classify({"name": "Russian Mix", "tags": "mix,music"}), "varied")
check("80's apostrophe", classify({"name": "Hala Sabratha", "tags": "80's,music"}), "oldies")
check("hitsonly glued", classify({"name": "REYFM hitsonly", "tags": "hitsonly"}), "pop")
check("iran international news", classify({"name": "Iran International", "tags": ""}), "news")
check("campur sari world", classify({"name": "89.2 FM Jakarta, Campur sari", "tags": ""}), "world")
check("klassiek classical", classify({"name": "NPO Radio 4", "tags": "klassiek"}), "classical")
check("drum and bass", classify({"name": "Algorythme", "tags": "drum&bass"}), "electronic")
check("superhits compound", classify({"name": "Superhits FM", "tags": ""}), "pop")
check("rdp africa world", classify({"name": "RDP Africa", "tags": "africa,portugal"}), "world")
check("kiss-fm hyphen", classify({"name": "106.1 KISS-FM", "tags": ""}), "pop")
check("digit prefix hit", classify({"name": "1047hit", "tags": ""}), "pop")
check("white not hit", classify({"name": "White River", "tags": ""}), "varied")
check("only rai world", classify({"name": "Only rai", "tags": ""}), "world")
check("nostalgie oldies", classify({"name": "Nostalgie", "tags": ""}), "oldies")
check("untagged MX latin", classify({"name": "Mosaique style", "tags": "", "cc": "MX"}), "latin")
check("untagged TN world", classify({"name": "Jawhara FM", "tags": "", "cc": "TN"}), "world")
check("untagged US stays varied", classify({"name": "Generic FM", "tags": "", "cc": "US"}), "varied")
check("portugal not latin by cc", classify({"name": "Radio Observador", "tags": "", "cc": "PT"}), "varied")
check("paradise still varied", classify({"name": "Radio Paradise", "tags": "eclectic,free", "cc": "US"}), "varied")

print("\n=== station_from_source ===")
dead = station_from_source({
    "name": "Dead FM", "url": "http://example.com/x", "countrycode": "US",
    "lastcheckok": 0, "tags": "jazz",
})
check("broken skipped", dead, None)
bad = station_from_source({"name": "http://evil", "url": "http://example.com/x", "countrycode": "US"})
check("bad name skipped", bad, None)
live = station_from_source({
    "name": "Midnight Jazz",
    "url": "http://example.com/jazz",
    "url_resolved": "http://example.com/jazz",
    "countrycode": "DE",
    "country": "Germany",
    "tags": "jazz",
    "codec": "mp3",
    "bitrate": 192,
    "votes": 10,
    "clickcount": 5,
    "lastcheckok": 1,
})
check("live classified jazz", live["genre"] if live else None, "jazz")
check("live country zh", live["country"] if live else None, "德国")

print("\n=== country / language zh ===")
check("GL", country_zh("GL", "Greenland"), "格陵兰")
check("San Marino", country_zh("SM", "San Marino"), "圣马力诺")
check("english name DR Congo", country_zh("", "The Democratic Republic Of The Congo"), "刚果（金）")
check("german", language_zh("german"), "德语")
check("multi lang", language_zh("german,english"), "德语、英语")

print("\n=== select_additions grow-only ===")
existing = [
    {"name": "Keep Me", "url": "http://keep.example/a", "cc": "CN", "genre": "news", "score": 1},
]
pool = [
    existing[0],
    {"name": "New One", "url": "http://new.example/b", "cc": "JP", "genre": "jazz", "score": 80},
    {"name": "Keep Me", "url": "http://other.example/c", "cc": "CN", "genre": "news", "score": 90},
]
added = select_additions(pool, existing, max_total=10, per_genre=8, per_genre_hard=10,
                         per_country=8, priority=[("CN", 2), ("JP", 2)])
urls = {r["url"] for r in added}
check("does not re-add existing url", "http://keep.example/a" in urls, False)
check("skips same name+cc", "http://other.example/c" in urls, False)
check("adds new station", "http://new.example/b" in urls, True)

print("\n=== cap respected ===")
many = [
    {"name": f"J{i}", "url": f"http://j.example/{i}", "cc": "US", "genre": "jazz", "score": 100 - i}
    for i in range(50)
]
capped = select_additions(
    many, existing=[], max_total=5, per_genre=3, per_genre_hard=4,
    per_country=10, priority=[("US", 2)],
)
check("max_total 5", len(capped) <= 5, True)
check("genre hard cap 4", sum(1 for r in capped if r["genre"] == "jazz") <= 4, True)

print("\n=== library persist extras ===")
from PySide6.QtWidgets import QApplication  # noqa: E402
from radio import paths  # noqa: E402
from radio.library import Library  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)
tmp = tempfile.mkdtemp(prefix="nr-cat-")
prev = paths._DATA_DIR
paths._DATA_DIR = tmp
try:
    lib = Library()
    base = len(lib.stations)
    check("bundled loaded", base >= 800, True)
    fav_url = lib.stations[0]["url"]
    lib.favorites = [fav_url]
    extra = {
        "name": "Synced Extra FM",
        "url": "http://extra.example/stream",
        "genre": "jazz",
        "country": "日本",
        "cc": "JP",
        "region": "",
        "state": "",
        "language": "",
        "tags": "jazz",
        "homepage": "",
        "favicon": "",
        "codec": "MP3",
        "bitrate": 192,
        "sample_rate": "",
        "channels": 2,
        "votes": 1,
        "clicks": 1,
        "zh": False,
        "score": 12.0,
        "extra": True,
        "custom": False,
    }
    applied = lib.apply_catalogue_sync([], [extra])
    check("added 1", applied["added"], 1)
    check("count grew", len(lib.stations), base + 1)
    check("favorite kept", lib.favorites, [fav_url])
    userdata = json.loads(open(os.path.join(tmp, "userdata.json"), encoding="utf-8").read())
    check("extras persisted", len(userdata.get("catalogue_extra") or []), 1)

    lib2 = Library()
    check("reload extras", any(s.get("url") == extra["url"] for s in lib2.stations), True)
    check("reload count", len(lib2.stations), base + 1)

    empty = lib2.apply_catalogue_sync([], [extra])
    check("second sync no dup", empty["added"], 0)
    check("still unique", len(lib2.stations), base + 1)

    restored = lib2.restore_catalogue_backup(1)
    check("restore ok", restored.get("ok"), True)
    check("restore drops extra", any(s.get("url") == extra["url"] for s in lib2.stations), False)
    check("restore back to bundled", len(lib2.stations), base)
    check("favorite still there", fav_url in lib2.favorites, True)
finally:
    paths._DATA_DIR = prev
    shutil.rmtree(tmp, ignore_errors=True)

uncapped = select_additions(many, existing=[], priority=[])
check("live default has no total cap", len(uncapped), 50)
check("LIVE_MAX is unlimited", LIVE_MAX, 0)
print("all catalogue sync checks passed")
