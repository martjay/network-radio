"""Exercise radio.net against a spread of real stations, including HTTPS ones
that Qt's bundled backend could not open."""
import sys
import time

sys.path.insert(0, r"E:\KU\AI\deepseek-harness\network-radio")
from radio.net import probe  # noqa: E402

URLS = [
    "https://dancewave.online/dance.mp3",
    "https://icecast.omroep.nl/radio1-bb-mp3",
    "https://ice1.somafm.com/groovesalad-128-mp3",
    "https://stream.srg-ssr.ch/m/rsj/mp3_128",
    "https://stream.live.vc.bbcmedia.co.uk/bbc_world_service",
    "http://ice1.somafm.com/groovesalad-128-mp3",
    "https://mangoradio.stream.laut.fm/mangoradio",
    "https://listen.reyfm.de/original_192kbps.mp3",
    "http://vis.media-ice.musicradio.com/ClassicFMMP3",
    "https://icecast.omroep.nl/radio2-bb-mp3",
    "https://live.mrf.io/stream/4d3b7e0e/mp3",
    "https://radiorecord.hostingradio.ru/rr_main96.aacp",
]

print(f"{'ok':<3} {'sec':>5} {'kbps':>7} {'ctype':<22} station / error")
for u in URLS:
    r = probe(u, timeout=10)
    if r["ok"]:
        print(f"OK  {r['seconds']:>5} {r['kbps']:>7} {r['content_type'][:21]:<22} {u[:52]}  icy={r['icy_name'][:22]!r}")
    else:
        print(f"--  {r['seconds']:>5} {'-':>7} {'-':<22} {u[:52]}  {r['error'][:46]}")
    time.sleep(0.2)
