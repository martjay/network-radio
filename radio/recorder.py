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

# Leading bytes buffered before the stream format is identified. The Ogg and
# MP4 headers are longer than a bare MPEG frame, so this must be generous.
_SNIFF_BYTES = 8192


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


_encoder_cache: set[str] | None = None


def ffmpeg_encoders() -> set[str]:
    """Names reported by `ffmpeg -encoders` (cached)."""
    global _encoder_cache
    if _encoder_cache is not None:
        return _encoder_cache
    exe = ffmpeg_path()
    if not exe:
        _encoder_cache = set()
        return _encoder_cache
    try:
        p = subprocess.run(
            [exe, "-hide_banner", "-encoders"],
            capture_output=True, timeout=8, creationflags=CREATE_NO_WINDOW,
        )
        names: set[str] = set()
        for line in p.stdout.decode("utf-8", "replace").splitlines():
            parts = line.strip().split()
            if len(parts) >= 2 and len(parts[0]) >= 5:
                names.add(parts[1])
        _encoder_cache = names
    except Exception:  # noqa: BLE001
        _encoder_cache = set()
    return _encoder_cache


def ffmpeg_audio_pipe_args(bitrate_kbps: int = 192) -> tuple[list[str], str]:
    """Args that write a Qt-playable audio elementary stream to stdout."""
    encoders = ffmpeg_encoders()
    rate = max(64, int(bitrate_kbps) or 192)
    if "libmp3lame" in encoders:
        return (["-c:a", "libmp3lame", "-b:a", f"{rate}k", "-f", "mp3"],
                "audio/mpeg")
    if "aac" in encoders:
        return (["-c:a", "aac", "-b:a", f"{rate}k", "-f", "adts"],
                "audio/aac")
    return (["-c:a", "pcm_s16le", "-ar", "44100", "-ac", "2", "-f", "wav"],
            "audio/wav")


# container -> (extension, muxer, codec)
CONTAINERS = {
    "mp3": ("mp3", "mp3", "copy"),
    "aac": ("aac", "adts", "copy"),
    "m4a": ("m4a", "mp4", "aac"),
    "wav": ("wav", "wav", "pcm_s16le"),
    "ogg": ("ogg", "ogg", "libvorbis"),
    "flac": ("flac", "flac", "flac"),
}

# Which *source* stream formats can be copied bit-for-bit into each container.
# Anything not listed must be re-encoded, otherwise ffmpeg refuses to write the
# header ("Exactly one MP3 audio stream is required") and leaves a 0-byte or
# unplayable file. About a quarter of the catalogue is AAC/Opus/Vorbis, so this
# matters for far more than one station.
COPY_COMPATIBLE = {
    "mp3": {"mp3"},
    "aac": {"aac"},
    "m4a": {"aac", "mp3"},
    "ogg": {"ogg"},
    "flac": {"flac"},
    "wav": set(),          # WAV always needs PCM
}

# Encoder used when the source cannot be copied into the chosen container.
TRANSCODE_ENCODER = {
    "mp3": "libmp3lame",
    "aac": "aac",
    "m4a": "aac",
    "ogg": "libvorbis",
    "flac": "flac",
    "wav": "pcm_s16le",
}

# Human-readable source format names, for the report shown in the UI.
FORMAT_LABELS = {
    "mp3": "MP3", "aac": "AAC", "ogg": "Ogg (Opus/Vorbis)",
    "flac": "FLAC", "unknown": "未知",
}

