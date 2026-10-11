"""Loopback HTTP relay.

The audio engine (Qt Multimedia) is pointed at `http://127.0.0.1:<port>/stream`
instead of a remote URL. The relay:

  * performs the upstream connection with a full TLS stack,
  * strips ICY metadata so the decoder sees a contiguous audio stream,
  * reports live transport statistics to the UI,
  * tees the same audio into a recorder when one is armed.

One relay instance serves exactly one station at a time.
"""
from __future__ import annotations

import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .net import StreamError, open_stream, guess_audio_type
from .proxy import LocalProxyShim

CHUNK = 16384
# ~10 s of 320 kbps audio. Small enough that the relay never runs far ahead of
# the decoder (live latency stays low), large enough to ride out a hiccup.
RING_BYTES = 400 * 1024


class _Ring:
    """Bounded byte buffer shared between the upstream pump and HTTP clients.

    When the consumer falls behind, the writer blocks. That backpressure is
    deliberate: it propagates to the upstream socket so the relay self-paces
    with the decoder instead of buffering unboundedly. Only if the consumer
    stays stalled past `write_timeout` is the oldest audio discarded, which
    keeps a live stream live rather than minutes behind.
    """

    def __init__(self, capacity: int, write_timeout: float = 4.0):
        self._buf = bytearray()
        self._cap = capacity
        self._cv = threading.Condition()
        self._closed = False
        self._dropped = 0
        self._write_timeout = write_timeout

    def write(self, data: bytes) -> None:
        deadline = time.monotonic() + self._write_timeout
        with self._cv:
            while not self._closed and len(self._buf) + len(data) > self._cap:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._cv.wait(min(remaining, 0.25))
            if self._closed:
                return
            self._buf += data
            if len(self._buf) > self._cap:
                over = len(self._buf) - self._cap
                del self._buf[:over]
                self._dropped += over
            self._cv.notify_all()

    def read(self, n: int, timeout: float = 5.0) -> bytes:
        deadline = time.monotonic() + timeout
        with self._cv:
            while not self._buf and not self._closed:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return b""
                self._cv.wait(remaining)
            if self._buf:
                out = bytes(self._buf[:n])
                del self._buf[:n]
                self._cv.notify_all()
                return out
            return b""

    def close(self) -> None:
        with self._cv:
            self._closed = True
            self._cv.notify_all()

    @property
    def dropped(self) -> int:
        return self._dropped


