"""Stream transport: HTTP(S) fetching, ICY metadata demultiplexing, playlist
resolution and liveness probing.

Qt's bundled multimedia backend on Windows cannot negotiate TLS on every
machine, so the application never hands a remote URL to the audio engine
directly. It fetches upstream itself (with a working TLS stack) and re-serves
clean, metadata-free audio over a loopback HTTP relay. Everything here is the
upstream half of that design.
"""
from __future__ import annotations

import html
import http.client
import re
import socket
import ssl
import subprocess
import sys
import threading
import time
import urllib.parse

from .proxy import ProxyError, make_http_connection

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
ICY_UA = "WinampMPEG/5.09"

PLAYLIST_TYPES = (
    "audio/x-scpls", "audio/x-mpegurl", "audio/mpegurl", "application/pls+xml",
    "application/x-scpls", "text/uri-list", "audio/x-ms-asx", "video/x-ms-asf",
)
AUDIO_TYPES = (
    "audio/", "application/ogg", "application/octet-stream", "video/mp2t",
    "application/vnd.apple.mpegurl", "application/x-mpegurl",
)

_TITLE_RE = re.compile(r"StreamTitle\s*=\s*'(.*?)'\s*;", re.S)


def decode_stream_title(raw: str) -> str:
    """Turn Icecast StreamTitle into readable text.

    Many servers send titles as `application/x-www-form-urlencoded`
    (`Kygo,+Ava+Max` instead of `Kygo, Ava Max`). Percent-decode first;
    only then treat `+` as space when the string has no real spaces yet.
    """
    text = (raw or "").strip("\x00 \r\n")
    if not text:
        return ""
    try:
        text = urllib.parse.unquote(text, errors="replace")
    except Exception:  # noqa: BLE001
        pass
    if "+" in text and " " not in text:
        text = text.replace("+", " ")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


_URL_RE = re.compile(r"StreamUrl\s*=\s*'(.*?)'\s*;", re.S)


# --------------------------------------------------------------------------- #
#  encoded-bitrate detection
#
#  Socket throughput is a poor quality indicator for live radio: servers
#  routinely flush a large backlog on connect, so a 128 kbps stream can look
#  like 250 kbps for the first half minute. Reading the bitrate out of the
#  audio frames themselves is exact, so that is what the interface reports as
#  "measured".
# --------------------------------------------------------------------------- #
_MP3_BITRATES = {
    # key is (version_bits, layer_bits); layer_bits: 3=Layer I, 2=Layer II, 1=Layer III
    # version_bits: 3=MPEG1, 2=MPEG2, 0=MPEG2.5 (shares MPEG2's tables)
    (3, 3): [0, 32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448],
    (3, 2): [0, 32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384],
    (3, 1): [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320],
    (2, 3): [0, 32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256],
    (2, 2): [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160],
    (2, 1): [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160],
}
_MP3_BITRATES[(0, 3)] = _MP3_BITRATES[(2, 3)]
_MP3_BITRATES[(0, 2)] = _MP3_BITRATES[(2, 2)]
_MP3_BITRATES[(0, 1)] = _MP3_BITRATES[(2, 1)]
_MP3_RATES = {3: [44100, 48000, 32000], 2: [22050, 24000, 16000], 0: [11025, 12000, 8000]}
_AAC_RATES = [96000, 88200, 64000, 48000, 44100, 32000, 24000, 22050,
              16000, 12000, 11025, 8000, 7350]


