"""Recording.

Audio arriving at the relay is teed into a background encoder process. The
process is fed raw MP3/AAC bytes from the live stream and re-muxed (never
re-encoded) into the chosen container, so recordings are bit-exact copies of
what was broadcast.

Input is auto-detected rather than assumed: MP3 and AAC elementary streams
need different demuxers, and some servers emit ID3/ADTS with odd framing.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def ffmpeg_path() -> str | None:
    """Locate ffmpeg: explicit setting, bundled copy, then PATH."""
    env = os.environ.get("BROADCAST_FFMPEG")
    if env and os.path.isfile(env):
        return env
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for cand in ("ffmpeg.exe", "ffmpeg"):
        p = os.path.join(here, "bin", cand)
        if os.path.isfile(p):
            return p
    found = shutil.which("ffmpeg")
    if found:
        return found
    for p in (r"C:\ffmpeg\bin\ffmpeg.exe", "/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/opt/homebrew/bin/ffmpeg"):
        if os.path.isfile(p):
            return p
    return None


def ffmpeg_available() -> bool:
    return ffmpeg_path() is not None


# container -> (extension, muxer, codec)
CONTAINERS = {
    "mp3": ("mp3", "mp3", "copy"),
    "aac": ("aac", "adts", "copy"),
    "m4a": ("m4a", "mp4", "aac"),
    "wav": ("wav", "wav", "pcm_s16le"),
    "ogg": ("ogg", "ogg", "libvorbis"),
    "flac": ("flac", "flac", "flac"),
}

RECORD_FORMATS = [
    ("mp3", "MP3（原流复制）"),
    ("aac", "AAC（原流复制）"),
    ("m4a", "M4A / AAC"),
    ("ogg", "OGG Vorbis"),
    ("flac", "FLAC 无损"),
    ("wav", "WAV 无损"),
]

# MPEG audio frame tables, used to keep the recorded stream frame-aligned.
# key is (version_bits, layer_bits); version: 3=MPEG1, 2=MPEG2, 0=MPEG2.5
_MP3_FRAME_BITRATES = {
    (3, 3): [0, 32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448],
    (3, 2): [0, 32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384],
    (3, 1): [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320],
    (2, 3): [0, 32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256],
    (2, 2): [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160],
    (2, 1): [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160],
}
_MP3_FRAME_BITRATES[(0, 3)] = _MP3_FRAME_BITRATES[(2, 3)]
_MP3_FRAME_BITRATES[(0, 2)] = _MP3_FRAME_BITRATES[(2, 2)]
_MP3_FRAME_BITRATES[(0, 1)] = _MP3_FRAME_BITRATES[(2, 1)]
_MP3_RATES = {3: [44100, 48000, 32000], 2: [22050, 24000, 16000], 0: [11025, 12000, 8000]}


class Recorder:
    """Streams live audio into an ffmpeg process writing a file on disk."""

    def __init__(
        self,
        directory: str,
        filename: str,
        source_url: str = "",
        title: str = "",
        bitrate_kbps: int = 192,
        container: str = "mp3",
    ):
        self.directory = directory
        self.filename = filename
        self.source_url = source_url
        self.title = title
        self.bitrate_kbps = max(64, min(320, int(bitrate_kbps or 192)))
        self.container = container if container in CONTAINERS else "mp3"
        self.path = os.path.join(directory, filename)
        self.started_at = 0.0
        self.bytes_in = 0
        self.error = ""

        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._first = bytearray()
        self._probed = False
        self._fmt = ""
        self._tail = b""      # trailing partial frame held back between writes

    # ------------------------------------------------------------------ #
    def _build_cmd(self, fmt: str) -> list[str]:
        exe = ffmpeg_path() or "ffmpeg"
        ext, muxer, codec = CONTAINERS[self.container]
        cmd = [
            exe, "-hide_banner", "-loglevel", "error", "-nostdin",
            "-f", fmt,
            "-i", "pipe:0",
            "-vn",
            "-map_metadata", "-1",
            "-metadata", f"title={self.title or 'Radio recording'}",
            "-metadata", f"comment=Recorded from {self.source_url}",
            "-metadata", f"date={time.strftime('%Y-%m-%d')}",
        ]
        if codec == "copy":
            cmd += ["-c:a", "copy"]
        elif codec == "aac":
            cmd += ["-c:a", "aac", "-b:a", f"{self.bitrate_kbps}k"]
        elif codec == "pcm_s16le":
            cmd += ["-c:a", "pcm_s16le", "-ar", "44100", "-ac", "2"]
        elif codec == "libvorbis":
            cmd += ["-c:a", "libvorbis", "-q:a", "5"]
        elif codec == "flac":
            cmd += ["-c:a", "flac", "-compression_level", "5"]
        if muxer == "mp4":
            cmd += ["-movflags", "+faststart"]
        cmd += ["-f", muxer, "-y", self.path]
        return cmd

    def _sniff(self, data: bytes) -> str:
        """Decide the demuxer from the first bytes of the stream."""
        head = bytes(self._first[:16])
        if head.startswith(b"ID3"):
            return "mp3"
        if head.startswith(b"\xff\xf1") or head.startswith(b"\xff\xf9"):
            return "aac"
        if head[:2] == b"\xff\xfb" or head[:2] == b"\xff\xfa" or head[:2] == b"\xff\xf3":
            return "mp3"
        if head.startswith(b"OggS"):
            return "ogg"
        if head.startswith(b"ADIF"):
            return "aac"
        # fall back on the declared source type
        return "aac" if "aac" in (self.source_url or "").lower() else "mp3"

    @staticmethod
    def _align(data: bytes, fmt: str) -> bytes:
        """Drop the partial frame at the head of the buffer.

        Recording starts mid-stream, so the first bytes are almost always the
        tail of a frame that began before we connected. Feeding that to the
        demuxer makes decoders report a backstep error and can produce an
        audible glitch at the start of the file, so we cut to the first sync
        word instead.
        """
        limit = min(len(data) - 6, 8192)
        if limit <= 0:
            return data
        if data.startswith(b"ID3"):
            return data  # let the demuxer consume the tag itself
        if fmt == "mp3":
            for i in range(limit):
                if data[i] == 0xFF and (data[i + 1] & 0xE0) == 0xE0:
                    ver = (data[i + 1] >> 3) & 0x03
                    layer = (data[i + 1] >> 1) & 0x03
                    brx = (data[i + 2] >> 4) & 0x0F
                    srx = (data[i + 2] >> 2) & 0x03
                    if ver != 1 and layer != 0 and brx not in (0, 15) and srx != 3:
                        return data[i:]
        elif fmt == "aac":
            for i in range(limit):
                if data[i] == 0xFF and (data[i + 1] & 0xF6) == 0xF0:
                    return data[i:]
        return data

    # ------------------------------------------------------------------ #
    def start(self) -> None:
        if not ffmpeg_available():
            raise RuntimeError("未找到 ffmpeg，请安装后重试（录制功能需要 ffmpeg）")
        os.makedirs(self.directory, exist_ok=True)
        self.started_at = time.time()

    @staticmethod
    def _frame_length(data: bytes, i: int) -> int:
        """Length of the MPEG audio frame whose header starts at `i`, or 0."""
        if i + 4 > len(data):
            return 0
        if data[i] != 0xFF or (data[i + 1] & 0xE0) != 0xE0:
            return 0
        b1, b2 = data[i + 1], data[i + 2]
        ver = (b1 >> 3) & 0x03
        layer = (b1 >> 1) & 0x03
        brx = (b2 >> 4) & 0x0F
        srx = (b2 >> 2) & 0x03
        pad = (b2 >> 1) & 0x01
        table = _MP3_FRAME_BITRATES.get((ver, layer))
        if not table or brx in (0, 15) or srx == 3:
            return 0
        rate = _MP3_RATES[ver][srx]
        coeff = 144 if ver == 3 else 72
        return (coeff * table[brx] * 1000 // rate) + pad

    @classmethod
    def _trim_partial_frame(cls, tail: bytes, fmt: str) -> bytes:
        """Return `tail` truncated to the last complete frame.

        Recording stops between frames, so the final buffer usually ends with
        a partial frame. Leaving it in makes decoders report a backstep error
        on the last frame, so the partial frame is dropped and held back until
        the rest of it arrives.
        """
        if not tail or fmt != "mp3":
            return tail
        n = len(tail)
        i = 0
        last_end = 0
        while i < n:
            length = cls._frame_length(tail, i)
            if length:
                if i + length > n:
                    # a frame begins here but has not fully arrived
                    return tail[:i]
                last_end = i + length
                i = last_end
                continue
            i += 1
        # Trailing bytes too short to form a header (or to be parsed) are also
        # an incomplete frame, so cut back to the last complete one.
        return tail[:last_end]

    def write(self, data: bytes) -> None:
        """Feed live audio bytes. Called from the relay pump thread."""
        if not data:
            return
        with self._lock:
            self.bytes_in += len(data)
            if self._proc is None:
                if len(self._first) < 4096:
                    self._first += data
                    if len(self._first) < 2048:
                        return
                if self._probed:
                    return
                self._probed = True
                fmt = self._sniff(data)
                self._fmt = fmt
                cmd = self._build_cmd(fmt)
                try:
                    self._proc = subprocess.Popen(
                        cmd,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE,
                        creationflags=CREATE_NO_WINDOW,
                    )
                except Exception as exc:  # noqa: BLE001
                    self.error = f"无法启动 ffmpeg: {exc}"
                    return
                pending = self._align(bytes(self._first), fmt)
                self._first.clear()
                self._feed(pending)
                return

            if self._fmt == "mp3":
                # hold back the trailing partial frame
                data = self._tail + data
                trimmed = self._trim_partial_frame(data, "mp3")
                self._tail = data[len(trimmed):]
                if not trimmed:
                    return
                self._feed(trimmed)
                return
            self._feed(data)

    def _feed(self, data: bytes) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None or not data:
            return
        try:
            proc.stdin.write(data)
        except (BrokenPipeError, OSError):
            self._collect_error()

    def _collect_error(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        try:
            err = proc.stderr.read(4096)
            if err:
                text = err.decode("utf-8", "replace").strip().splitlines()
                if text:
                    self.error = text[-1][:200]
        except Exception:  # noqa: BLE001
            pass

    def stop(self) -> str:
        with self._lock:
            proc, self._proc = self._proc, None
            pending = bytes(self._first)
            self._first.clear()
            # The held-back tail is by definition an incomplete frame; writing
            # it would leave a truncated frame at the end of the file, which is
            # what makes decoders report a backstep error. Drop it.
            self._tail = b""
            if proc is not None and pending:
                try:
                    proc.stdin.write(pending)  # type: ignore[union-attr]
                except Exception:  # noqa: BLE001
                    pass
        if proc is None:
            return ""
        try:
            if proc.stdin:
                proc.stdin.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            proc.wait(timeout=12)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=3)
            except Exception:  # noqa: BLE001
                pass
        self._collect_error()
        if not os.path.exists(self.path):
            return ""
        return self.path

    @property
    def elapsed(self) -> float:
        return max(0.0, time.time() - self.started_at) if self.started_at else 0.0

    @property
    def size(self) -> int:
        try:
            return os.path.getsize(self.path)
        except OSError:
            return 0


def write_tags(path: str, station: dict, duration_s: float = 0.0) -> bool:
    """Write ID3 tags onto a finished recording without re-encoding."""
    if not path or not os.path.isfile(path) or not ffmpeg_available():
        return False
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    muxer = {"mp3": "mp3", "aac": "adts", "m4a": "mp4", "ogg": "ogg", "flac": "flac", "wav": "wav"}.get(ext)
    if not muxer:
        return False
    tmp = path + ".tagging"
    cmd = [
        ffmpeg_path() or "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
        "-i", path, "-c", "copy",
        "-metadata", f"title={station.get('name', '')}",
        "-metadata", f"artist={station.get('country', '')}",
        "-metadata", f"genre={station.get('genre_label', station.get('genre', ''))}",
        "-metadata", f"comment={station.get('url', '')}",
        "-metadata", f"date={time.strftime('%Y')}",
        "-f", muxer, "-y", tmp,
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=120, creationflags=CREATE_NO_WINDOW)
    except Exception:  # noqa: BLE001
        return False
    if os.path.isfile(tmp) and os.path.getsize(tmp) > 0:
        try:
            os.replace(tmp, path)
            return True
        except OSError:
            try:
                os.remove(tmp)
            except OSError:
                pass
    return False


def sanitize(name: str, limit: int = 70) -> str:
    safe = re.sub(r'[\\/:*?"<>|]+', "_", name or "radio").strip(" ._")
    safe = re.sub(r"\s+", " ", safe)
    return (safe[:limit] or "radio")
