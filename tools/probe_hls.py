import json
import sys
import time

sys.path.insert(0, r"E:\KU\AI\deepseek-harness\network-radio")
from radio.net import probe

d = json.load(open(r"E:\KU\AI\deepseek-harness\network-radio\assets\stations.json", encoding="utf-8"))
hls = [s for s in d["stations"] if ".m3u8" in s["url"].lower()]
print(f"HLS entries in catalogue: {len(hls)}\n")
ok = 0
for s in hls:
    t = time.time()
    r = probe(s["url"], timeout=18)
    dt = time.time() - t
    if r["ok"]:
        ok += 1
    tag = "OK " if r["ok"] else "-- "
    detail = (r.get("error", "") or f"{r.get('content_type','')} {r.get('kbps')}kbps").replace("\n", " ")
    print(f"{tag}{s['name'][:30]:<32}{dt:5.1f}s  {detail[:56]}")
print(f"\nHLS reachable: {ok}/{len(hls)}")