def parse_encoded_bitrate(data: bytes) -> tuple[int, int, int]:
    """Return (bitrate_kbps, sample_rate, channels) read from the stream.

    Handles MPEG audio (Layer I/II/III) and ADTS AAC. Returns zeros when the
    payload is not recognised, so callers can fall back to other estimates.
    """
    if not data:
        return 0, 0, 0

    # ---- MPEG audio: find the first valid frame header -------------------
    limit = min(len(data) - 4, 65536)
    i = 0
    while i < limit:
        if data[i] == 0xFF and (data[i + 1] & 0xE0) == 0xE0:
            b1, b2, b3 = data[i + 1], data[i + 2], data[i + 3]
            ver = (b1 >> 3) & 0x03
            layer = (b1 >> 1) & 0x03
            brx = (b2 >> 4) & 0x0F
            srx = (b2 >> 2) & 0x03
            mode = (b3 >> 6) & 0x03
            if (ver != 1 and layer != 0 and brx not in (0, 15) and srx != 3):
                table = _MP3_BITRATES.get((ver, layer))
                if table:
                    channels = 1 if mode == 3 else 2
                    return table[brx], _MP3_RATES[ver][srx], channels
        i += 1

    # ---- ADTS AAC --------------------------------------------------------
    i = 0
    while i < limit:
        if data[i] == 0xFF and (data[i + 1] & 0xF6) == 0xF0:
            b2, b3 = data[i + 2], data[i + 3]
            srx = (b2 >> 2) & 0x0F
            channels = ((b2 & 0x01) << 2) | ((b3 >> 6) & 0x03)
            frame_len = ((b3 & 0x03) << 11) | (data[i + 4] << 3) | ((data[i + 5] >> 5) & 0x07)
            if srx < len(_AAC_RATES) and frame_len > 0:
                rate = _AAC_RATES[srx]
                # 1024 samples per AAC frame
                kbps = int(round(frame_len * 8 * rate / 1024 / 1000))
                return kbps, rate, channels or 2
        i += 1

    return 0, 0, 0


class StreamError(Exception):
    """Raised when an upstream stream cannot be opened."""


class NeedsFfmpeg(StreamError):
    """Raised when a stream can only be consumed through ffmpeg (HLS)."""

    def __init__(self, message: str = "HLS stream", url: str = ""):
        super().__init__(message)
        self.url = url


# --------------------------------------------------------------------------- #
#  low level connection
# --------------------------------------------------------------------------- #
def _arm_live_socket(sock) -> None:
    """Keep a live Icecast socket open: block on reads, TCP keepalive on NAT."""
    if sock is None:
        return
    try:
        sock.settimeout(None)
    except OSError:
        pass
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    except OSError:
        pass
    if sys.platform == "win32":
        try:
            sock.ioctl(socket.SIO_KEEPALIVE_VALS, (1, 45_000, 5_000))
        except (OSError, AttributeError):
            pass
        return
    for opt, val in (
        (getattr(socket, "TCP_KEEPIDLE", None), 45),
        (getattr(socket, "TCP_KEEPINTVL", None), 10),
        (getattr(socket, "TCP_KEEPCNT", None), 8),
    ):
        if opt is None:
            continue
        try:
            sock.setsockopt(socket.IPPROTO_TCP, opt, val)
        except OSError:
            pass


def _make_conn(scheme: str, host: str, port: int, timeout: float, verify: bool,
               proxy=None):
    """Build an http.client connection, routed through `proxy` when needed."""
    if proxy is not None and proxy.should_proxy(host):
        return make_http_connection(scheme, host, port, timeout, verify, proxy)
    if scheme == "https":
        ctx = ssl.create_default_context()
        if not verify:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        return http.client.HTTPSConnection(host, port, timeout=timeout, context=ctx)
    return http.client.HTTPConnection(host, port, timeout=timeout)


def _request(url: str, timeout: float, icy: bool = True, max_redirects: int = 8,
             proxy=None):
    """Open `url`, following redirects. Returns (conn, response, final_url)."""
    seen: list[str] = []
    for _ in range(max_redirects):
        parts = urllib.parse.urlsplit(url)
        scheme = (parts.scheme or "http").lower()
        if scheme not in ("http", "https"):
            raise StreamError(f"unsupported scheme: {scheme}")
        host = parts.hostname
        if not host:
            raise StreamError("no host in url")
        port = parts.port or (443 if scheme == "https" else 80)
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        seen.append(url)

        headers = {
            "User-Agent": ICY_UA if icy else DEFAULT_UA,
            "Accept": "*/*",
            "Connection": "close",
        }
        if icy:
            headers["Icy-MetaData"] = "1"

        last_exc: Exception | None = None
        for verify in (True, False):
            try:
                conn = _make_conn(scheme, host, port, timeout, verify, proxy)
                conn.request("GET", path, headers=headers)
                resp = conn.getresponse()
                break
            except ssl.SSLError as exc:
                last_exc = exc
                continue
            except ProxyError as exc:
                raise StreamError(str(exc)) from exc
            except (socket.timeout, TimeoutError) as exc:
                raise StreamError("connection timed out") from exc
            except (OSError, http.client.HTTPException) as exc:
                last_exc = exc
                continue
        else:
            raise StreamError(f"connect failed: {last_exc}")

        status = resp.status
        if status in (301, 302, 303, 307, 308):
            loc = resp.getheader("Location")
            conn.close()
            if not loc:
                raise StreamError(f"HTTP {status} without Location")
            nxt = urllib.parse.urljoin(url, loc)
            if nxt in seen:
                raise StreamError("redirect loop")
            url = nxt
            continue
        if status in (401, 403):
            conn.close()
            raise StreamError(f"HTTP {status} access denied")
        if status >= 400:
            conn.close()
            raise StreamError(f"HTTP {status}")
        return conn, resp, url

    raise StreamError("too many redirects")


