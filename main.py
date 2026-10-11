"""Application entry point.

Run with:   python main.py

Options:
    --screenshot PATH   launch, render one frame to PATH, exit
    --selftest          verify a frozen build can load its resources, audio
                        backend and catalogue, then exit with a status code
    --playtest [URL]    tune a station, confirm audio is decoded, print a
                        report and exit (used to validate packaged builds)
"""
from __future__ import annotations

import os
import sys

# Keep Qt from spamming the console and make HiDPI behave on Windows.
os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.*=false;qt.qpa.*=false")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from radio import paths, theme  # noqa: E402
from radio.main_window import MainWindow  # noqa: E402


def run_selftest(app: QApplication) -> int:
    """Confirm a packaged build is intact. Returns a process exit code.

    Everything checked here is something that works from source but can break
    once frozen: bundled data paths, the Qt multimedia plugins, the FFmpeg
    backend DLLs, and numpy.
    """
    from PySide6.QtMultimedia import QMediaDevices

    failures: list[str] = []

    def check(name: str, fn) -> None:
        try:
            detail = fn()
            print(f"  PASS  {name:<34} {detail}")
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL  {name:<34} {type(exc).__name__}: {exc}")
            failures.append(name)

    print(f"BROADCAST self-test  (frozen={paths.is_frozen()})")
    print(f"  python   {sys.version.split()[0]}")
    print(f"  resource {paths._resource_root()}")

    check("numpy import", lambda: __import__("numpy").__version__)

    def check_catalogue():
        path = paths.bundled("stations.json")
        if not os.path.isfile(path):
            raise FileNotFoundError(f"missing: {path}")
        from radio.library import Library
        lib = Library()
        if len(lib.stations) < 100:
            raise ValueError(f"only {len(lib.stations)} stations parsed")
        return f"{len(lib.stations)} stations, {len(lib.genre_options())} genres"

    check("station catalogue", check_catalogue)

    def check_audio_backend():
        from PySide6.QtMultimedia import QAudioBufferOutput, QMediaPlayer
        player = QMediaPlayer()
        player.setAudioBufferOutput(QAudioBufferOutput())
        return "QMediaPlayer + QAudioBufferOutput ready"

    check("audio backend", check_audio_backend)

    def check_output_device():
        dev = QMediaDevices.defaultAudioOutput()
        if dev is None or dev.isNull():
            raise RuntimeError("no default audio output device")
        return dev.description()[:44]

    check("audio output device", check_output_device)

    def check_proxy():
        from radio.proxy import system_proxy
        cfg = system_proxy()
        return cfg.describe()

    check("proxy module", check_proxy)

    def check_recorder():
        from radio.recorder import ffmpeg_available
        return "ffmpeg found" if ffmpeg_available() else "ffmpeg not found (recording disabled)"

    check("recorder module", check_recorder)

    def check_userdata():
        d = paths.app_dir()
        probe = os.path.join(d, ".selftest")
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("ok")
        os.remove(probe)
        return d

    check("writable data dir", check_userdata)

    def check_theme():
        from radio import icons
        return f"{theme.ui_family()} / {len(icons.DRAW)} icons"

    check("theme + icons", check_theme)

    print()
    if failures:
        print(f"SELF-TEST FAILED: {len(failures)} check(s): {', '.join(failures)}")
        return 1
    print("SELF-TEST PASSED")
    return 0


def run_playtest(app: QApplication) -> int:
    """Tune a real station and confirm the packaged decoder produces audio.

    This is the check that actually matters for a frozen build: it exercises
    the bundled FFmpeg backend end to end (network -> relay -> decoder -> PCM
    buffers -> FFT).
    """
    from PySide6.QtCore import QTimer

    idx = sys.argv.index("--playtest")
    url = sys.argv[idx + 1] if len(sys.argv) > idx + 1 and not sys.argv[idx + 1].startswith("-") else ""
    seconds = 14

    window = MainWindow()
    window.show()

    state = {"peak": 0.0, "level": 0.0, "error": "", "meta": "", "tuned": ""}

    def on_spectrum(values):
        try:
            state["peak"] = max(state["peak"], float(max(values)))
        except (TypeError, ValueError):
            pass

    window.engine.spectrum_changed.connect(on_spectrum)
    window.engine.level_changed.connect(lambda v: state.__setitem__("level", max(state["level"], v)))
    window.engine.error_occurred.connect(lambda m: state.__setitem__("error", m))
    window.engine.metadata_changed.connect(lambda m: state.__setitem__("meta", m))

    def choose():
        target = None
        if url:
            # Accept a catalogue entry or any bare stream URL.
            target = window.library.find(url)
            if target is None and url.lower().startswith(("http://", "https://")):
                target = {"id": "playtest", "name": url, "url": url, "codec": "",
                          "bitrate": 0, "country": "", "genre": "varied", "zh": False}
        if target is None:
            for r in window.model.rows:
                if (r.get("codec") or "").upper() == "MP3" and ".m3u8" not in r.get("url", "").lower():
                    target = r
                    break
        if target is None:
            state["error"] = "no station available to test"
            return
        state["tuned"] = target.get("name", "")
        print(f"  tuning: {state['tuned']}")
        window.engine.tune(target)

    def finish():
        ok = state["peak"] > 0.20 and not state["error"]
        print(f"  station   {state['tuned']}")
        print(f"  state     {window.engine.state}")
        print(f"  spectrum  peak={state['peak']:.3f}  level={state['level']:.3f}")
        print(f"  metadata  {state['meta'] or '(none)'}")
        if state["error"]:
            print(f"  error     {state['error']}")
        print()
        print("PLAY-TEST PASSED" if ok else "PLAY-TEST FAILED")
        app.exit(0 if ok else 1)

    QTimer.singleShot(600, choose)
    QTimer.singleShot(seconds * 1000, finish)
    return app.exec()


def main() -> int:
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName(paths.APP_NAME)
    app.setApplicationDisplayName(paths.APP_TITLE)
    app.setApplicationVersion(paths.APP_VERSION)
    app.setOrganizationName(paths.APP_NAME)
    app.setStyle("Fusion")

    # The theme module resolves font families lazily; force it now that the
    # platform font database exists.
    base = theme.font(12, 400)
    app.setFont(base)
    app.setStyleSheet(theme.stylesheet())

    if "--selftest" in sys.argv:
        return run_selftest(app)

    if "--playtest" in sys.argv:
        return run_playtest(app)

    window = MainWindow()
    window.show()

    if "--screenshot" in sys.argv:
        from PySide6.QtCore import QTimer

        idx = sys.argv.index("--screenshot")
        out = sys.argv[idx + 1] if len(sys.argv) > idx + 1 else "screenshot.png"

        def shoot():
            window.grab().save(out)
            print(f"saved {out}  ({window.width()}x{window.height()})")
            app.quit()

        QTimer.singleShot(2500, shoot)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