class Relay:
    """Owns the upstream connection and a loopback HTTP server."""

    def __init__(self, url: str, station_id: str = "", recorder=None,
                 connect_timeout: float = 14.0, proxy=None):
        self.url = url
        self.station_id = station_id
        self.recorder = recorder
        self.connect_timeout = connect_timeout
        self.proxy = proxy
        self._shim: LocalProxyShim | None = None

        self.reader = None  # StreamReader or FfmpegReader
        self.error: str = ""
        self.content_type: str = ""
        self.icy_name: str = ""
        self.now_playing: str = ""
        self.bitrate_hint: int = 0
        self.final_url: str = ""
        self.started_at = 0.0
        self.client_connected = False
        self.first_byte_at = 0.0

        self._ring = _Ring(RING_BYTES)
        self._stop = threading.Event()
        self._pump: threading.Thread | None = None
        self._server: ThreadingHTTPServer | None = None
        self._server_thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._clients = 0
        self._upstream_ready = threading.Event()
        self._pump_bytes = 0
        self._marked = False
        # ~1.5 s of 320 kbps, the size of a typical server-side prebuffer
        self._mark_threshold = 60 * 1024

    # ------------------------------------------------------------------ #
    #  lifecycle
    # ------------------------------------------------------------------ #
    def start(self) -> str:
        """Connect upstream and start serving. Returns the loopback URL."""
        self.reader = open_stream(
            self.url, timeout=self.connect_timeout, proxy=self.proxy,
            shim_factory=self._ensure_shim,
        )
        self.content_type = self.reader.content_type or guess_audio_type(self.reader.final_url)
        if isinstance(self.content_type, str) and "mpegurl" in self.content_type.lower():
            self.content_type = "audio/mpeg"
        self.icy_name = self.reader.icy_name
        self.bitrate_hint = self.reader.bitrate_hint
        self.final_url = self.reader.final_url
        self.started_at = time.time()

        self._pump = threading.Thread(target=self._pump_loop, name="relay-pump", daemon=True)
        self._pump.start()

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler_class())
        self._server.daemon_threads = True
        self._server_thread = threading.Thread(
            target=self._server.serve_forever, name="relay-http", daemon=True
        )
        self._server_thread.start()
        port = self._server.server_address[1]
        return f"http://127.0.0.1:{port}/stream"

    def _ensure_shim(self) -> str:
        """Start (once) the local CONNECT proxy used by ffmpeg-backed streams."""
        if self._shim is None:
            self._shim = LocalProxyShim(self.proxy, timeout=self.connect_timeout)
            self._shim.start()
        return self._shim.url

    def stop(self) -> None:
        self._stop.set()
        self._ring.close()
        if self._server is not None:
            try:
                self._server.shutdown()
                self._server.server_close()
            except Exception:  # noqa: BLE001
                pass
        if self.reader is not None:
            self.reader.close()
        if self._shim is not None:
            self._shim.stop()
            self._shim = None
        for th in (self._pump, self._server_thread):
            if th is not None and th.is_alive():
                th.join(timeout=1.5)

    # ------------------------------------------------------------------ #
    #  upstream pump
    # ------------------------------------------------------------------ #
    def _pump_loop(self) -> None:
        idle = 0
        try:
            while not self._stop.is_set():
                try:
                    data = self.reader.read(CHUNK)
                except StreamError as exc:
                    self.error = str(exc)
                    break
                if not data:
                    idle += 1
                    if self.reader is not None and self.reader.now_playing:
                        self.now_playing = self.reader.now_playing
                    if idle > 3:
                        self.error = self.error or "stream ended"
                        break
                    time.sleep(0.05)
                    continue
                idle = 0
                self._upstream_ready.set()
                self._ring.write(data)
                self._pump_bytes += len(data)
                if not self._marked and self._pump_bytes > self._mark_threshold:
                    # The opening burst has drained; start measuring real
                    # throughput from here so the reading reflects the stream
                    # rather than the server's initial buffer flush.
                    self._marked = True
                    if self.reader is not None:
                        self.reader.mark()
                if self.recorder is not None:
                    try:
                        self.recorder.write(data)
                    except Exception:  # noqa: BLE001
                        pass
                if self.reader is not None and self.reader.now_playing:
                    self.now_playing = self.reader.now_playing
        finally:
            self._ring.close()

    # ------------------------------------------------------------------ #
    #  stats
    # ------------------------------------------------------------------ #
    @property
    def elapsed(self) -> float:
        return max(0.0, time.time() - self.started_at) if self.started_at else 0.0

    @property
    def measured_kbps(self) -> float:
        """True encoded bitrate of the audio, read from the frames themselves.

        Falls back to the socket-throughput average only when the payload is
        not a recognised format.
        """
        if self.reader is None:
            return 0.0
        if getattr(self.reader, "encoded_kbps", 0):
            return float(self.reader.encoded_kbps)
        return self.reader.measured_kbps

    @property
    def encoded_rate(self) -> int:
        return int(getattr(self.reader, "encoded_rate", 0) or 0)

    @property
    def encoded_channels(self) -> int:
        return int(getattr(self.reader, "encoded_channels", 0) or 0)

    @property
    def bytes_audio(self) -> int:
        return self.reader.bytes_audio if self.reader else 0

    @property
    def buffer_bytes(self) -> int:
        return len(self._ring._buf)  # noqa: SLF001  (diagnostic read)

    @property
    def dropped_bytes(self) -> int:
        return self._ring.dropped

    @property
    def clients(self) -> int:
        return self._clients

    # ------------------------------------------------------------------ #
    #  HTTP handler
    # ------------------------------------------------------------------ #
    def _handler_class(self):
        relay = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"
            server_version = "BroadcastRelay/1.0"

            def log_message(self, *args):  # silence stderr spam
                pass

            def do_HEAD(self):  # noqa: N802
                self.send_response(200)
                self.send_header("Content-Type", relay.content_type or "audio/mpeg")
                self.send_header("Connection", "close")
                self.end_headers()

            def do_GET(self):  # noqa: N802
                if not self.path.startswith("/stream"):
                    self.send_error(404)
                    return
                relay._clients += 1
                relay.client_connected = True
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", relay.content_type or "audio/mpeg")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.flush()
                    relay._upstream_ready.wait(timeout=8.0)
                    while not relay._stop.is_set():
                        chunk = relay._ring.read(CHUNK, timeout=6.0)
                        if not chunk:
                            if relay._stop.is_set():
                                break
                            if relay.error:
                                break
                            continue
                        if relay.first_byte_at == 0.0:
                            relay.first_byte_at = time.time()
                        try:
                            self.wfile.write(chunk)
                            self.wfile.flush()
                        except (BrokenPipeError, ConnectionResetError, OSError):
                            break
                finally:
                    relay._clients = max(0, relay._clients - 1)
                    self.close_connection = True

        return Handler


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
