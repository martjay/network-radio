"""Prove the PEM markers found inside Qt's DLLs are format constants, not keys.

A real PEM private key has the header immediately followed by a newline and
then base64 body lines. Qt's binaries contain the header strings because they
are used to *detect* PEM input. This checks what actually follows each marker.
"""
from __future__ import annotations

import io
import re
import sys
import zipfile

sys.path.insert(0, r"E:\KU\AI\deepseek-harness\network-radio")
from radio.net import open_stream  # noqa: E402
from radio.proxy import system_proxy  # noqa: E402

URL = ("https://github.com/martjay/network-radio/releases/download/"
       "v1.0.0/Broadcast-1.0.0-win64.zip")

print("fetching release zip ...")
r = open_stream(URL, timeout=60, proxy=system_proxy())
buf = bytearray()
while True:
    c = r.read(262144)
    if not c:
        break
    buf += c
r.close()
z = zipfile.ZipFile(io.BytesIO(bytes(buf)))

HEADER = re.compile(rb"-----BEGIN ([A-Z0-9 ]*PRIVATE KEY)-----")
BASE64_LINE = re.compile(rb"^[A-Za-z0-9+/=]{40,}$")

targets = [n for n in z.namelist() if n.lower().endswith((".dll", ".pyd", ".exe"))]
print(f"scanning {len(targets)} binaries\n")

suspicious = []
for name in targets:
    try:
        data = z.read(name)
    except Exception:  # noqa: BLE001
        continue
    for m in HEADER.finditer(data):
        end = m.end()
        following = data[end:end + 200]
        # What comes right after the marker?
        # A genuine PEM key: b"\n" then base64 lines.
        looks_real = False
        if following[:1] in (b"\n", b"\r"):
            body = following.split(b"-----", 1)[0]
            lines = [ln for ln in body.replace(b"\r", b"").split(b"\n") if ln]
            b64 = [ln for ln in lines if BASE64_LINE.match(ln)]
            if len(b64) >= 3:
                looks_real = True
        preview = following[:60]
        printable = "".join(chr(b) if 32 <= b < 127 else "." for b in preview)
        tag = "SUSPICIOUS" if looks_real else "format constant"
        if looks_real:
            suspicious.append(f"{name}: {m.group(1).decode()}")
        print(f"  {tag:<15} {name.split('/')[-1]:<28} {m.group(1).decode():<24} next={printable!r}")

print()
if suspicious:
    print(f"!!! {len(suspicious)} markers followed by base64 key material:")
    for s in suspicious:
        print("   ", s)
    sys.exit(1)

print("CONCLUSION: every PEM marker is a bare format string used by Qt's TLS")
print("            parser to recognise PEM input. None is followed by key")
print("            material, so no private key is embedded.")
