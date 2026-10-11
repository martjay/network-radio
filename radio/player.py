"""Playback engine.

`PlayerEngine` runs on the GUI thread and owns the Qt objects, but every
blocking network operation happens on a worker thread so the interface never
freezes. Switching stations is serialised through a single worker so a slow
connect can never race a newer request.
"""
from __future__ import annotations

import re
import threading
import time

import numpy as np
from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtMultimedia import QAudioBufferOutput, QAudioOutput, QMediaPlayer

from . import paths
from .net import probe
from .proxy import ProxyConfig, test_proxy
from .recorder import Recorder
from .relay import Relay

VOLUME_CURVE_EXP = 2.2  # perceptual taper for the volume slider


def slider_to_linear(pos: int) -> float:
    """Map a 0..100 slider position to a 0..1 audio gain."""
    p = max(0, min(100, int(pos))) / 100.0
    return float(p ** VOLUME_CURVE_EXP)


def linear_to_slider(gain: float) -> int:
    g = max(0.0, min(1.0, float(gain)))
    return int(round((g ** (1.0 / VOLUME_CURVE_EXP)) * 100))


class PlayerEngine(QObject):
    # -- state ---------------------------------------------------------------
    state_changed = Signal(str)          # idle | connecting | buffering | playing | error
    station_changed = Signal(dict)       # the station dict being tuned
    metadata_changed = Signal(str)       # live "artist - title"
    icy_name_changed = Signal(str)
    error_occurred = Signal(str)
    level_changed = Signal(float)        # 0..1 RMS
    spectrum_changed = Signal(object)    # numpy float32 array of band magnitudes
    stats_changed = Signal(dict)         # transport counters
    recording_changed = Signal(bool, str)
    history_changed = Signal(dict)
    buffer_health = Signal(float)        # 0..1, share of ring currently filled

    # internal: marshal worker-thread results onto the GUI thread
    _relay_ready = Signal(object, int, bool, str)
    _relay_failed = Signal(int, str)

    BANDS = 40
    FFT = 2048
    F_LOW = 40.0
    F_HIGH = 16000.0
    # Music rolls off with frequency, so a flat band readout always looks like a
    # downhill slide. A gentle tilt plus this floor keeps the whole display
    # alive instead of pinning the bass end at zero.
    TILT = 0.30
    FLOOR_DB = -52.0

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.station: dict = {}
        self.state = "idle"
        self.proxy: ProxyConfig | None = None

        self._audio = QAudioOutput()
        self._audio.setVolume(slider_to_linear(settings.get("volume", 72)))
        self._player = QMediaPlayer()
        self._player.setAudioOutput(self._audio)
        self._abo = QAudioBufferOutput()
        self._player.setAudioBufferOutput(self._abo)
        self._abo.audioBufferReceived.connect(self._on_audio_buffer)

        self._player.mediaStatusChanged.connect(self._on_media_status)
        self._player.errorOccurred.connect(self._on_error)
        # Worker threads must not touch Qt objects or QTimer; hand results back
        # over queued signal connections instead.
        self._relay_ready.connect(self._start_playback)
        self._relay_failed.connect(self._on_connect_failed)

        self._relay: Relay | None = None
        self._relay_lock = threading.Lock()
        self._generation = 0
        self._connect_thread: threading.Thread | None = None
        self._want_playing = False

        self._recorder: Recorder | None = None
        self._recording = False
        self._rec_path = ""

        self._window = np.hanning(self.FFT).astype(np.float32)
        self._prev_bands = np.zeros(self.BANDS, dtype=np.float32)
        self._samples = np.zeros(0, dtype=np.float32)
        self._last_level_emit = 0.0
        self._last_spec_emit = 0.0
        self._last_title = ""
        self._last_icy = ""
        self._peak = 0.0
        self._meta_watch = QTimer(self)
        self._meta_watch.setInterval(1000)
        self._meta_watch.timeout.connect(self._poll_metadata)
        self._stats_timer = QTimer(self)
        self._stats_timer.setInterval(1000)
        self._stats_timer.timeout.connect(self._emit_stats)

    # ------------------------------------------------------------------ #
    #  public API
    # ------------------------------------------------------------------ #
    def tune(self, station: dict) -> None:
        """Begin playing `station` (dict from the catalogue)."""
        if not station:
            return
        self.stop(keep_station=False)
        self._generation += 1
        gen = self._generation
        self.station = dict(station)
        self.station_changed.emit(self.station)
        self.metadata_changed.emit("")
        self.icy_name_changed.emit("")
        self._last_title = ""
        self._last_icy = ""
        self._want_playing = True
        self._set_state("connecting")

        url = station.get("url", "")
        rec_dir = self.settings.get("recordings_dir") or paths.default_recordings_dir()
        want_rec = bool(self.settings.get("auto_record", False))

        def work():
            relay = Relay(url, station_id=station.get("id", ""), proxy=self.proxy)
            try:
                local = relay.start()
            except Exception as exc:  # noqa: BLE001
                relay.stop()
                self._relay_failed.emit(gen, str(exc))
                return
            if gen != self._generation:
                relay.stop()
                return
            with self._relay_lock:
                if gen != self._generation:
                    relay.stop()
                    return
                self._relay = relay
            self._relay_ready.emit(local, gen, want_rec, rec_dir)

        self._connect_thread = threading.Thread(target=work, name="tune", daemon=True)
        self._connect_thread.start()

    def stop(self, keep_station: bool = True) -> None:
        self._want_playing = False
        self._generation += 1
        self._player.stop()
        self._player.setSource(QUrl())
        self._meta_watch.stop()
        self._stats_timer.stop()
        with self._relay_lock:
            relay, self._relay = self._relay, None
        if relay is not None:
            threading.Thread(target=relay.stop, daemon=True).start()
        if self._recording:
            self.stop_recording()
        self._samples = np.zeros(0, dtype=np.float32)
        self._prev_bands[:] = 0.0
        self.level_changed.emit(0.0)
        self.spectrum_changed.emit(np.zeros(self.BANDS, dtype=np.float32))
        self.buffer_health.emit(0.0)
        if not keep_station:
            self.station = {}
        self._set_state("idle")

    def toggle(self) -> None:
        if self.state in ("playing", "buffering", "connecting"):
            self.stop()
        elif self.station:
            self.tune(self.station)

    def retune(self) -> None:
        if self.station:
            self.tune(self.station)

    def set_volume(self, pos: int) -> None:
        self._audio.setVolume(slider_to_linear(pos))

    def set_muted(self, muted: bool) -> None:
        self._audio.setMuted(bool(muted))

    @property
    def is_muted(self) -> bool:
        return self._audio.isMuted()

    # -- recording ------------------------------------------------------- #
    def start_recording(self) -> bool:
        if self._relay is None or not self._want_playing:
            return False
        directory = self.settings.get("recordings_dir") or paths.default_recordings_dir()
        fmt = self.settings.get("record_format", "mp3")
        kbps = int(self.settings.get("record_bitrate", 192))
        name = self._recording_filename()
        try:
            rec = Recorder(
                directory=directory,
                filename=name,
                source_url=self._relay.final_url or self.station.get("url", ""),
                title=self.station.get("name", ""),
                bitrate_kbps=kbps,
                container=fmt,
                # Let the recorder match the container to the real stream
                # format; otherwise AAC/Opus stations cannot be written.
                auto_container=True,
            )
            rec.start()
        except Exception as exc:  # noqa: BLE001
            self.error_occurred.emit(f"无法开始录制：{exc}")
            return False
        self._recorder = rec
        self._rec_path = rec.path
        with self._relay_lock:
            relay = self._relay
            if relay is not None:
                relay.recorder = rec
        # Hand the recorder the container header captured at stream open, so
        # it can identify the format even though it was armed mid-stream.
        # Only used for detection - the header is not written to the file.
        if relay is not None:
            head = relay.head_bytes
            if head:
                try:
                    rec.set_header(head)
                except Exception:  # noqa: BLE001
                    pass
        self._recording = True
        self.recording_changed.emit(True, rec.path)
        return True

    def stop_recording(self) -> str:
        rec, self._recorder = self._recorder, None
        with self._relay_lock:
            if self._relay is not None:
                self._relay.recorder = None
        self._recording = False
        self._rec_path = ""
        if rec is None:
            self.recording_changed.emit(False, "")
            return ""
        path = rec.stop()
        if not path:
            # Nothing usable was written; surface why instead of reporting a
            # saved file that does not exist.
            self.error_occurred.emit(rec.error or "录制失败：没有写入任何音频数据")
            self.recording_changed.emit(False, "")
            return ""
        self.recording_changed.emit(False, path)
        return path

    @property
    def is_recording(self) -> bool:
        return self._recording

    def _recording_filename(self) -> str:
        base = self.station.get("name", "radio")
        safe = re.sub(r'[\\/:*?"<>|]+', "_", base).strip(" ._") or "radio"
        safe = re.sub(r"\s+", " ", safe)[:70]
        stamp = time.strftime("%Y%m%d_%H%M%S")
        ext = self.settings.get("record_format", "mp3")
        return f"{safe}_{stamp}.{ext}"

    # ------------------------------------------------------------------ #
    #  internals
    # ------------------------------------------------------------------ #
    def _set_state(self, state: str) -> None:
        if state != self.state:
            self.state = state
            self.state_changed.emit(state)

    def _fail(self, message: str) -> None:
        self._set_state("error")
        self.error_occurred.emit(message)

    def _on_connect_failed(self, gen: int, message: str) -> None:
        if gen != self._generation:
            return
        self._fail(self._friendly_error(message))

    def _friendly_error(self, message: str) -> str:
        low = (message or "").lower()
        proxied = self.proxy is not None and self.proxy.usable
        if "timed out" in low or "timeout" in low:
            base = "连接超时，该电台可能已下线或网络受限"
            return base if proxied else base + "（该电台可能位于境外，可在设置中启用代理）"
        if "cannot reach proxy" in low or "proxy refused" in low:
            return f"代理不可用：{message}"
        if "403" in low or "401" in low:
            return "服务器拒绝访问（可能需要特定地区）"
        if "404" in low or "410" in low:
            return "电台地址已失效"
        if "playlist" in low:
            return "播放列表中没有可用的流地址"
        if "no audio" in low:
            return "未收到音频数据"
        if "connection refused" in low or "unreachable" in low:
            base = "无法连接到服务器"
            return base if proxied else base + "（若为境外电台，请尝试启用代理）"
        return f"无法连接：{message}" if message else "无法连接该电台"

    def _start_playback(self, local_url: str, gen: int, want_rec: bool, rec_dir: str) -> None:
        if gen != self._generation or not self._want_playing:
            return
        with self._relay_lock:
            relay = self._relay
        if relay is None:
            return
        self.icy_name_changed.emit(relay.icy_name)
        self._set_state("buffering")
        self._player.setSource(QUrl(local_url))
        self._player.play()
        self._meta_watch.start()
        self._stats_timer.start()
        if want_rec:
            QTimer.singleShot(900, self.start_recording)

    def _on_media_status(self, status) -> None:
        name = status.name
        if not self._want_playing:
            return
        if name in ("BufferedMedia", "LoadedMedia"):
            if self.state != "playing":
                self._set_state("playing")
        elif name == "BufferingMedia":
            if self.state == "playing":
                self._set_state("buffering")
            elif self.state == "connecting":
                self._set_state("buffering")
        elif name == "StalledMedia":
            self._set_state("buffering")
        elif name == "EndOfMedia":
            # live streams occasionally report EOS on reconnect; retry once
            if self._want_playing and self._relay is not None:
                self._player.setPosition(0)
                self._player.play()
        elif name == "InvalidMedia":
            if self._want_playing:
                self._set_state("error")
                self.error_occurred.emit("媒体无法解码，请尝试其它电台")

    def _on_error(self, error, message: str) -> None:
        if not self._want_playing:
            return
        if error == QMediaPlayer.Error.NoError:
            return
        self._set_state("error")
        text = {
            "ResourceError": "无法打开音频流（网络或服务器拒绝）",
            "FormatError": "音频格式不受支持",
            "NetworkError": "网络中断",
            "AccessDeniedError": "访问被拒绝",
        }.get(error.name, f"播放错误：{message or error.name}")
        self.error_occurred.emit(text)

    def _poll_metadata(self) -> None:
        with self._relay_lock:
            relay = self._relay
        if relay is None:
            return
        if relay.error and self._want_playing and self.state == "playing":
            self._set_state("error")
            self.error_occurred.emit(relay.error)
            return
        title = relay.now_playing
        if title and title != getattr(self, "_last_title", ""):
            self._last_title = title
            self.metadata_changed.emit(title)
        if relay.icy_name and relay.icy_name != getattr(self, "_last_icy", ""):
            self._last_icy = relay.icy_name
            self.icy_name_changed.emit(relay.icy_name)

    def _emit_stats(self) -> None:
        with self._relay_lock:
            relay = self._relay
        # The container (and therefore the file extension) is only known once
        # the first bytes arrive, so re-announce the path if it changed.
        if self._recording and self._recorder is not None:
            current = self._recorder.path
            if current != self._rec_path:
                self._rec_path = current
                self.recording_changed.emit(True, current)
        if relay is None:
            return
        self.stats_changed.emit({
            "elapsed": relay.elapsed,
            "kbps": relay.measured_kbps,
            "bytes": relay.bytes_audio,
            "dropped": relay.dropped_bytes,
            "buffer": relay.buffer_bytes,
            "clients": relay.clients,
            "error": relay.error,
            "final_url": relay.final_url,
            "content_type": relay.content_type,
            "encoded_rate": relay.encoded_rate,
            "encoded_channels": relay.encoded_channels,
        })
        # Backpressure keeps the relay ring nearly empty while the decoder
        # keeps up, so the gauge is scaled to a small window where ordinary
        # jitter is visible; a full gauge means the decoder is falling behind.
        self.buffer_health.emit(min(1.0, relay.buffer_bytes / (64 * 1024)))

    # -- audio analysis --------------------------------------------------- #
    def _on_audio_buffer(self, buffer) -> None:
        try:
            total = buffer.byteCount() // 4
            if total <= 0:
                return
            fmt = buffer.format()
            channels = max(1, int(fmt.channelCount()))
            # keep only whole frames so the reshape below can never fail
            usable = (total // channels) * channels
            if usable <= 0:
                return
            arr = np.frombuffer(buffer.constData(), dtype=np.float32, count=usable)
        except Exception:  # noqa: BLE001
            return
        if arr.size == 0:
            return

        now = time.monotonic()
        # --- level meter (fast attack, slow release) --------------------
        peak = float(np.max(np.abs(arr)))
        self._peak = max(peak, self._peak * 0.86)
        if now - self._last_level_emit > 0.033:
            self._last_level_emit = now
            self.level_changed.emit(min(1.0, self._peak))

        # --- spectrum ---------------------------------------------------
        if now - self._last_spec_emit < 0.045:
            return
        self._last_spec_emit = now

        self._samples = (
            np.concatenate((self._samples, arr)) if self._samples.size else arr.copy()
        )
        need = self.FFT * channels
        if self._samples.size < need:
            return
        block = self._samples[-need:]
        self._samples = self._samples[-need * 2:]

        if channels > 1:
            frames = block.reshape(-1, channels)
            mono = frames.mean(axis=1)
        else:
            mono = block
        if mono.size < self.FFT:
            return

        windowed = mono[: self.FFT].astype(np.float32) * self._window
        spec = np.abs(np.fft.rfft(windowed))
        spec = spec / (self.FFT / 4.0)
        bands = self._to_bands(spec, fmt.sampleRate() or 44100)

        # Compress to dB and tilt so the display reads like a spectrum
        # analyser rather than a pink-noise slope.
        db = 20.0 * np.log10(bands + 1e-7) + self.TILT * np.arange(self.BANDS, dtype=np.float32)
        norm = np.clip((db - self.FLOOR_DB) / -self.FLOOR_DB, 0.0, 1.0).astype(np.float32)
        # asymmetric smoothing: instant rise, gentle fall
        up = norm > self._prev_bands
        self._prev_bands = np.where(
            up, norm, self._prev_bands * 0.74 + norm * 0.26
        ).astype(np.float32)
        self.spectrum_changed.emit(self._prev_bands.copy())

    def _to_bands(self, spec: np.ndarray, sample_rate: int) -> np.ndarray:
        """Log-spaced band energies, integrating every FFT bin in each band."""
        n = spec.size
        freqs = np.fft.rfftfreq(self.FFT, d=1.0 / max(sample_rate, 8000))
        edges = np.geomspace(self.F_LOW, self.F_HIGH, self.BANDS + 1)
        out = np.zeros(self.BANDS, dtype=np.float32)
        for i in range(self.BANDS):
            a = int(np.searchsorted(freqs, edges[i], side="left"))
            b = int(np.searchsorted(freqs, edges[i + 1], side="right"))
            a = min(max(a, 0), n)
            b = min(max(b, a + 1), n)
            if a >= n:
                out[i] = 0.0
            else:
                out[i] = float(spec[a:b].mean())
        return out

    # ------------------------------------------------------------------ #
    #  proxy
    # ------------------------------------------------------------------ #
    def set_proxy(self, cfg: ProxyConfig | None) -> None:
        """Apply a proxy setting. Takes effect on the next tune."""
        self.proxy = cfg

    def test_proxy(self, cfg: ProxyConfig, timeout: float = 8.0) -> dict:
        return test_proxy(cfg, timeout=timeout)

    def test_station(self, url: str, timeout: float = 10.0) -> dict:
        """Test a station URL using the currently configured proxy."""
        return probe(url, timeout=timeout, proxy=self.proxy)