def content_kind(content_type: str) -> str:
    ct = (content_type or "").split(";")[0].strip().lower()
    if any(ct.startswith(t) for t in PLAYLIST_TYPES):
        return "playlist"
    if ct.endswith((".m3u", ".m3u8", ".pls")) or "mpegurl" in ct or "scpls" in ct:
        return "playlist"
    if any(ct.startswith(t) for t in AUDIO_TYPES):
        return "audio"
    if ct in ("text/html", "text/plain", "application/json"):
        return "text"
    return "unknown"


def guess_audio_type(url: str, fallback: str = "audio/mpeg") -> str:
    low = url.lower()
    if ".aac" in low or "aacp" in low:
        return "audio/aacp"
    if ".ogg" in low or "ogg" in low:
        return "audio/ogg"
    if ".opus" in low:
        return "audio/ogg"
    if "m3u8" in low:
        return "application/vnd.apple.mpegurl"
    return fallback


def parse_playlist(text: str, base: str = "") -> list[str]:
    """Extract stream URLs from M3U / PLS / ASX / plain-text playlists."""
    out: list[str] = []
    if not text:
        return out
    low = text.lower()
    if "<asx" in low or "<entry" in low:
        for m in re.finditer(r'href\s*=\s*["\']([^"\']+)["\']', text, re.I):
            out.append(m.group(1).strip())
    if "file1=" in low or "[playlist]" in low:
        for m in re.finditer(r"^\s*File\d*\s*=\s*(.+)$", text, re.I | re.M):
            out.append(m.group(1).strip())
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith(("http://", "https://")):
            out.append(line)
        elif line.lower().startswith(("file=",)):
            out.append(line.split("=", 1)[1].strip())

    resolved: list[str] = []
    for u in out:
        u = u.strip().strip('"\'')
        if u.startswith(("http://", "https://")):
            resolved.append(urllib.parse.urljoin(base, u) if base else u)
    # de-duplicate, preserve order
    seen: set[str] = set()
    uniq: list[str] = []
    for u in resolved:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq


