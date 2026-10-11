"""Regression tests for the bitrate parser and stream helpers.

Run:  python tools/selftest.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from radio.net import parse_encoded_bitrate, parse_playlist  # noqa: E402

FAILS: list[str] = []


def check(name: str, got, want) -> None:
    ok = got == want
    if ok:
        shown = ""
    else:
        def brief(v):
            r = repr(v)
            return r if len(r) <= 48 else f"{r[:45]}...({len(v)}B)"
        shown = f"got={brief(got)} want={brief(want)}"
    print(f"  {'PASS' if ok else 'FAIL'}  {name:<52} {shown}")
    if not ok:
        FAILS.append(name)


def mp3_frame(version: int, layer: int, bitrate_idx: int, rate_idx: int, mode: int = 0) -> bytes:
    """Build a valid MPEG audio frame header for the given parameters."""
    b1 = 0xE0 | (version << 3) | (layer << 1) | 0x01   # no CRC
    b2 = (bitrate_idx << 4) | (rate_idx << 2) | 0x00
    b3 = (mode << 6) | 0x00
    return bytes([0xFF, b1, b2, b3]) + b"\x00" * 64


def main() -> int:
    print("MPEG audio bitrate parsing")
    # MPEG1 Layer III, the format virtually all Icecast MP3 stations use.
    check("MPEG1 L3 128 kbps 44.1 kHz stereo",
          parse_encoded_bitrate(mp3_frame(3, 1, 9, 0, 0)), (128, 44100, 2))
    check("MPEG1 L3 192 kbps 48 kHz stereo",
          parse_encoded_bitrate(mp3_frame(3, 1, 11, 1, 0)), (192, 48000, 2))
    check("MPEG1 L3 320 kbps 44.1 kHz stereo",
          parse_encoded_bitrate(mp3_frame(3, 1, 14, 0, 0)), (320, 44100, 2))
    check("MPEG1 L3 64 kbps 32 kHz mono",
          parse_encoded_bitrate(mp3_frame(3, 1, 5, 2, 3)), (64, 32000, 1))
    check("MPEG1 L2 128 kbps 44.1 kHz stereo",
          parse_encoded_bitrate(mp3_frame(3, 2, 8, 0, 0)), (128, 44100, 2))
    check("MPEG1 L1 448 kbps 44.1 kHz stereo",
          parse_encoded_bitrate(mp3_frame(3, 3, 14, 0, 0)), (448, 44100, 2))
    check("MPEG2 L3 64 kbps 22.05 kHz stereo",
          parse_encoded_bitrate(mp3_frame(2, 1, 8, 0, 0)), (64, 22050, 2))
    check("MPEG2.5 L3 32 kbps 11.025 kHz stereo",
          parse_encoded_bitrate(mp3_frame(0, 1, 4, 0, 0)), (32, 11025, 2))

    print("\ngarbage and edge cases")
    check("empty input", parse_encoded_bitrate(b""), (0, 0, 0))
    check("random bytes", parse_encoded_bitrate(bytes(range(256)) * 8), (0, 0, 0))
    check("0xFF run then valid frame",
          parse_encoded_bitrate(b"\xff\xff\xff" + mp3_frame(3, 1, 9, 0)), (128, 44100, 2))
    check("ID3 tag prefix then frame",
          parse_encoded_bitrate(b"ID3\x04\x00\x00\x00\x00\x00\x00" + mp3_frame(3, 1, 7, 0)),
          (96, 44100, 2))
    # free-format (bitrate index 0) and the forbidden index 15 must be skipped
    check("free-format frame skipped",
          parse_encoded_bitrate(mp3_frame(3, 1, 0, 0) + mp3_frame(3, 1, 9, 0)), (128, 44100, 2))

    print("\nADTS AAC parsing")
    # 44100 Hz, stereo, 1024-sample frame, ~128 kbps -> frame length ~371 bytes
    def aac_frame(frame_len: int, srx: int = 4, ch: int = 2) -> bytes:
        b2 = (srx << 2) | ((ch >> 2) & 0x01)
        b3 = ((ch & 0x03) << 6) | ((frame_len >> 11) & 0x03)
        b4 = (frame_len >> 3) & 0xFF
        b5 = ((frame_len & 0x07) << 5) | 0x1F
        return bytes([0xFF, 0xF1, b2, b3, b4, b5]) + b"\x00" * (frame_len - 6)

    kbps, rate, channels = parse_encoded_bitrate(aac_frame(371, 4, 2))
    check("AAC 44.1 kHz sample rate", rate, 44100)
    check("AAC stereo", channels, 2)
    check("AAC ~128 kbps frame length", 120 <= kbps <= 136, True)
    kbps2, rate2, _ = parse_encoded_bitrate(aac_frame(186, 3, 2))   # 48 kHz, ~64 kbps
    check("AAC 48 kHz sample rate", rate2, 48000)
    check("AAC ~64 kbps frame length", 55 <= kbps2 <= 75, True)

    print("\nplaylist parsing")
    pls = "[playlist]\nNumberOfEntries=2\nFile1=http://a.example/1\nTitle1=A\nFile2=http://b.example/2\n"
    check("PLS file list", parse_playlist(pls), ["http://a.example/1", "http://b.example/2"])
    m3u = "#EXTM3U\n#EXTINF:-1,Station\nhttp://c.example/3\n\nhttp://d.example/4\n"
    check("M3U url list", parse_playlist(m3u), ["http://c.example/3", "http://d.example/4"])
    asx = '<asx version="3.0"><entry><ref href="http://e.example/5"/></entry></asx>'
    check("ASX href", parse_playlist(asx), ["http://e.example/5"])
    check("duplicates removed",
          parse_playlist("http://x/1\nhttp://x/1\nhttp://x/2"), ["http://x/1", "http://x/2"])
    check("non-http entries ignored",
          parse_playlist("notaurl\nhttp://ok/1\nfile:///local"), ["http://ok/1"])

    print("\nrecorder frame alignment")
    from radio.recorder import Recorder

    frame = mp3_frame(3, 1, 11, 0)          # 192 kbps frame header
    junk = b"\x7a\x11\x03\xff" * 3          # partial frame tail
    check("mp3 aligned to sync word",
          Recorder._align(junk + frame, "mp3")[:4], frame[:4])
    check("mp3 already aligned is unchanged",
          Recorder._align(frame, "mp3"), frame)
    check("id3 tag passed through",
          Recorder._align(b"ID3\x04\x00\x00" + frame, "mp3")[:3], b"ID3")
    aac = bytes([0xFF, 0xF1, 0x50, 0x80, 0x00, 0x1F]) + b"\x00" * 32
    check("aac aligned to sync word",
          Recorder._align(b"\x00\x11\x22" + aac, "aac")[:2], b"\xff\xf1")
    check("no sync word leaves data intact",
          Recorder._align(b"\x00" * 64, "mp3"), b"\x00" * 64)

    print("\nrecorder tail trimming")
    # MPEG1 Layer III, 128 kbps @ 44.1 kHz -> 417 or 418 byte frames
    hdr = bytes([0xFF, 0xFB, 0x90, 0x00])
    frame = hdr + b"\x00" * 413          # 417 bytes total
    check("frame length computed", Recorder._frame_length(frame, 0), 417)
    check("complete frames kept", Recorder._trim_partial_frame(frame * 3, "mp3"), frame * 3)
    check("partial frame dropped",
          Recorder._trim_partial_frame(frame * 3 + frame[:100], "mp3"), frame * 3)
    check("one partial frame dropped",
          Recorder._trim_partial_frame(frame + frame[:1], "mp3"), frame)
    check("empty tail handled", Recorder._trim_partial_frame(b"", "mp3"), b"")
    check("non-mp3 untouched",
          Recorder._trim_partial_frame(b"\x00" * 10, "aac"), b"\x00" * 10)

    print()
    if FAILS:
        print(f"{len(FAILS)} FAILED: {', '.join(FAILS)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
