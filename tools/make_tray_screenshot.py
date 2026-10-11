"""Capture the tray menu and icon previews for the documentation."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, r"E:\KU\AI\deepseek-harness\network-radio")
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from radio import appicon, theme  # noqa: E402
from radio.main_window import MainWindow  # noqa: E402

OUT = r"E:\KU\AI\deepseek-harness\network-radio\docs"
os.makedirs(OUT, exist_ok=True)

app = QApplication(sys.argv)
app.setStyle("Fusion")
app.setStyleSheet(theme.stylesheet())
appicon.set_taskbar_identity()
app.setWindowIcon(appicon.app_icon())

win = MainWindow()
win.resize(1560, 940)
win.show()


def step():
    # tune something so the tray tooltip and menu reflect real state
    for r in win.model.rows:
        if "somafm" in r.get("url", "").lower() and "reggae" in r.get("url", "").lower():
            win.table.select_url(r["url"])
            win.engine.tune(r)
            break
    QTimer.singleShot(11000, step2)


def step2():
    win.grab().save(os.path.join(OUT, "screenshot-playing.png"))
    print("saved screenshot-playing.png")

    # render the tray menu itself
    if win.tray and win.tray.available:
        win.tray.set_state(True, False, False)
        menu = win.tray.menu
        menu.show()
        app.processEvents()
        QTimer.singleShot(600, lambda: shot_menu(menu))
    else:
        finish()


def shot_menu(menu):
    menu.grab().save(os.path.join(OUT, "screenshot-tray-menu.png"))
    print("saved screenshot-tray-menu.png")
    menu.hide()
    finish()


def finish():
    # icon preview strip
    appicon.save_preview(os.path.join(OUT, "icon"))
    print("saved icon previews")
    win._really_quit = True
    win.engine.stop()
    win.close()
    app.quit()


QTimer.singleShot(700, step)
app.exec()
