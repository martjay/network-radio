"""Verify tray behaviour, close-to-tray, window-size persistence and DPI."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, r"E:\KU\AI\deepseek-harness\network-radio")
from PySide6.QtWidgets import QApplication  # noqa: E402

from radio import appicon, theme  # noqa: E402
from radio.main_window import MainWindow  # noqa: E402

app = QApplication(sys.argv)
app.setStyle("Fusion")
app.setStyleSheet(theme.stylesheet())

results: list[tuple[str, bool]] = []


def check(name, ok, detail=""):
    results.append((name, ok))
    print(f"  {'PASS' if ok else 'FAIL'}  {name:<46} {detail}")


print("=== 1. application icon ===")
ic = appicon.app_icon()
sizes = sorted({(s.width(), s.height()) for s in ic.availableSizes()})
check("icon is not null", not ic.isNull())
check("multi-resolution", len(sizes) >= 8, f"{len(sizes)} sizes: {sizes[:5]}...")
check("has 16px (taskbar)", (16, 16) in sizes)
check("has 256px (explorer)", (256, 256) in sizes)
ico = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "assets", "broadcast.ico")
check(".ico exists for the exe", os.path.isfile(ico),
      f"{os.path.getsize(ico)} bytes" if os.path.isfile(ico) else "missing")

print("\n=== 2. window icon / tray icon ===")
win = MainWindow()
win.resize(1400, 880)
win.show()
app.processEvents()
check("window icon set", not win.windowIcon().isNull())
check("tray available", bool(win.tray and win.tray.available))
if win.tray and win.tray.available:
    check("tray icon visible", win.tray.icon.isVisible())
    check("tray tooltip set", bool(win.tray.icon.toolTip()))
    texts = [a.text() for a in win.tray.menu.actions() if a.text()]
    check("menu has transport", any("播放" in t or "暂停" in t for t in texts), str(texts[:3]))
    check("menu has record", any("录制" in t for t in texts))
    check("menu has favorite", any("收藏" in t for t in texts))
    check("menu has quit", any("退出" in t for t in texts))

print("\n=== 3. close hides to tray (does not quit) ===")
win.library.set("close_to_tray", True, save=False)
win.library.set("tray_notifications", False, save=False)
win.show()
app.processEvents()
win.close()
app.processEvents()
check("window hidden after close", not win.isVisible())
check("still alive (not quit)", win._really_quit is False)
check("geometry was saved", bool(win.library.get("window_geometry")),
      str(win.library.get("window_geometry")))

print("\n=== 4. real quit path ===")
win.show()
app.processEvents()
win._quit_from_tray()
app.processEvents()
check("_really_quit set", win._really_quit is True)

print("\n=== 5. window size persistence across restart ===")
win2 = MainWindow()
saved = win2.library.get("window_geometry")
check("restored from saved geometry", bool(saved), str(saved))
if saved:
    x, y, w, h = (int(v) for v in str(saved).split(","))
    got = (win2.width(), win2.height())
    check("restored size matches", got == (w, h), f"saved={w}x{h} got={got[0]}x{got[1]}")

print("\n=== 6. off-screen geometry is clamped ===")
win2.library.set("window_geometry", "9000,9000,1200,800", save=False)
win2._restore_geometry()
scr = app.primaryScreen().availableGeometry()
check("window pulled back on screen",
      scr.contains(win2.geometry().center()),
      f"center={win2.geometry().center()} screen={scr}")

print("\n=== 7. DPI awareness ===")
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
scr0 = QGuiApplication.primaryScreen()
check("device pixel ratio reported", scr0.devicePixelRatio() > 0,
      f"dpr={scr0.devicePixelRatio()}")
check("logical DPI reported", scr0.logicalDotsPerInch() > 0,
      f"{scr0.logicalDotsPerInch():.0f} dpi")
policy = QApplication.highDpiScaleFactorRoundingPolicy()
check("rounding policy is PassThrough",
      policy == Qt.HighDpiScaleFactorRoundingPolicy.PassThrough, str(policy))

print()
passed = sum(1 for _, ok in results if ok)
failed = [n for n, ok in results if not ok]
print(f"{passed}/{len(results)} checks passed")
if failed:
    print("FAILED: " + ", ".join(failed))
sys.exit(1 if failed else 0)
