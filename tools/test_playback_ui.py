"""Drive the real application: tune a station, let it play, capture the UI.

Verifies the whole chain inside the actual window: relay -> decoder -> level
meter -> FFT spectrum -> live ICY metadata -> transport stats.
"""
import sys
import time

sys.path.insert(0, r"E:\KU\AI\deepseek-harness\network-radio")
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from radio import theme  # noqa: E402
from radio.main_window import MainWindow  # noqa: E402

OUT = sys.argv[1] if len(sys.argv) > 1 else r"E:\KU\AI\deepseek-harness\network-radio\shot_play.png"
PICK = sys.argv[2] if len(sys.argv) > 2 else ""

app = QApplication(sys.argv)
app.setStyle("Fusion")
app.setStyleSheet(theme.stylesheet())
win = MainWindow()
win.resize(1560, 940)
win.show()

log = []


def note(msg):
    log.append(f"[{time.time() - t0:5.1f}s] {msg}")


t0 = time.time()
win.engine.state_changed.connect(lambda s: note(f"state -> {s}"))
win.engine.metadata_changed.connect(lambda m: note(f"metadata -> {m!r}"))
win.engine.error_occurred.connect(lambda e: note(f"ERROR -> {e}"))


def choose():
    rows = win.model.rows
    note(f"rows={len(rows)}")
    target = None
    if PICK:
        for r in rows:
            if PICK.lower() in r.get("name", "").lower() and ".m3u8" not in r.get("url", "").lower():
                target = r
                break
    if target is None:
        # a plain Icecast MP3 station, which exercises ICY metadata
        for r in rows:
            if (int(r.get("bitrate") or 0) >= 128
                    and (r.get("codec") or "").upper() == "MP3"
                    and ".m3u8" not in r.get("url", "").lower()):
                target = r
                break
    if target is None and rows:
        target = rows[0]
    if target:
        note(f"tuning: {target.get('name')} | {target.get('codec')} {target.get('bitrate')}k")
        win.table.select_url(target["url"])
        win.engine.tune(target)
    else:
        note("NO STATION FOUND")


def capture():
    spec = win.engine._prev_bands
    note(f"spectrum max={float(spec.max()):.3f} mean={float(spec.mean()):.3f}")
    note(f"level widget display={win._level._display:.3f} hold={win._level._hold:.3f}")
    note(f"mini title={win._mini_title.fullText()!r}")
    note(f"mini track={win._mini_track.fullText()!r}")
    note(f"np track={win._np_track.fullText()!r}")
    note(f"status={win._status_text.text()!r}")
    note(f"status right={win._status_right.text()!r}")
    note(f"measured={win._q_measured._value.fullText()!r} buffer={win._q_buffer._value.fullText()!r}")
    win.grab().save(OUT)
    note(f"saved {OUT}")
    print("\n".join(log))
    app.quit()


QTimer.singleShot(600, choose)
QTimer.singleShot(13000, capture)
app.exec()
