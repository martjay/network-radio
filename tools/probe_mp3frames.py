"""Parse MP3 frame headers to determine the true encoded bitrate, and compare
it against the measured socket throughput."""
import sys
import time

sys.path.insert(0, r"E:\KU\AI\deepseek-harness\network-radio")
from radio.net import open_stream

BITRATES = {
    (3, 1): [0, 32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448],
    (3, 2): [0, 32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384],
    (3, 3): [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320],
}
RATES = {3: [44100, 48000, 32000], 2: [22050, 24000, 16000], 0: [11025, 12000, 8000]}


def frames(buf: bytes):
    out = []
    i = 0
    n = len(buf)
    while i < n - 4 and len(out) < 40:
        if buf[i] == 0xFF and (buf[i + 1] & 0xE0) == 0xE0:
            b1, b2 = buf[i + 1], buf[i + 2]
            ver = (b1 >> 3) & 0x03          # 3 = MPEG1
            layer = (b1 >> 1) & 0x03        # 1 = Layer III
            brx = (b2 >> 4) & 0x0F
            srx = (b2 >> 2) & 0x03
            if layer == 1 and brx not in (0, 15) and srx != 3 and ver in RATES:
                table = BITRATES.get((ver, 3)) or BITRATES.get((ver, layer))
                if table:
                    out.append((table[brx], RATES[ver][srx]))
                    i += 4
                    continue
        i += 1
    return out


URL = sys.argv[1] if len(sys.argv) > 1 else "https://atunwadigital.streamguys1.com/brilafm"
r = open_stream(URL, timeout=14)
print(f"station: {URL}")
print(f"icy-name={r.icy_name!r}  metaint-header={getattr(r, '_metaint', 'n/a')}")

data = bytearray()
t0 = time.time()
while len(data) < 256 * 1024 and time.time() - t0 < 12:
    d = r.read(16384)
    if not d:
        break
    data += d
elapsed = time.time() - t0
r.close()

parsed = frames(bytes(data))
if parsed:
    from collections import Counter
    c = Counter(parsed)
    top = c.most_common(3)
    print(f"decoded frames analysed: {len(parsed)}")
    for (br, sr), count in top:
        print(f"  MP3 frame header says: {br} kbps @ {sr} Hz   (x{count})")
else:
    print("no MP3 frames parsed (AAC or other codec)")

print(f"socket throughput: {len(data)*8/1000/elapsed:.1f} kbps over {elapsed:.1f}s")
