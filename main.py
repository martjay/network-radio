"""Application entry point.

Run with:   python main.py

Options:
    --screenshot PATH   launch, render one frame to PATH, exit
    --selftest          verify a frozen build can load its resources, audio
                        backend and catalogue, then exit with a status code
    --playtest [URL]    tune a station, confirm audio is decoded, print a
                        report and exit (used to validate packaged builds)
    --rectest [URL]     record a few seconds and verify the file is playable
                        (used to validate packaged builds)
"""
from __future__ import annotations

import os
import sys

# Keep Qt from spamming the console and make HiDPI behave on Windows.
os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.*=false;qt.qpa.*=false")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from radio import appicon, paths, theme  # noqa: E402
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

    def check_app_icon():
        from radio import appicon
        ic = appicon.app_icon()
        if ic.isNull():
            raise RuntimeError("application icon is null")
        sizes = len(ic.availableSizes())
        if sizes < 8:
            raise ValueError(f"only {sizes} icon sizes")
        ico = paths.bundled("broadcast.ico")
        have = "ico bundled" if os.path.isfile(ico) else "ico missing"
        return f"{sizes} sizes, {have}"

    check("application icon", check_app_icon)

    def check_tray():
        from PySide6.QtWidgets import QSystemTrayIcon
        from radio import appicon
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return "no system tray on this desktop (tray disabled)"
        icon = appicon.tray_icon()
        if icon.isNull():
            raise RuntimeError("tray icon is null")
        return f"tray available, {len(icon.availableSizes())} sizes"

    check("system tray", check_tray)

    def check_dpi():
        from PySide6.QtGui import QGuiApplication
        screen = QGuiApplication.primaryScreen()
        return (f"{screen.logicalDotsPerInch():.0f} dpi, "
                f"scale {screen.devicePixelRatio():.2f}x")

    check("high-DPI scaling", check_dpi)

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


def _configure_dpi() -> None:
    """Set up high-DPI handling before the QApplication exists.

    Qt 6 always scales for high-DPI displays, so the deprecated
    AA_EnableHighDpiScaling / AA_UseHighDpiPixmaps switches are not set (they
    only produce warnings). What still matters is the rounding policy:
    `PassThrough` honours fractional scale factors (125%, 150%) exactly, so
    the hand-painted interface is rendered at the true scale rather than being
    resampled to a neighbouring integer factor.
    """
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )


def run_rectest(app: QApplication) -> int:
    """Record a few seconds and confirm the result is a playable file.

    This is the packaged-build check for recording: it exercises the bundled
    ffmpeg, the container selection and the frame handling end to end.
    """
    import subprocess
    import tempfile

    from PySide6.QtCore import QTimer

    from radio.recorder import ffmpeg_path

    idx = sys.argv.index("--rectest")
    url = sys.argv[idx + 1] if len(sys.argv) > idx + 1 and not sys.argv[idx + 1].startswith("-") else ""
    out_dir = tempfile.mkdtemp(prefix="broadcast_rectest_")
    state: dict = {"path": "", "error": "", "source": "", "container": ""}

    window = MainWindow()
    window.show()
    window.library.set("recordings_dir", out_dir, save=False)
    window.library.set("record_format", "mp3", save=False)   # deliberately MP3

    def choose():
        target = None
        if url:
            target = window.library.find(url)
            if target is None and url.lower().startswith(("http://", "https://")):
                target = {"id": "rt", "name": url, "url": url, "codec": "",
                          "bitrate": 0, "country": "", "genre": "varied", "zh": False}
        if target is None:
            for r in window.model.rows:
                if (r.get("codec") or "").upper() == "MP3":
                    target = r
                    break
        if target is None:
            state["error"] = "no station available"
            return
        print(f"  station: {target.get('name')}")
        window.engine.tune(target)

    def start():
        if not window.engine.start_recording():
            state["error"] = "start_recording returned False"
            return
        rec = window.engine._recorder
        if rec is not None:
            state["source"] = rec.source
            state["container"] = rec.container
        print(f"  source format: {state['source']}  container: {state['container']}")

    def finish():
        state["path"] = window.engine.stop_recording()
        path = state["path"]
        print(f"  file: {os.path.basename(path) if path else '(none)'}")
        ok = False
        if path and os.path.exists(path):
            size = os.path.getsize(path)
            print(f"  size: {size} bytes")
            if size > 8000:
                probe = subprocess.run(
                    [ffmpeg_path(), "-hide_banner", "-v", "error", "-i", path,
                     "-f", "null", "-"],
                    capture_output=True, timeout=120,
                )
                err = probe.stderr.decode("utf-8", "replace").strip()
                print(f"  decode: rc={probe.returncode} {err[:120] or '(clean)'}")
                ok = probe.returncode == 0 and not err
            else:
                print("  file too small to be valid audio")
        else:
            print(f"  error: {state['error'] or 'no file produced'}")
        print()
        print("REC-TEST PASSED" if ok else "REC-TEST FAILED")
        window.engine.stop()
        app.exit(0 if ok else 1)

    QTimer.singleShot(600, choose)
    QTimer.singleShot(7000, start)
    QTimer.singleShot(15000, finish)
    return app.exec()


