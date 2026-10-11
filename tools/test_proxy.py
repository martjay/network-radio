"""Test the proxy stack against real proxies and real stations.

Local proxies (127.0.0.1:7890) are fast and reliable, so they double as a
regression test for the tunnel code.
"""
from __future__ import annotations

import sys
import time

sys.path.insert(0, r"E:\KU\AI\deepseek-harness\network-radio")
from radio.net import probe  # noqa: E402
from radio.proxy import (  # noqa: E402
    MODE_CUSTOM, MODE_NONE, LocalProxyShim, ProxyConfig,
    parse_proxy, system_proxy, test_proxy,
)

FAILS: list[str] = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name:<44} {detail}")
    if not ok:
        FAILS.append(name)


# A station that is commonly blocked / slow without a proxy.
INTL_STATIONS = [
    ("SomaFM Groove Salad", "https://ice1.somafm.com/groovesalad-128-mp3"),
    ("SomaFM Reggae", "https://ice5.somafm.com/reggae-256-mp3"),
    ("NPO Radio1 (NL)", "https://icecast.omroep.nl/radio1-bb-mp3"),
    ("Swiss Jazz", "https://stream.srg-ssr.ch/m/rsj/mp3_128"),
]

print("=== 1. parsing ===")
c = parse_proxy("127.0.0.1:7890")
check("host:port", c and c.host == "127.0.0.1" and c.port == 7890, str(c and c.endpoint()))
c = parse_proxy("http://user:p%40ss@proxy.local:3128")
check("http url with credentials", c and c.username == "user" and c.password == "p%40ss",
      str(c and c.endpoint()))
c = parse_proxy("socks5://127.0.0.1:1080")
check("socks5 scheme", c and c.scheme == "socks5" and c.port == 1080, str(c and c.endpoint()))
c = parse_proxy("socks5h://localhost")
check("socks5 default port", c and c.scheme == "socks5" and c.port == 1080, str(c and c.endpoint()))
check("empty rejected", parse_proxy("") is None)
check("garbage rejected", parse_proxy("not a proxy!!") is None)
check("bad port rejected", parse_proxy("host:99999") is None)

print("\n=== 2. bypass rules ===")
cfg = ProxyConfig(MODE_CUSTOM, "http", "127.0.0.1", 7890)
check("localhost bypassed", cfg.should_proxy("localhost") is False)
check("127.0.0.1 bypassed", cfg.should_proxy("127.0.0.1") is False)
check("127.0.0.5 bypassed", cfg.should_proxy("127.0.0.5") is False)
check("public host proxied", cfg.should_proxy("ice1.somafm.com") is True)
cfg_none = ProxyConfig(MODE_NONE)
check("mode=none proxies nothing", cfg_none.should_proxy("ice1.somafm.com") is False)
cfg_empty = ProxyConfig(MODE_CUSTOM, "http", "", 0)
check("unconfigured custom not usable", cfg_empty.usable is False)

print("\n=== 3. system proxy detection ===")
syscfg = system_proxy()
print(f"        detected: {syscfg.describe()}   (source: {syscfg.source or 'none'})")
check("system proxy detected", syscfg.usable or syscfg.mode == MODE_NONE,
      syscfg.describe())

print("\n=== 4. proxy reachability ===")
live = ProxyConfig(MODE_CUSTOM, "http", "127.0.0.1", 7890)
r = test_proxy(live, timeout=10)
check("live proxy passes traffic", r["ok"], r["message"][:60])

# A port with nothing listening must fail cleanly, not hang or crash.
dead = ProxyConfig(MODE_CUSTOM, "http", "127.0.0.1", 9)
t0 = time.time()
r_dead = test_proxy(dead, timeout=5)
dt = time.time() - t0
check("dead proxy fails fast", (not r_dead["ok"]) and dt < 12, f"{dt:.1f}s: {r_dead['message'][:44]}")

print("\n=== 5. station playback through the proxy ===")
for name, url in INTL_STATIONS:
    t0 = time.time()
    res = probe(url, timeout=14, proxy=live)
    dt = time.time() - t0
    ok = res["ok"]
    detail = f"{dt:4.1f}s " + (f"{res.get('kbps', 0):.0f} kbps {res.get('content_type','')}"
                               if ok else res.get("error", "")[:44])
    check(f"via proxy: {name}", ok, detail)

print("\n=== 6. direct vs proxy comparison ===")
for name, url in INTL_STATIONS[:2]:
    direct = probe(url, timeout=12, proxy=ProxyConfig(MODE_NONE))
    print(f"        {name:<22} direct={'OK' if direct['ok'] else direct.get('error','')[:36]}")

print("\n=== 7. ffmpeg CONNECT shim ===")
shim = LocalProxyShim(live, timeout=15)
shim_url = shim.start()
check("shim started", bool(shim_url), shim_url)
try:
    # ffmpeg through the shim must be able to open a proxied HLS stream.
    import subprocess
    from radio.recorder import ffmpeg_path

    # a plain (non-HLS) stream is enough to prove the CONNECT path works
    cmd = [
        ffmpeg_path(), "-hide_banner", "-v", "error", "-nostdin",
        "-http_proxy", shim_url,
        "-i", "https://ice1.somafm.com/groovesalad-128-mp3",
        "-t", "2", "-f", "null", "-",
    ]
    t0 = time.time()
    p = subprocess.run(cmd, capture_output=True, timeout=60)
    dt = time.time() - t0
    err = p.stderr.decode("utf-8", "replace").strip()
    check("ffmpeg tunnels through shim", p.returncode == 0, f"{dt:.1f}s {err[:50] or 'clean'}")
finally:
    shim.stop()
    check("shim stopped", True)

print()
if FAILS:
    print(f"{len(FAILS)} FAILED: {', '.join(FAILS)}")
    sys.exit(1)
print("all proxy checks passed")