RECORD_FORMATS = [
    ("mp3", "MP3（原流复制）"),
    ("aac", "AAC（原流复制）"),
    ("m4a", "M4A（AAC 转码）"),
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
        auto_container: bool = False,
    ):
        self.directory = directory
        self.filename = filename
        self.source_url = source_url
        self.title = title
        self.bitrate_kbps = max(64, min(320, int(bitrate_kbps or 192)))
        self.container = container if container in CONTAINERS else "mp3"
        self.requested_container = self.container
        self.auto_container = bool(auto_container)
        self.source = ""
        self.transcoded = False
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
        self._prepared = False
        self._header = b""    # stream header supplied for format detection

    # ------------------------------------------------------------------ #
    def _build_cmd(self, fmt: str) -> list[str]:
        exe = ffmpeg_path() or "ffmpeg"
        _ext, muxer, _codec = CONTAINERS[self.container]
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

        source = self.source_format(fmt)
        can_copy = source in COPY_COMPATIBLE.get(self.container, set())
        if can_copy:
            cmd += ["-c:a", "copy"]
        else:
            # The source cannot live in this container; encode it.
            encoder = TRANSCODE_ENCODER[self.container]
            if encoder in ("aac",):
                cmd += ["-c:a", "aac", "-b:a", f"{self.bitrate_kbps}k"]
            elif encoder == "libvorbis":
                # Vorbis ignores -b:a in favour of a quality scale; 5 ~ 160 kbps.
                cmd += ["-c:a", "libvorbis", "-q:a", "5"]
            elif encoder == "flac":
                cmd += ["-c:a", "flac", "-compression_level", "5"]
            elif encoder == "pcm_s16le":
                cmd += ["-c:a", "pcm_s16le", "-ar", "44100", "-ac", "2"]
            else:
                cmd += ["-c:a", encoder, "-b:a", f"{self.bitrate_kbps}k"]
            self.transcoded = True

        if muxer == "mp4":
            cmd += ["-movflags", "+faststart"]
        cmd += ["-f", muxer, "-y", self.path]
        return cmd

    @property
    def needs_stream_header(self) -> bool:
        """Whether the stream must begin at its header for this format.

        Ogg and FLAC are container formats whose first page carries the codec
        setup; a demuxer cannot start from the middle of them. MP3 and ADTS AAC
        are self-synchronising frame streams, and prefixing them would duplicate
        audio and break frame alignment.

        Defaults to True before the format is known, which is the safe choice:
        an unnecessary header only costs a little duplicated audio at the very
        start, whereas a missing one makes the file unreadable.
        """
        if not self.source:
            return True
        return self.source in ("ogg", "flac")

    @staticmethod
    def source_format(fmt: str) -> str:
        """Normalise a detected demuxer name to a source-format key."""
        if fmt in ("mp3", "aac", "ogg", "flac"):
            return fmt
        if fmt == "vorbis":
            return "ogg"
        if fmt == "opus":
            return "ogg"
        return fmt or "unknown"

    @staticmethod
    def best_container(source: str, requested: str) -> str:
        """Pick a container that can hold `source` losslessly if possible.

        Copy-format requests (MP3/AAC) may remap when the stream cannot live
        in that muxer. Explicit encode formats (WAV/FLAC/OGG/M4A) stay put
        so a user who asked for WAV actually gets a WAV file.
        """
        if requested in ("wav", "flac", "ogg", "m4a"):
            return requested
        if requested and source in COPY_COMPATIBLE.get(requested, set()):
            return requested
        for candidate in ("mp3", "aac", "ogg", "flac", "m4a"):
            if source in COPY_COMPATIBLE.get(candidate, set()):
                return candidate
        return requested or "mp3"

    def _sniff(self, data: bytes) -> str:
        """Decide the demuxer from the first bytes of the stream."""
        head = bytes(data[:16])
        if head.startswith(b"ID3"):
            return "mp3"
        if head.startswith(b"OggS"):
            return "ogg"
        if head.startswith(b"fLaC"):
            return "flac"
        if head.startswith(b"\xff\xf1") or head.startswith(b"\xff\xf9"):
            return "aac"
        if head[:2] == b"\xff\xfb" or head[:2] == b"\xff\xfa" or head[:2] == b"\xff\xf3":
            return "mp3"
        if head.startswith(b"ADIF"):
            return "aac"
        if head[:4] == b"RIFF" and bytes(data[8:12]) == b"WAVE":
            return "wav"
        # Unknown: fall back to the declared source URL.
        low = (self.source_url or "").lower()
        if "opus" in low or "ogg" in low or "vorbis" in low:
            return "ogg"
        if "flac" in low:
            return "flac"
        if "aac" in low:
            return "aac"
        return "mp3"

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

    def prepare(self, first_bytes: bytes) -> None:
        """Choose the real container from the stream, then fix the file name.

        Called as soon as the first bytes arrive. Without this, an Ogg/Opus
        station would be muxed into an .mp3 file and ffmpeg would refuse to
        write the header, leaving an unplayable recording.
        """
        if self._prepared:
            return
        self._prepared = True
        self.source = self.source_format(self._sniff(first_bytes))
        self._choose_container()

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

    def set_header(self, head: bytes) -> None:
        """Identify the stream format from its leading bytes.

        Used only for detection and container selection; the bytes themselves
        are not written, because the recorder starts mid-stream. The relay
        ensures the recorder receives the header as part of its normal feed.
        """
        with self._lock:
            if not head or self._probed:
                return
            self._header = bytes(head)
            self.source = self.source_format(self._sniff(self._header))
            self._choose_container()

    def _choose_container(self) -> None:
        """Pick the real container from `self.source` and update the path."""
        chosen = self.best_container(self.source, self.requested_container) \
            if self.auto_container else self.requested_container
        if chosen == self.container:
            return
        self.container = chosen
        base, _old = os.path.splitext(self.path)
        self.path = f"{base}.{CONTAINERS[chosen][0]}"

    def write(self, data: bytes) -> None:
        """Feed live audio bytes. Called from the relay pump thread."""
        if not data:
            return
        with self._lock:
            self.bytes_in += len(data)
            if self._proc is None:
                # Accumulate enough leading bytes to identify the format. This
                # must append until the threshold is met regardless of how big
                # the incoming chunk is - a large first chunk previously left
                # the buffer empty, so the format was guessed from the URL and
                # an Opus stream was written as .mp3.
                if len(self._first) < _SNIFF_BYTES:
                    self._first += data
                    if len(self._first) < _SNIFF_BYTES:
                        return
                if self._probed:
                    return
                self._probed = True
                # Prefer the retained stream header; fall back to what we got.
                head = self._header or bytes(self._first)
                self.prepare(head)
                fmt = self._sniff(head)
                self._fmt = fmt
                cmd = self._build_cmd(fmt)
                try:
                    # stderr must NOT be a pipe: nothing drains it while the
                    # recording runs, and once the ~64 KB pipe buffer fills
                    # (ffmpeg prints progress roughly once a second) ffmpeg
                    # blocks on write and the recording silently stalls until
                    # stop() times out and kills it.
                    self._proc = subprocess.Popen(
                        cmd,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=CREATE_NO_WINDOW,
                    )
                    try:
                        from .winjob import assign_pid
                        assign_pid(self._proc.pid)
                    except Exception:  # noqa: BLE001
                        pass
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

    def stop(self, timeout: float = 12.0) -> str:
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
            proc.wait(timeout=max(0.4, float(timeout)))
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass
            try:
                proc.wait(timeout=1.5)
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