# --------------------------------------------------------------------------- #
#  ICY aware reader
# --------------------------------------------------------------------------- #
class StreamReader:
    """Reads an audio stream, transparently stripping ICY metadata blocks.

    `read(n)` returns *audio* bytes only. Interleaved `StreamTitle` blocks are
    parsed out and exposed via `now_playing`.
    """

    def __init__(self, url: str, timeout: float = 12.0, proxy=None):
        self.url = url
        self.final_url = url
        self.timeout = timeout
        self.proxy = proxy
        self.headers: dict[str, str] = {}
        self.content_type = ""
        self.icy_name = ""
        self.now_playing = ""
        self.bitrate_hint = 0
        self.bytes_audio = 0
        self.opened_at = 0.0
        self._measured_from = 0.0
        self._mark_bytes = 0
        self._sniff = bytearray()
        self._sniffed = False
        self.encoded_kbps = 0
        self.encoded_rate = 0
        self.encoded_channels = 0
        self._conn = None
        self._resp = None
        self._metaint = 0
        self._need = 0
        self._meta_len = 0
        self._meta_raw = b""
        self._audio = bytearray()
        self._eof = False

    # -- lifecycle ---------------------------------------------------------
    def open(self, resolve_playlist: bool = True) -> "StreamReader":
        conn, resp, final = _request(self.url, self.timeout, icy=True, proxy=self.proxy)
        ct = resp.getheader("Content-Type", "") or ""
        kind = content_kind(ct)

        if kind == "playlist" or (resolve_playlist and self._looks_like_playlist_url()):
            body = self._read_small(resp)
            conn.close()
            # HLS manifests are not a list of stream URLs but a segment
            # timeline: hand those to ffmpeg, which can consume them directly.
            if self._is_hls(body, ct):
                raise NeedsFfmpeg("HLS stream", self.url)
            links = parse_playlist(body.decode("utf-8", "replace"), final)
            if not links:
                raise NeedsFfmpeg("playlist contained no direct stream url", self.url)
            # Recurse once into the first usable entry.
            last: Exception | None = None
            for link in links[:4]:
                try:
                    return StreamReader(link, self.timeout, proxy=self.proxy).open(resolve_playlist=False)
                except NeedsFfmpeg as exc:
                    raise NeedsFfmpeg(str(exc) or "HLS stream", exc.url or link) from exc
                except StreamError as exc:
                    last = exc
            raise StreamError(f"playlist targets unreachable: {last}")

        if kind == "text":
            body = self._read_small(resp)
            conn.close()
            links = parse_playlist(body.decode("utf-8", "replace"), final)
            if links:
                return StreamReader(links[0], self.timeout, proxy=self.proxy).open(resolve_playlist=False)
            raise StreamError("server returned a web page, not audio")

        self._conn, self._resp, self.final_url = conn, resp, final
        self.headers = {k.lower(): v for k, v in resp.getheaders()}
        self.content_type = ct or guess_audio_type(final)
        self.icy_name = (resp.getheader("icy-name") or "").strip()
        try:
            self._metaint = int(resp.getheader("icy-metaint") or 0)
        except ValueError:
            self._metaint = 0
        try:
            self.bitrate_hint = int(resp.getheader("icy-br") or 0) * 1000
        except ValueError:
            self.bitrate_hint = 0
        self._need = self._metaint
        self.opened_at = time.time()
        # The connection timeout must not apply to the live read: Icecast
        # sockets stay quiet during talk/pause, and a 14s socket timeout
        # would kill a healthy station with "stream stalled".
        sock = getattr(self._conn, "sock", None)
        _arm_live_socket(sock)
        return self

    def _looks_like_playlist_url(self) -> bool:
        low = self.url.lower().split("?")[0]
        return low.endswith((".m3u", ".m3u8", ".pls", ".asx"))

    @staticmethod
    def _is_hls(body: bytes, content_type: str) -> bool:
        ct = (content_type or "").lower()
        if "mpegurl" in ct or "vnd.apple" in ct:
            return True
        head = body[:400].lstrip()
        return head.startswith(b"#EXTM3U") and (b"#EXT-X-" in body[:4096] or b".ts" in body[:4096])

    @staticmethod
    def _read_small(resp, limit: int = 262144) -> bytes:
        chunks: list[bytes] = []
        total = 0
        while total < limit:
            try:
                b = resp.read(8192)
            except Exception:  # noqa: BLE001
                break
            if not b:
                break
            chunks.append(b)
            total += len(b)
        return b"".join(chunks)

    def close(self) -> None:
        for obj in (self._resp, self._conn):
            try:
                if obj is not None:
                    obj.close()
            except Exception:  # noqa: BLE001
                pass
        self._resp = None
        self._conn = None
        self._eof = True

    # -- metadata ----------------------------------------------------------
    def _parse_meta(self, raw: bytes) -> None:
        if not raw:
            return
        text = raw.decode("latin-1", "replace").strip("\x00 \r\n")
        if not text:
            return
        m = _TITLE_RE.search(text)
        if m:
            title = decode_stream_title(m.group(1))
            if title and title != self.now_playing:
                self.now_playing = title
            return
        # some servers send a bare string
        if "=" not in text and 2 < len(text) < 200:
            self.now_playing = decode_stream_title(text)

    # -- reading -----------------------------------------------------------
    def _raw_read(self, n: int) -> bytes:
        if self._eof or self._resp is None:
            return b""
        try:
            data = self._resp.read(n)
        except (socket.timeout, TimeoutError) as exc:
            raise StreamError("stream stalled") from exc
        except AttributeError:
            # The response was closed underneath us (relay shutdown).
            self._eof = True
            return b""
        except (OSError, ValueError, http.client.HTTPException) as exc:
            raise StreamError(f"stream error: {exc}") from exc
        if not data:
            self._eof = True
        return data or b""

    def read(self, n: int = 8192) -> bytes:
        """Return up to n bytes of audio (never ICY metadata)."""
        if self._eof and not self._audio:
            return b""
        guard = 0
        while len(self._audio) < n and not self._eof and guard < 64:
            guard += 1
            chunk = self._raw_read(16384)
            if not chunk:
                break
            if self._metaint <= 0:
                self._audio += chunk
                continue
            self._demux_icy(chunk)
        out = bytes(self._audio[:n])
        del self._audio[:n]
        self.bytes_audio += len(out)
        if not self._sniffed and out:
            self._sniff += out
            if len(self._sniff) >= 8192:
                self._sniffed = True
                br, rate, ch = parse_encoded_bitrate(bytes(self._sniff))
                self.encoded_kbps, self.encoded_rate, self.encoded_channels = br, rate, ch
                self._sniff = bytearray()
        return out

    def _demux_icy(self, data: bytes) -> None:
        i = 0
        ln = len(data)
        while i < ln:
            if self._meta_len > 0:
                take = min(self._meta_len, ln - i)
                self._meta_raw += data[i:i + take]
                i += take
                self._meta_len -= take
                if self._meta_len == 0:
                    self._parse_meta(self._meta_raw)
                    self._meta_raw = b""
                    self._need = self._metaint
                continue
            if self._need > 0:
                take = min(self._need, ln - i)
                self._audio += data[i:i + take]
                i += take
                self._need -= take
                continue
            # metadata length byte
            blocks = data[i]
            i += 1
            self._meta_len = blocks * 16
            if self._meta_len == 0:
                self._need = self._metaint

    @property
    def live_seconds(self) -> float:
        return max(0.0, time.time() - self.opened_at) if self.opened_at else 0.0

    @property
    def measured_kbps(self) -> float:
        """Average throughput over the steady-state window.

        The first seconds of a stream arrive in a burst (server-side buffer
        flush), so including them overstates the real bitrate. `mark` resets
        the measurement window once the burst has drained.
        """
        secs = self.live_seconds - self._measured_from
        if secs < 2.0:
            return 0.0
        return ((self.bytes_audio - self._mark_bytes) * 8.0 / 1000.0) / secs

    def mark(self) -> None:
        """Restart the throughput measurement window."""
        self._measured_from = self.live_seconds
        self._mark_bytes = self.bytes_audio


