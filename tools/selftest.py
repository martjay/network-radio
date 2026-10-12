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

    print("\ncontainer / source compatibility")
    from radio.recorder import COPY_COMPATIBLE, Recorder

    check("mp3 source into mp3 is a copy", "mp3" in COPY_COMPATIBLE["mp3"], True)
    check("ogg source cannot go into mp3", "ogg" in COPY_COMPATIBLE["mp3"], False)
    check("aac source cannot go into mp3", "aac" in COPY_COMPATIBLE["mp3"], False)
    # The reported bug: an Ogg/Opus station must not be written as .mp3.
    check("opus auto-selects ogg", Recorder.best_container("ogg", "mp3"), "ogg")
    check("aac auto-selects aac", Recorder.best_container("aac", "mp3"), "aac")
    check("mp3 keeps requested mp3", Recorder.best_container("mp3", "mp3"), "mp3")
    check("flac keeps requested flac", Recorder.best_container("flac", "flac"), "flac")
    check("wav request not remapped to mp3", Recorder.best_container("mp3", "wav"), "wav")
    check("flac request not remapped to mp3", Recorder.best_container("mp3", "flac"), "flac")
    check("wav forces transcode", COPY_COMPATIBLE["wav"], set())
    check("source_format maps opus->ogg", Recorder.source_format("opus"), "ogg")
    check("source_format maps vorbis->ogg", Recorder.source_format("vorbis"), "ogg")

    print("\nstream sniffing")
    _rec = Recorder.__new__(Recorder)
    _rec.source_url = ""
    check("OggS header -> ogg", _rec._sniff(b"OggS\x00\x02\x00\x00" + b"\x00" * 8), "ogg")
    check("ID3 header -> mp3", _rec._sniff(b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\x00" * 6), "mp3")
    check("fLaC header -> flac", _rec._sniff(b"fLaC\x00\x00\x00\x22" + b"\x00" * 8), "flac")
    check("ADTS header -> aac", _rec._sniff(b"\xff\xf1\x50\x80\x00\x1f" + b"\x00" * 10), "aac")
    check("MPEG frame -> mp3", _rec._sniff(b"\xff\xfb\x90\x00" + b"\x00" * 12), "mp3")
    _rec.source_url = "https://listen.moe/kpop/stream"
    check("unknown bytes falls back to url", _rec._sniff(b"\x01\x02\x03\x04" + b"\x00" * 12), "mp3")
    _rec.source_url = "https://example.com/opus.stream"
    check("url hint 'opus' -> ogg", _rec._sniff(b"\x01\x02\x03\x04" + b"\x00" * 12), "ogg")

    print("\nstream continuity")
    # The relay keeps a sliding window of pre-recording audio. It must slide,
    # not stop appending: a retained prefix that is not contiguous with the
    # live stream leaves a gap, and the decoder then reports a corrupt frame
    # part-way through the recording.
    import inspect

    from radio.relay import Relay

    src = inspect.getsource(Relay._pump_loop)
    check("backlog slides (drops oldest)", "del self._pending[:overflow]" in src, True)
    check("backlog still bounded", "_pending_limit" in src, True)

    print("\nheader replay policy")
    # Container formats need the header page replayed; raw frame streams must
    # not be, or audio is duplicated and frame alignment breaks.
    _r = Recorder.__new__(Recorder)
    _r.source = ""
    check("unknown format defaults to needing header", _r.needs_stream_header, True)
    for src_fmt, want in (("ogg", True), ("flac", True), ("mp3", False), ("aac", False)):
        _r.source = src_fmt
        check(f"{src_fmt}: needs header = {want}", _r.needs_stream_header, want)

    _relay = Relay.__new__(Relay)
    _relay._lock = __import__("threading").Lock()
    _relay._pending = bytearray(b"LIVE" * 8)
    _relay._head = b"HEADER"
    _relay._wrapped = True
    check("wrapped + needs  -> header prepended",
          _relay.drain_for_recorder(True).startswith(b"HEADER"), True)
    _relay._pending = bytearray(b"LIVE" * 8)
    check("wrapped + no need -> backlog only",
          _relay.drain_for_recorder(False).startswith(b"LIVE"), True)
    _relay._pending = bytearray(b"HEADERLIVE")
    check("not wrapped -> no duplication",
          _relay.drain_for_recorder(True), b"HEADERLIVE")

    print()
    if FAILS:
        print(f"{len(FAILS)} FAILED: {', '.join(FAILS)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
