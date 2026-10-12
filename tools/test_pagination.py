"""Verify list pagination: slicing, page controls, size change, cross-page step."""
from __future__ import annotations

import sys

sys.path.insert(0, r"E:\KU\AI\deepseek-harness\network-radio")
from PySide6.QtWidgets import QApplication  # noqa: E402

from radio import theme  # noqa: E402
from radio.main_window import MainWindow  # noqa: E402

app = QApplication(sys.argv)
app.setStyle("Fusion")
app.setStyleSheet(theme.stylesheet())
win = MainWindow()
win.show()
app.processEvents()

results: list[tuple[str, bool]] = []


def check(name, ok, detail=""):
    results.append((name, ok))
    print(f"  {'PASS' if ok else 'FAIL'}  {name:<46} {detail}")


print("=== 1. default page size and slicing ===")
win.engine.stop()
win.library.set("page_size", 30, save=False)
idx = win._page_size_combo.findData(30)
win._page_size_combo.setCurrentIndex(idx)
win._page = 0
win._show_page()
app.processEvents()
total = len(win._filtered_rows)
check("filtered list populated", total > 30, f"{total} stations")
check("model shows one page", len(win.model.rows) == 30, f"{len(win.model.rows)} rows")
pages = win._page_count()
check("page count correct", pages == (total + 29) // 30, f"{pages} pages")
check("page label", win._page_label.text() == f"1 / {pages}", win._page_label.text())
check("prev disabled on first page", not win._page_prev.isEnabled())
check("next enabled", win._page_next.isEnabled())

print("\n=== 2. page navigation ===")
win._page_next.click()
app.processEvents()
check("page 2 shown", win._page == 1 and "2 /" in win._page_label.text())
check("page 2 rows differ", win.model.rows[0].get("url") != win._filtered_rows[0].get("url"))
check("page 2 starts at row 30", win.model.rows[0].get("url") == win._filtered_rows[30].get("url"))
check("prev enabled on page 2", win._page_prev.isEnabled())

print("\n=== 3. page size change keeps anchor ===")
win._goto_page(1)   # rows 30..59 visible
win._page_size_combo.setCurrentIndex(win._page_size_combo.findData(50))
app.processEvents()
check("page size saved", int(win.library.get("page_size")) == 50)
check("model shows 50 rows", len(win.model.rows) == 50, f"{len(win.model.rows)}")
# anchor: old page 1 (30/page) started at index 30 -> 30 // 50 == page 0
check("anchor preserved", win._page == 30 // 50, f"page={win._page}")

print("\n=== 4. filter change resets to page 1 ===")
win._goto_page(1)
win.search.setText("jazz")
app.processEvents()
check("back on page 1 after filter", win._page == 0)
check("filtered smaller", len(win._filtered_rows) < total, f"{len(win._filtered_rows)} rows")
win.search.clear()
app.processEvents()

print("\n=== 5. cross-page step ===")
win._page_size_combo.setCurrentIndex(win._page_size_combo.findData(30))
app.processEvents()
win._page = 0
win._show_page()
# pretend the last row of page 1 is playing, then step forward -> page 2
win.engine.station = dict(win._filtered_rows[29])
win._step(1)
app.processEvents()
check("step turned the page", win._page == 1, f"page={win._page}")
check("stepped to row 30", win.engine.station.get("url") == win._filtered_rows[30].get("url"))
check("selection follows", win.table.currentIndex().row() == 0,
      f"row={win.table.currentIndex().row()}")
win.engine.stop()

print("\n=== 6. select_station jumps pages ===")
target = win._filtered_rows[75]
win.select_station(target.get("url"))
app.processEvents()
check("jumped to target page", win._page == 75 // 30, f"page={win._page}")
check("target selected",
      win.model.station_at(win.table.currentIndex().row()).get("url") == target.get("url"))

print()
passed = sum(1 for _, ok in results if ok)
failed = [n for n, ok in results if not ok]
print(f"{passed}/{len(results)} checks passed")
if failed:
    print("FAILED: " + ", ".join(failed))
sys.exit(1 if failed else 0)