def _install_crash_logging() -> None:
    """Route Python and native crash traces to a log file.

    A windowed frozen build has no console, so without this the only symptom
    of a crash is the process silently disappearing. `faulthandler` also
    captures native faults (access violations inside the Qt/FFmpeg DLLs),
    which are otherwise impossible to diagnose after the fact.

    Logs live next to the user data: `<app dir>/logs/crash.log`, with the
    previous run preserved as `crash-prev.log`.
    """
    import faulthandler
    import threading
    import traceback

    try:
        log_dir = os.path.join(paths.app_dir(), "logs")
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, "crash.log")
        prev = os.path.join(log_dir, "crash-prev.log")
        try:
            if os.path.isfile(log_path) and os.path.getsize(log_path) > 0:
                os.replace(log_path, prev)
        except OSError:
            pass
        fh = open(log_path, "a", encoding="utf-8", errors="replace", buffering=1)
    except OSError:
        # No writable log location; crash logging is best-effort by design.
        return

    import datetime
    fh.write(f"\n===== BROADCAST start {datetime.datetime.now():%Y-%m-%d %H:%M:%S} "
             f"(frozen={paths.is_frozen()}) =====\n")
    faulthandler.enable(file=fh)

    def _excepthook(exc_type, exc, tb):
        try:
            fh.write("--- unhandled exception ---\n")
            fh.writelines(traceback.format_exception(exc_type, exc, tb))
            fh.flush()
        except Exception:  # noqa: BLE001
            pass

    def _threading_hook(args):
        try:
            fh.write(f"--- unhandled exception in thread {args.thread.name} ---\n")
            fh.writelines(
                traceback.format_exception(args.exc_type, args.exc_value,
                                           args.exc_traceback))
            fh.flush()
        except Exception:  # noqa: BLE001
            pass

    sys.excepthook = _excepthook
    threading.excepthook = _threading_hook

    # In a windowed frozen build sys.stdout/sys.stderr are None, and any
    # library calling print() would raise inside whatever slot triggered it.
    # Give them somewhere harmless to go.
    if sys.stdout is None:
        sys.stdout = fh
    if sys.stderr is None:
        sys.stderr = fh


def main() -> int:
    _install_crash_logging()
    _configure_dpi()
    app = QApplication(sys.argv)
    app.setApplicationName(paths.APP_NAME)
    app.setApplicationDisplayName(paths.APP_TITLE)
    app.setApplicationVersion(paths.APP_VERSION)
    app.setOrganizationName(paths.APP_NAME)
    app.setStyle("Fusion")

    # Own taskbar identity and window icon, so the shell shows the product's
    # icon rather than the generic interpreter one (notably when frozen).
    appicon.set_taskbar_identity()
    app.setWindowIcon(appicon.app_icon())

    # The theme module resolves font families lazily; force it now that the
    # platform font database exists.
    base = theme.font(12, 400)
    app.setFont(base)
    app.setStyleSheet(theme.stylesheet())

    if "--selftest" in sys.argv:
        return run_selftest(app)

    if "--playtest" in sys.argv:
        return run_playtest(app)

    if "--rectest" in sys.argv:
        return run_rectest(app)

    # Closing the window hides to the tray by default. A second launch must
    # raise that instance instead of stacking another MainWindow.
    _cli = {"--selftest", "--playtest", "--rectest", "--screenshot"}
    if not _cli.intersection(sys.argv):
        from PySide6.QtNetwork import QLocalServer, QLocalSocket

        sock_name = f"{paths.APP_NAME}-single-instance"
        probe = QLocalSocket()
        probe.connectToServer(sock_name)
        if probe.waitForConnected(200):
            probe.write(b"raise\n")
            probe.waitForBytesWritten(300)
            probe.disconnectFromServer()
            return 0

    window = MainWindow()
    window.show()

    if not _cli.intersection(sys.argv):
        from PySide6.QtNetwork import QLocalServer

        sock_name = f"{paths.APP_NAME}-single-instance"
        server = QLocalServer(window)
        QLocalServer.removeServer(sock_name)
        server.listen(sock_name)

        def _raise_existing():
            conn = server.nextPendingConnection()
            if conn is not None:
                conn.readAll()
                conn.close()
            window.reveal()

        server.newConnection.connect(_raise_existing)
    # Belt and braces: if the process quits without a closeEvent (session
    # logout, QApplication.quit() from elsewhere), still stop playback and
    # recording synchronously instead of leaving daemon threads behind.
    app.aboutToQuit.connect(window.engine.shutdown)

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