def _friendly_hls_error(stderr: str) -> str:
    text = (stderr or "").strip()
    low = text.lower()
    if "unknown encoder" in low or "encoder not found" in low:
        return "当前 ffmpeg 缺少音频编码器，无法转码 HLS"
    if re.search(r"server returned 40[13]|http error 40[13]|access denied", low):
        return "HLS 服务器拒绝访问"
    if re.search(r"server returned 404|http error 404", low):
        return "HLS 地址无效"
    if "certificate" in low or "ssl" in low or "tls" in low:
        return "HLS 证书校验失败"
    if "timed out" in low or "timeout" in low:
        return "HLS 连接超时"
    if "connection refused" in low:
        return "HLS 连接被拒绝"
    if "does not contain any stream" in low or "matches no streams" in low:
        return "该 HLS 流没有可用音频"
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if lines:
        return f"无法打开 HLS 流：{lines[-1][:160]}"
    return "ffmpeg 无法打开该 HLS 流"


# --------------------------------------------------------------------------- #
#  ffmpeg backed reader (HLS and other segmented protocols)
# --------------------------------------------------------------------------- #
class FfmpegReader:
    """Reads audio through an ffmpeg subprocess.

    Used for HLS manifests, which are a segment timeline rather than a byte
    stream. ffmpeg remuxes/encodes to a Qt-playable elementary stream so the
    rest of the pipeline sees the same kind of bytes it gets from Icecast.
    """

    def __init__(self, url: str, timeout: float = 20.0, bitrate_kbps: int = 192,
                 proxy=None, proxy_shim_url: str = ""):
        self.url = url
        self.timeout = timeout
        self.bitrate_kbps = bitrate_kbps
        self.proxy = proxy
        self.proxy_shim_url = proxy_shim_url
        self.final_url = url
        self.content_type = "audio/mpeg"
        self.icy_name = ""
        self.now_playing = ""
        self.bitrate_hint = bitrate_kbps * 1000
        self.bytes_audio = 0
        self.opened_at = 0.0
        self._measured_from = 0.0
        self._mark_bytes = 0
        self._proc: subprocess.Popen | None = None
        self._first = b""
        self._sniff = bytearray()
        self._sniffed = False
        self._err = bytearray()
        self.encoded_kbps = 0
        self.encoded_rate = 0
        self.encoded_channels = 0

    def open(self, resolve_playlist: bool = True) -> "FfmpegReader":
        from .recorder import CREATE_NO_WINDOW, ffmpeg_audio_pipe_args, ffmpeg_path

        exe = ffmpeg_path()
        if not exe:
            raise StreamError("该电台使用 HLS 格式，需要 ffmpeg 支持（未找到 ffmpeg）")
        out_args, content_type = ffmpeg_audio_pipe_args(self.bitrate_kbps)
        last_err = ""
        for rich in (True, False):
            cmd = self._build_cmd(exe, out_args, rich_hls=rich)
            try:
                proc = self._spawn(cmd, CREATE_NO_WINDOW)
            except Exception as exc:  # noqa: BLE001
                raise StreamError(f"无法启动 ffmpeg：{exc}") from exc
            first = self._wait_stdout(proc, self.timeout)
            if first:
                self._proc = proc
                self._first = first
                self.content_type = content_type
                self.opened_at = time.time()
                self.encoded_kbps = self.bitrate_kbps
                return self
            last_err = bytes(self._err).decode("utf-8", "replace")
            self._stop_proc(proc)
            low = last_err.lower()
            if rich and ("option not found" in low or "unrecognized option" in low
                         or not last_err):
                continue
            break
        raise StreamError(_friendly_hls_error(last_err))

    def _build_cmd(self, exe: str, out_args: list[str], *, rich_hls: bool) -> list[str]:
        us = str(int(max(self.timeout, 15.0) * 1_000_000))
        parsed = urllib.parse.urlparse(self.url)
        origin = f"{parsed.scheme}://{parsed.netloc}/"
        cmd = [exe, "-hide_banner", "-loglevel", "error", "-nostdin"]
        if rich_hls:
            cmd += [
                "-protocol_whitelist",
                "file,http,https,tcp,tls,crypto,udp,rtp,httpproxy",
                "-allowed_extensions", "ALL",
                "-reconnect", "1",
                "-reconnect_streamed", "1",
                "-reconnect_delay_max", "4",
                "-seekable", "0",
                "-fflags", "+genpts+discardcorrupt",
            ]
        cmd += [
            "-rw_timeout", us,
            "-user_agent", DEFAULT_UA,
            "-headers", f"Referer: {origin}\r\n",
        ]
        if self.proxy_shim_url:
            # Route ffmpeg through the local CONNECT shim, which handles HTTP,
            # HTTPS, SOCKS5 and credentials uniformly.
            cmd += ["-http_proxy", self.proxy_shim_url]
        cmd += ["-i", self.url, "-vn", "-sn", "-dn"]
        cmd += out_args
        cmd += ["pipe:1"]
        return cmd

    def _spawn(self, cmd: list[str], creationflags: int) -> subprocess.Popen:
        self._err = bytearray()
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            bufsize=0,
            creationflags=creationflags,
        )

        def drain() -> None:
            try:
                while True:
                    chunk = proc.stderr.read(512)  # type: ignore[union-attr]
                    if not chunk:
                        break
                    self._err.extend(chunk)
                    if len(self._err) > 12000:
                        del self._err[: len(self._err) - 6000]
            except Exception:  # noqa: BLE001
                pass

        threading.Thread(target=drain, daemon=True, name="ffmpeg-err").start()
        return proc

    def _wait_stdout(self, proc: subprocess.Popen, timeout: float) -> bytes:
        bucket: list[bytes] = []

        def read() -> None:
            try:
                bucket.append(proc.stdout.read(8192) or b"")  # type: ignore[union-attr]
            except Exception:  # noqa: BLE001
                bucket.append(b"")

        t = threading.Thread(target=read, daemon=True, name="ffmpeg-out")
        t.start()
        t.join(max(1.0, timeout))
        if not bucket and proc.poll() is not None:
            t.join(0.4)
        return bucket[0] if bucket else b""

    @staticmethod
    def _stop_proc(proc: subprocess.Popen | None) -> None:
        if proc is None:
            return
        # Kill first. Closing stdout while the pump thread is blocked in
        # read() deadlocks on Windows and leaves Broadcast.exe behind.
        try:
            if proc.poll() is None:
                proc.kill()
        except Exception:  # noqa: BLE001
            pass
        for stream in (proc.stdout, proc.stdin, proc.stderr):
            try:
                if stream:
                    stream.close()
            except Exception:  # noqa: BLE001
                pass
        try:
            proc.wait(timeout=1.5)
        except Exception:  # noqa: BLE001
            pass

    def read(self, n: int = 8192) -> bytes:
        if self._proc is None:
            return b""
        pending = getattr(self, "_first", b"")
        if pending:
            out, self._first = pending[:n], pending[n:]
            self.bytes_audio += len(out)
            return out
        try:
            data = self._proc.stdout.read(n)  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            data = b""
        if not data:
            self._eof = True
            return b""
        self.bytes_audio += len(data)
        if not self._sniffed:
            self._sniff += data
            if len(self._sniff) >= 8192:
                self._sniffed = True
                br, rate, ch = parse_encoded_bitrate(bytes(self._sniff))
                if rate:
                    self.encoded_rate, self.encoded_channels = rate, ch
                self._sniff = bytearray()
        return data

    def close(self) -> None:
        proc, self._proc = self._proc, None
        self._stop_proc(proc)

    @property
    def live_seconds(self) -> float:
        return max(0.0, time.time() - self.opened_at) if self.opened_at else 0.0

    @property
    def measured_kbps(self) -> float:
        secs = self.live_seconds - self._measured_from
        if secs < 2.0:
            return 0.0
        return ((self.bytes_audio - self._mark_bytes) * 8.0 / 1000.0) / secs

    def mark(self) -> None:
        self._measured_from = self.live_seconds
        self._mark_bytes = self.bytes_audio


