import sys
import time

sys.path.insert(0, r"E:\KU\AI\deepseek-harness\network-radio")
from radio.net import open_stream

URL = sys.argv[1] if len(sys.argv) > 1 else "https://atunwadigital.streamguys1.com/brilafm"

r = open_stream(URL, timeout=14)
print(f"opened: ctype={r.content_type} icy={r.icy_name!r}")
t0 = time.time()
last = 0
total = 0
mark_at = None
for i in range(60):
    time.sleep(0.5)
    d = r.read(16384)
    total += len(d)
    el = time.time() - t0
    if total > 60 * 1024 and mark_at is None:
        mark_at = (el, total)
        r.mark()
    inst = (total - last) * 8 / 1000 / 0.5
    last = total
    tag = ""
    if mark_at and abs(el - mark_at[0]) < 0.01:
        tag = "  <-- marked"
    print(f"  t={el:5.1f}s  total={total/1024:7.1f}KB  inst={inst:6.1f}kbps  "
          f"avg={(total*8/1000)/el:6.1f}kbps  measured={r.measured_kbps:6.1f}kbps{tag}")
    if el > 12:
        break
r.close()
