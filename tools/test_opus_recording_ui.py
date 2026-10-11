"""End-to-end: record the exact station the user reported, through the real UI,
and confirm the file the app reports is actually playable."""
from __future__ import annotations

import os
import subprocess
import sys
import time

sys.path.insert(0, r"E:\KU\AI\deepseek-harness\network-radio")
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from radio import paths, theme  # noqa: E402
from radio.main_window import MainWindow  # noqa: E402
from radio.recorder import CREATE_NO_WINDOW, ffmpeg_path  # noqa: E402

OUT = os.path.join(paths.app_dir(), "recordings")
os.makedirs(OUT, exist_ok=True)

app = QApplication(sys.argv)
app.setStyle("Fusion")
app.setStyleSheet(theme.stylesheet())
win = MainWindow()
win.resize(1560, 940)
win.show()

log: list[str] = []
t0 = time.time()
results: list[tuple[str, bool]] = []


def note(m):
    log.append(f"[{time.time()-t0:5.1f}s] {m}")


def check(name, ok, detail=""):
    results.append((name, ok))
    print(f"  {'PASS' if ok else 'FAIL'}  {name:<46} {detail}")


win.engine.state_changed.connect(lambda s: note(f"state={s}"))
win.engine.error_occurred.connect(lambda e: note(f"ERROR={e}"))
win.engine.recording_changed.connect(lambda a, p: note(f"recording={a} path={os.path.basename(p) if p else ''}"))

TARGET = "https://listen.moe/kpop/stream"


def phase1():
    print("\n--- the reported station (Ogg/Opus) ---")
    win.library.set("recordings_dir", OUT, save=False)
    win.library.set("record_format", "mp3", save=False)   # the setting that used to break it
    station = {"id": "t", "name": "Listen.moe Kpop", "url": TARGET, "codec": "OPUS",
               "bitrate": 192, "country": "日本", "genre": "world", "zh": False}
    win.engine.tune(station)
    QTimer.singleShot(9000, phase2)


def phase2():
    print(f"  state before record: {win.engine.state}")
    started = win.engine.start_recording()
    check("recording started", started, "")
    QTimer.singleShot(9000, phase3)


def phase3():
    path = win.engine.stop_recording()
    check("stop returned a path", bool(path), path or "(none)")
    if not path:
        finish()
        return
    exists = os.path.exists(path)
    size = os.path.getsize(path) if exists else 0
    ext = os.path.splitext(path)[1]
    check("reported file exists", exists, f"{size/1024:.0f} KB")
    check("non-zero size", size > 20000, f"{size} bytes")
    check("extension matches source format", ext == ".ogg",
          f"got {ext} (Opus must not be written as .mp3)")
    if exists and size:
        p = subprocess.run([ffmpeg_path(), "-hide_banner", "-v", "error", "-i", path,
                            "-f", "null", "-"], capture_output=True, timeout=90,
                           creationflags=CREATE_NO_WINDOW)
        err = p.stderr.decode("utf-8", "replace").strip()
        check("file decodes cleanly", p.returncode == 0 and not err, err[:80] or "no errors")
    finish()


def finish():
    win.engine.stop()
    print("\n--- log ---")
    for line in log[-14:]:
        print("   ", line)
    passed = sum(1 for _, ok in results if ok)
    failed = [n for n, ok in results if not ok]
    print(f"\n{passed}/{len(results)} checks passed")
    if failed:
        print("FAILED: " + ", ".join(failed))
    app.quit()
    sys.exit(1 if failed else 0)


QTimer.singleShot(700, phase1)
app.exec()
