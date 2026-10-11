"""Capture the final presentation screenshots."""
import os
import sys

sys.path.insert(0, r"E:\KU\AI\deepseek-harness\network-radio")
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from radio import theme  # noqa: E402
from radio.main_window import MainWindow  # noqa: E402

OUT = r"E:\KU\AI\deepseek-harness\network-radio\docs"
os.makedirs(OUT, exist_ok=True)

app = QApplication(sys.argv)
app.setStyle("Fusion")
app.setStyleSheet(theme.stylesheet())
win = MainWindow()
win.resize(1560, 940)
win.show()


def step1():
    # a high-bitrate station with live ICY metadata
    for r in win.model.rows:
        u = r.get("url", "").lower()
        if "somafm" in u and "reggae" in u:
            win.table.select_url(r["url"])
            win.engine.tune(r)
            break
    QTimer.singleShot(12000, step2)


def step2():
    win.grab().save(os.path.join(OUT, "screenshot-playing.png"))
    print("saved screenshot-playing.png")
    win.engine.stop()
    QTimer.singleShot(1200, step3)


def step3():
    win._on_nav("zh")
    QTimer.singleShot(900, step4)


def step4():
    win.grab().save(os.path.join(OUT, "screenshot-chinese.png"))
    print("saved screenshot-chinese.png")
    win._on_nav("jazz")
    QTimer.singleShot(900, step5)


def step5():
    win.grab().save(os.path.join(OUT, "screenshot-jazz.png"))
    print("saved screenshot-jazz.png")
    QTimer.singleShot(500, step6)


def step6():
    from radio.dialogs import PreferencesDialog, StationDialog

    prefs = PreferencesDialog(win, win.library, win.engine)
    prefs.nav.setCurrentRow(1)          # network / proxy
    prefs.show()
    app.processEvents()
    prefs.grab().save(os.path.join(OUT, "screenshot-proxy.png"))
    print("saved screenshot-proxy.png")

    prefs.nav.setCurrentRow(2)          # recording
    app.processEvents()
    prefs.grab().save(os.path.join(OUT, "screenshot-preferences.png"))
    print("saved screenshot-preferences.png")

    prefs.nav.setCurrentRow(4)          # about / author
    app.processEvents()
    prefs.grab().save(os.path.join(OUT, "screenshot-about.png"))
    print("saved screenshot-about.png")
    prefs.hide()

    dlg = StationDialog(win, None, win.engine)
    dlg.name_edit.setText("示例电台")
    dlg.url_edit.setText("https://ice1.somafm.com/groovesalad-128-mp3")
    dlg.show()
    app.processEvents()
    dlg.grab().save(os.path.join(OUT, "screenshot-add-station.png"))
    print("saved screenshot-add-station.png")
    dlg.hide()

    app.quit()


QTimer.singleShot(700, step1)
app.exec()
