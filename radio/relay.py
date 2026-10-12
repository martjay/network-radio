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

    def write(self, data: bytes, *, may_drop: bool = True) -> None:
        # While the decoder is attached, dropping bytes punches a hole in AAC
        # (and some MP3) streams and Qt reports ResourceError. Block instead,
        # so backpressure goes to the upstream socket.
        wait = self._write_timeout if may_drop else 120.0
        deadline = time.monotonic() + wait
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
        self._http_gen = 0
        self._upstream_ready = threading.Event()
        self._pump_bytes = 0
        self._marked = False
        # Bytes that have arrived but not yet been handed to a consumer. While
        # no recorder is attached the pump holds the stream back instead of
        # discarding it, so a recorder armed shortly after playback starts
        # still receives the container header (Ogg BOS page, ID3 tag, ...).
        # ffmpeg cannot initialise a container demuxer from mid-stream data,
        # and replaying a stale copy later would break the Ogg timeline.
        self._pending = bytearray()
        self._pending_limit = 256 * 1024
        # First bytes seen on the stream, kept for format identification once
        # the backlog has been handed to a recorder.
        self._head = bytearray()
        self._head_limit = 8 * 1024
        # True once the backlog has dropped its oldest bytes, which means the
        # retained stream no longer begins at the header.
        self._wrapped = False
        self._drained = False
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
        # Unblock the pump (ffmpeg/socket read) before joining threads or
        # shutting the HTTP server, which can otherwise wait on each other.
        if self.reader is not None:
            try:
                self.reader.close()
            except Exception:  # noqa: BLE001
                pass
            self.reader = None
        if self._server is not None:
            def _shut_http() -> None:
                try:
                    self._server.shutdown()
                    self._server.server_close()
                except Exception:  # noqa: BLE001
                    pass
            t = threading.Thread(target=_shut_http, name="relay-http-stop", daemon=True)
            t.start()
            t.join(timeout=1.0)
        if self._shim is not None:
            try:
                self._shim.stop()
            except Exception:  # noqa: BLE001
                pass
            self._shim = None
        for th in (self._pump, self._server_thread):
            if th is not None and th.is_alive():
                th.join(timeout=0.8)

    # ------------------------------------------------------------------ #
    #  upstream pump
    # ------------------------------------------------------------------ #
    def _pump_loop(self) -> None:
        idle_since = 0.0
        try:
            while not self._stop.is_set():
                try:
                    data = self.reader.read(CHUNK)
                except StreamError as exc:
                    self.error = str(exc)
                    break
                if not data:
                    if self.reader is not None and self.reader.now_playing:
                        self.now_playing = self.reader.now_playing
                    # True EOF only. A short empty read used to kill the pump
                    # after ~200 ms, which looks like a random ResourceError.
                    if getattr(self.reader, "_eof", False):
                        self.error = self.error or "stream ended"
                        break
                    if idle_since == 0.0:
                        idle_since = time.monotonic()
                    elif time.monotonic() - idle_since > 45.0:
                        self.error = self.error or "stream ended"
                        break
                    time.sleep(0.05)
                    continue
                idle_since = 0.0
                self._upstream_ready.set()
                self._ring.write(data, may_drop=self._clients <= 0)
                self._pump_bytes += len(data)
                if len(self._head) < self._head_limit:
                    self._head += data

                recorder = self.recorder
                if recorder is None:
                    # Hold the stream back until a recorder attaches, so the
                    # recording does not begin with silence.
                    #
                    # This must stay a *sliding* window: once full, the oldest
                    # bytes are dropped so what remains is always contiguous
                    # with the live data that follows. Simply refusing to
                    # append would leave a gap between the retained prefix and
                    # the resumed stream, and ffmpeg cannot reconcile that -
                    # the decoder reports a corrupt frame part-way through.
                    self._pending += data
                    overflow = len(self._pending) - self._pending_limit
                    if overflow > 0:
                        del self._pending[:overflow]
                        self._wrapped = True
                else:
                    # First write after attaching: prepend the backlog so the
                    # recording covers everything since playback started.
                    if not self._drained:
                        self._drained = True
                        backlog = self.drain_for_recorder(
                            needs_header=getattr(recorder, "needs_stream_header", True)
                        )
                        if backlog:
                            try:
                                recorder.write(backlog)
                            except Exception:  # noqa: BLE001
                                pass
                    try:
                        recorder.write(data)
                    except Exception:  # noqa: BLE001
                        pass

                if not self._marked and self._pump_bytes > self._mark_threshold:
                    # The opening burst has drained; start measuring real
                    # throughput from here so the reading reflects the stream
                    # rather than the server's initial buffer flush.
                    self._marked = True
                    if self.reader is not None:
                        self.reader.mark()
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

    @property
    def head_bytes(self) -> bytes:
        """The true start of the stream, for format identification.

        This is always the first bytes received, never the sliding backlog:
        once the backlog has wrapped, its start is somewhere in the middle of
        the stream and would misidentify the container.
        """
        with self._lock:
            return bytes(self._head)

    def drain_for_recorder(self, needs_header: bool = True) -> bytes:
        """Audio to hand a newly attached recorder.

        Returns the pre-recording backlog. If the backlog has already wrapped
        past the stream start and the caller says the format needs it, the
        retained header is prepended so a container demuxer (Ogg) can
        initialise.

        `needs_header` must be False for raw frame streams (MP3, ADTS AAC):
        those are self-synchronising, and replaying a prefix there duplicates
        audio and desynchronises the frame boundaries.
        """
        with self._lock:
            backlog = bytes(self._pending)
            self._pending = bytearray()
            if not backlog or not self._wrapped or not needs_header:
                return backlog
            prefix = bytes(self._head)
            # Avoid duplicating if the backlog still happens to contain it.
            if backlog.startswith(prefix[:32]):
                return backlog
            return prefix + backlog

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
                with relay._lock:
                    relay._http_gen += 1
                    my_gen = relay._http_gen
                    relay._clients += 1
                relay.client_connected = True
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", relay.content_type or "audio/mpeg")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Pragma", "no-cache")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.flush()
                    relay._upstream_ready.wait(timeout=8.0)
                    while not relay._stop.is_set() and my_gen == relay._http_gen:
                        chunk = relay._ring.read(CHUNK, timeout=6.0)
                        if not chunk:
                            if relay._stop.is_set() or my_gen != relay._http_gen:
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
