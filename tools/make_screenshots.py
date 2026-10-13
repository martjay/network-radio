"""Capture the README screenshots from the live UI."""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from radio import appicon, theme  # noqa: E402
from radio.dialogs import PreferencesDialog, StationDialog  # noqa: E402
from radio.main_window import MainWindow  # noqa: E402

OUT = os.path.join(ROOT, "docs")
os.makedirs(OUT, exist_ok=True)


def save(widget, name: str) -> None:
    path = os.path.join(OUT, name)
    ok = widget.grab().save(path)
    print(f"{'saved' if ok else 'FAILED'} {name}  {widget.width()}x{widget.height()}")


def pick(rows, *needles: str):
    lowered = [n.lower() for n in needles]
    for row in rows:
        blob = " ".join(
            str(row.get(k, "")).lower()
            for k in ("name", "url", "genre", "country", "tags")
        )
        if all(n in blob for n in lowered):
            if ".m3u8" not in (row.get("url") or "").lower():
                return row
    return None


app = QApplication(sys.argv)
app.setStyle("Fusion")
app.setStyleSheet(theme.stylesheet())
appicon.set_taskbar_identity()
app.setWindowIcon(appicon.app_icon())

win = MainWindow()
win.resize(1560, 940)
win.show()
app.processEvents()


def tune(row) -> None:
    if row is None:
        return
    win.table.select_url(row["url"])
    win.engine.tune(row)
    print(f"tuning {row.get('name')!r}")


def wait_play(then, tries: int = 0) -> None:
    spec = getattr(win.engine, "_prev_bands", None)
    energy = float(spec.max()) if spec is not None and getattr(spec, "size", 0) else 0.0
    state = getattr(win.engine, "state", "")
    if state == "playing" and energy > 0.04:
        then()
        return
    if tries >= 50:
        print(f"giving up wait_play state={state!r} energy={energy:.3f}")
        then()
        return
    QTimer.singleShot(400, lambda: wait_play(then, tries + 1))


def step_playing() -> None:
    rows = win.model.rows
    target = pick(rows, "somafm", "reggae") or pick(rows, "somafm")
    if target is None:
        for row in rows:
            if int(row.get("bitrate") or 0) >= 128 and (row.get("codec") or "").upper() == "MP3":
                target = row
                break
    tune(target or (rows[0] if rows else None))
    wait_play(shot_playing)


def shot_playing() -> None:
    save(win, "screenshot-playing.png")
    win._on_nav("zh")
    rows = win.model.rows
    zh = next((r for r in rows if r.get("zh") and ".m3u8" not in (r.get("url") or "").lower()), None)
    if zh:
        tune(zh)
        wait_play(shot_chinese)
    else:
        QTimer.singleShot(700, shot_chinese)


def shot_chinese() -> None:
    save(win, "screenshot-chinese.png")
    win._on_nav("jazz")
    rows = win.model.rows
    jazz = None
    for row in rows:
        url = (row.get("url") or "").lower()
        name = (row.get("name") or "").lower()
        if ".m3u8" in url or "smoothjazz.com.pl" in url or "smoothjazz.com.pl" in name:
            continue
        if (row.get("codec") or "").upper() == "MP3":
            jazz = row
            break
    if jazz is None and rows:
        jazz = rows[0]
    if jazz:
        tune(jazz)
        wait_play(shot_jazz)
    else:
        QTimer.singleShot(700, shot_jazz)


def shot_jazz() -> None:
    save(win, "screenshot-jazz.png")
    shot_dialogs()


def shot_dialogs() -> None:
    prefs = PreferencesDialog(win, win.library, win.engine)
    prefs.show()
    app.processEvents()

    prefs.nav.setCurrentRow(0)
    app.processEvents()
    save(prefs, "screenshot-preferences.png")

    prefs.nav.setCurrentRow(1)
    app.processEvents()
    save(prefs, "screenshot-proxy.png")

    prefs.nav.setCurrentRow(4)
    app.processEvents()
    save(prefs, "screenshot-about.png")
    prefs.hide()
    prefs.close()

    dlg = StationDialog(win, None, win.engine)
    dlg.name_edit.setText("示例电台")
    dlg.url_edit.setText("https://ice1.somafm.com/groovesalad-128-mp3")
    dlg.show()
    app.processEvents()
    save(dlg, "screenshot-add-station.png")
    dlg.hide()
    dlg.close()
    shot_tray()


def shot_tray() -> None:
    if win.tray and win.tray.available:
        name = win._mini_title.fullText() if hasattr(win, "_mini_title") else "BROADCAST"
        track = win._mini_track.fullText() if hasattr(win, "_mini_track") else ""
        win.tray.set_playing(name, track, playing=True, state="playing")
        win.tray.set_state(True, False, False)
        menu = win.tray.menu
        menu.popup(win.geometry().center())
        app.processEvents()
        QTimer.singleShot(400, lambda: grab_tray(menu))
    else:
        finish()


def grab_tray(menu) -> None:
    save(menu, "screenshot-tray-menu.png")
    menu.hide()
    finish()


def finish() -> None:
    appicon.save_preview(os.path.join(OUT, "icon"))
    print("saved icon previews")
    win._really_quit = True
    try:
        win.engine.stop()
    except Exception:
        pass
    win.close()
    app.quit()


QTimer.singleShot(700, step_playing)
raise SystemExit(app.exec())
