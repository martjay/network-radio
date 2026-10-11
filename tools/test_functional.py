"""End-to-end functional test of the running application.

Exercises: catalogue load, filtering, station switching, playback, ICY
metadata, spectrum analysis, recording (start/stop/file validity), favourites,
search, and settings persistence.
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, r"E:\KU\AI\deepseek-harness\network-radio")
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from radio import theme  # noqa: E402
from radio.main_window import MainWindow  # noqa: E402

OUTDIR = r"E:\KU\AI\deepseek-harness\network-radio\tools\_testout"
os.makedirs(OUTDIR, exist_ok=True)

app = QApplication(sys.argv)
app.setStyle("Fusion")
app.setStyleSheet(theme.stylesheet())

win = MainWindow()
win.resize(1560, 940)
win.show()

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name:<46} {detail}")


log: list[str] = []
t0 = time.time()


def note(m: str) -> None:
    log.append(f"[{time.time()-t0:5.1f}s] {m}")


win.engine.state_changed.connect(lambda s: note(f"state={s}"))
win.engine.metadata_changed.connect(lambda m: note(f"meta={m!r}"))
win.engine.error_occurred.connect(lambda e: note(f"ERR={e}"))

STATION = ""


def phase1():
    """Catalogue + UI sanity."""
    print("\n--- catalogue and UI ---")
    lib = win.library
    check("stations loaded", len(lib.stations) > 700, f"{len(lib.stations)} stations")
    check("genres present", len(lib.genre_options()) >= 12, f"{len(lib.genre_options())} genres")
    check("countries present", len(lib.country_options()) >= 40, f"{len(lib.country_options())} countries")
    zh = [s for s in lib.all_stations() if s.get("zh")]
    check("chinese stations", len(zh) >= 50, f"{len(zh)} stations")
    check("no emoji in names", not any(
        any(ord(c) > 0x1F000 for c in s.get("name", "")) for s in lib.stations),
        "checked 820 names")

    # The app deliberately restores the section from the previous session, so
    # start from a known state rather than assuming the default.
    win._on_nav("all")
    app.processEvents()
    check("list populated", win.model.rowCount() > 100, f"{win.model.rowCount()} rows")

    # filtering
    win.search.setText("jazz")
    app.processEvents()
    n_jazz = win.model.rowCount()
    check("search filters list", 0 < n_jazz < 200, f"'jazz' -> {n_jazz} rows")
    win.search.clear()
    app.processEvents()

    win._set_nav("zh")
    win._on_nav("zh")
    app.processEvents()
    check("chinese section", win.model.rowCount() >= 50, f"{win.model.rowCount()} rows")
    win._on_nav("all")
    app.processEvents()
    check("back to all", win.model.rowCount() > 700, f"{win.model.rowCount()} rows")

    # pick a station with ICY metadata for the playback test
    global STATION
    for r in win.model.rows:
        u = r.get("url", "").lower()
        if "somafm" in u and ".m3u8" not in u:
            STATION = r["url"]
            break
    if not STATION:
        for r in win.model.rows:
            if (r.get("codec") or "").upper() == "MP3" and ".m3u8" not in r.get("url", "").lower():
                STATION = r["url"]
                break
    note(f"target station url={STATION}")
    QTimer.singleShot(200, phase2)


def phase2():
    """Playback + analysis."""
    print("\n--- playback ---")
    station = win.library.find(STATION)
    check("station resolved", station is not None, station.get("name", "") if station else "")
    if station:
        win.table.select_url(STATION)
        win.engine.tune(station)
    QTimer.singleShot(11000, phase3)


def phase3():
    print("\n--- playback results ---")
    st = win.engine.state
    check("state is playing", st == "playing", f"state={st}")
    check("relay connected", win.engine._relay is not None, "")

    spec = win.engine._prev_bands
    peak = float(spec.max())
    mean = float(spec.mean())
    nonzero = int((spec > 0.05).sum())
    check("spectrum has energy", peak > 0.35, f"peak={peak:.3f} mean={mean:.3f}")
    check("spectrum bands populated", nonzero >= 20, f"{nonzero}/40 bands above 0.05")
    low = float(spec[:12].mean())
    high = float(spec[-12:].mean())
    check("low end not dead", low > 0.20, f"low band mean={low:.3f}")
    check("low > high (natural tilt)", low > high, f"low={low:.3f} high={high:.3f}")

    lvl = win._level._hold
    check("level meter active", lvl > 0.05, f"hold={lvl:.3f}")
    check("icy metadata received", bool(win._mini_track.fullText()),
          repr(win._mini_track.fullText()[:48]))
    kbps = win._q_measured._value.fullText()
    check("bitrate reported", kbps not in ("--", ""), kbps)
    check("sample rate reported", win._q_sample._value.fullText() not in ("--", ""),
          win._q_sample._value.fullText())
    check("play history recorded", len(win.library.history) >= 1,
          f"{len(win.library.history)} entries")
    check("play count incremented", win.library.play_count(STATION) >= 1,
          f"count={win.library.play_count(STATION)}")
    QTimer.singleShot(200, phase4)


def phase4():
    """Recording."""
    print("\n--- recording ---")
    win.library.set("recordings_dir", OUTDIR, save=False)
    win.library.set("record_format", "mp3", save=False)
    started = win.engine.start_recording()
    check("recording started", started, "")
    QTimer.singleShot(7000, phase5)


def phase5():
    path = win.engine.stop_recording()
    check("recording stopped", bool(path), path or "no file")
    if path and os.path.exists(path):
        size = os.path.getsize(path)
        check("file written", size > 20000, f"{size/1024:.0f} KB")
        from radio.recorder import ffmpeg_path
        import subprocess
        probe = subprocess.run(
            [ffmpeg_path(), "-hide_banner", "-v", "error", "-i", path,
             "-f", "null", "-"],
            capture_output=True, timeout=60,
        )
        check("file decodes cleanly", probe.returncode == 0 and not probe.stderr.strip(),
              probe.stderr.decode("utf-8", "replace").strip()[:70] or "no errors")
    else:
        check("file written", False, "missing")
    QTimer.singleShot(200, phase6)


def phase6():
    """Favourites + persistence."""
    print("\n--- favourites and persistence ---")
    lib = win.library
    before = len(lib.favorites)
    win._on_favorite_toggled(STATION)
    check("favourite added", len(lib.favorites) == before + 1, f"{len(lib.favorites)}")
    check("favourite list resolves", any(s["url"] == STATION for s in lib.favorite_stations()), "")
    win._on_favorite_toggled(STATION)
    check("favourite removed", len(lib.favorites) == before, f"{len(lib.favorites)}")

    lib.set("volume", 55)
    lib.set("record_format", "ogg")
    lib.save()
    from radio.library import Library
    fresh = Library()
    check("settings persisted", fresh.get("volume") == 55 and fresh.get("record_format") == "ogg",
          f"volume={fresh.get('volume')} fmt={fresh.get('record_format')}")

    m3u = os.path.join(OUTDIR, "fav.m3u")
    lib.toggle_favorite(STATION)
    n = lib.export_favorites(m3u)
    check("m3u exported", n >= 1 and os.path.exists(m3u), f"{n} entries")
    lib.toggle_favorite(STATION)

    win.engine.stop()
    win.grab().save(os.path.join(OUTDIR, "final.png"))
    note("saved final screenshot")

    print("\n--- engine log ---")
    for line in log[-24:]:
        print("   ", line)

    print("\n=== SUMMARY ===")
    passed = sum(1 for _, ok, _ in results if ok)
    failed = [n for n, ok, _ in results if not ok]
    print(f"{passed}/{len(results)} checks passed")
    if failed:
        print("FAILED: " + ", ".join(failed))
    app.quit()


QTimer.singleShot(400, phase1)
app.exec()
sys.exit(1 if any(not ok for _, ok, _ in results) else 0)
