"""Verify the folder button now works, including the unwritable-directory case."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, r"E:\KU\AI\deepseek-harness\network-radio")
from PySide6.QtWidgets import QApplication  # noqa: E402

from radio import paths, theme  # noqa: E402
from radio.main_window import MainWindow, _ensure_dir, _reveal_in_file_manager  # noqa: E402

app = QApplication(sys.argv)
app.setStyle("Fusion")
app.setStyleSheet(theme.stylesheet())
win = MainWindow()
win.show()
app.processEvents()

results = []


def check(name, ok, detail=""):
    results.append((name, ok))
    print(f"  {'PASS' if ok else 'FAIL'}  {name:<44} {detail}")


print("=== 1. the exact case that used to crash ===")
# C:\Users\tianj\Music\... is not writable in this sandbox, which is what made
# the old handler raise PermissionError before it could open anything.
unwritable = os.path.join(os.path.expanduser("~"), "Music", "Broadcast Recordings")
print(f"  unwritable path: {unwritable}")
print(f"  _ensure_dir      : {_ensure_dir(unwritable)}")

win.library.set("recordings_dir", unwritable, save=False)
try:
    win._open_recordings()
    check("handler does not raise", True, f"status={win._status_text.text()[:56]!r}")
except Exception as exc:  # noqa: BLE001
    check("handler does not raise", False, f"{type(exc).__name__}: {exc}")

resolved = win._recordings_dir()
check("falls back to a writable dir", _ensure_dir(resolved) and resolved != unwritable,
      resolved)

print("\n=== 2. explicit writable directory ===")
good = os.path.join(paths.app_dir(), "recordings")
win.library.set("recordings_dir", good, save=False)
try:
    win._open_recordings()
    check("opens explicit dir", os.path.isdir(good), win._status_text.text()[:56])
except Exception as exc:  # noqa: BLE001
    check("opens explicit dir", False, f"{type(exc).__name__}: {exc}")

print("\n=== 3. simulated button click ===")
win.library.set("recordings_dir", good, save=False)
try:
    win._rec_folder_btn.click()
    app.processEvents()
    check("button click works", True, win._status_text.text()[:56])
except Exception as exc:  # noqa: BLE001
    check("button click works", False, f"{type(exc).__name__}: {exc}")

print("\n=== 4. About-page buttons ===")
from radio.dialogs import PreferencesDialog  # noqa: E402
dlg = PreferencesDialog(win, win.library, win.engine)
for label, fn in (("data dir", lambda: dlg._open_path(paths.app_dir())),
                  ("recordings dir", lambda: dlg._open_path(dlg._recordings_dir())),
                  ("repo url", lambda: dlg._open_url(paths.APP_REPO))):
    try:
        fn()
        check(f"about: {label}", True, "(no exception)")
    except Exception as exc:  # noqa: BLE001
        check(f"about: {label}", False, f"{type(exc).__name__}: {exc}")

print("\n=== 5. _reveal_in_file_manager return value ===")
r = _reveal_in_file_manager(good)
print(f"  returned {r}  (True = a file manager was launched)")
check("returns a bool", isinstance(r, bool), str(r))

print()
passed = sum(1 for _, ok in results if ok)
failed = [n for n, ok in results if not ok]
print(f"{passed}/{len(results)} checks passed")
if failed:
    print("FAILED: " + ", ".join(failed))
sys.exit(1 if failed else 0)
