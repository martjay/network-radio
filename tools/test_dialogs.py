"""Render each dialog and capture it, so the secondary surfaces are verified
visually rather than assumed."""
import os
import sys

sys.path.insert(0, r"E:\KU\AI\deepseek-harness\network-radio")
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from radio import theme  # noqa: E402
from radio.dialogs import (  # noqa: E402
    ExportDialog, PreferencesDialog, ReportDialog, StationDialog,
)
from radio.main_window import MainWindow  # noqa: E402

OUT = r"E:\KU\AI\deepseek-harness\network-radio\tools\_testout"
os.makedirs(OUT, exist_ok=True)

app = QApplication(sys.argv)
app.setStyle("Fusion")
app.setStyleSheet(theme.stylesheet())

win = MainWindow()
win.resize(1560, 940)
win.show()

shots = []


def grab(widget, name):
    widget.show()
    app.processEvents()
    path = os.path.join(OUT, f"{name}.png")
    widget.grab().save(path)
    shots.append((name, widget.width(), widget.height(), path))
    widget.hide()


def run():
    lib = win.library
    eng = win.engine

    d1 = StationDialog(win)
    d1.name_edit.setText("示例电台")
    d1.url_edit.setText("https://ice1.somafm.com/groovesalad-128-mp3")
    grab(d1, "dlg_station")

    d2 = PreferencesDialog(win, lib, eng)
    for i, name in enumerate(["dlg_pref_playback", "dlg_pref_network", "dlg_pref_recording",
                              "dlg_pref_interface", "dlg_pref_about"]):
        d2.nav.setCurrentRow(i)
        grab(d2, name)

    # custom-proxy mode shows the address fields enabled
    from radio.proxy import MODE_CUSTOM
    d2.nav.setCurrentRow(1)
    idx = d2._proxy_mode.findData(MODE_CUSTOM)
    d2._proxy_mode.setCurrentIndex(idx)
    d2._proxy_host.setText("127.0.0.1")
    d2._proxy_port.setText("7890")
    app.processEvents()
    grab(d2, "dlg_pref_network_custom")

    station = win.library.stations[0]
    d3 = ReportDialog(win, station, eng)
    grab(d3, "dlg_report")

    d4 = ExportDialog(win, lib)
    grab(d4, "dlg_export")

    for name, w, h, path in shots:
        print(f"  {name:<22} {w:>4}x{h:<4} {path}")
    print(f"\ncaptured {len(shots)} dialogs")
    app.quit()


QTimer.singleShot(900, run)
app.exec()