def open_stream(url: str, timeout: float = 14.0, proxy=None, shim_factory=None):
    """Open `url`, transparently falling back to ffmpeg for HLS sources.

    `shim_factory` is called only when ffmpeg is actually needed; it returns
    the URL of a local CONNECT proxy that ffmpeg should route through (or an
    empty string for a direct connection).
    """
    try:
        return StreamReader(url, timeout=timeout, proxy=proxy).open()
    except NeedsFfmpeg as exc:
        shim_url = ""
        if shim_factory is not None and proxy is not None and proxy.usable:
            shim_url = shim_factory() or ""
        return FfmpegReader(
            exc.url or url, timeout=max(timeout, 22.0),
            proxy=proxy, proxy_shim_url=shim_url,
        ).open()


# --------------------------------------------------------------------------- #
#  liveness probe (used by the "verify stream" action and the health sweep)
# --------------------------------------------------------------------------- #
def probe(url: str, timeout: float = 10.0, want_bytes: int = 8192, proxy=None,
          shim_factory=None) -> dict:
    """Open `url` and pull real audio. Returns a dict describing the result."""
    t0 = time.time()
    reader = None
    try:
        reader = open_stream(url, timeout=timeout, proxy=proxy,
                             shim_factory=shim_factory)
        buf = bytearray()
        deadline = t0 + timeout
        while len(buf) < want_bytes and time.time() < deadline:
            chunk = reader.read(4096)
            if not chunk:
                break
            buf += chunk
        elapsed = time.time() - t0
        if not buf:
            return {"ok": False, "error": "no audio data", "seconds": round(elapsed, 2)}
        return {
            "ok": True,
            "error": "",
            "content_type": reader.content_type,
            "icy_name": reader.icy_name,
            "now_playing": reader.now_playing,
            "bytes": len(buf),
            "kbps": round(len(buf) * 8 / max(elapsed, 0.05) / 1000, 1),
            "seconds": round(elapsed, 2),
            "final_url": reader.final_url,
        }
    except StreamError as exc:
        return {"ok": False, "error": str(exc), "seconds": round(time.time() - t0, 2)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "seconds": round(time.time() - t0, 2)}
    finally:
        if reader is not None:
            reader.close()
