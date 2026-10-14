"""Verify list pagination: slicing, page controls, size change, cross-page step."""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
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
win.search.blockSignals(True)
win.search.setText("")
win.search.blockSignals(False)
win._quality_chip.setChecked(False)
win._fav_chip.blockSignals(True)
win._fav_chip.setChecked(False)
win._fav_chip.blockSignals(False)
win._zh_chip.blockSignals(True)
win._zh_chip.setChecked(False)
win._zh_chip.blockSignals(False)
win._on_nav("all")
win._set_country_filter("all")
win._apply_filters()
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
check("page label",
      win._page_edit.text() == "1" and win._page_total.text() == f"/ {pages}",
      f"{win._page_edit.text()} {win._page_total.text()}")
check("prev disabled on first page", not win._page_prev.isEnabled())
check("next enabled", win._page_next.isEnabled())

print("\n=== 2. page navigation ===")
win._page_next.click()
app.processEvents()
check("page 2 shown", win._page == 1 and win._page_edit.text() == "2")
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

print("\n=== 6. type a page number ===")
pages = win._page_count()
win._page_edit.setText("3")
win._jump_typed_page()
app.processEvents()
check("typed 3 lands on page 3", win._page == 2, f"page={win._page}")
check("readout follows", win._page_edit.text() == "3")
too_high = str(pages + 40)
win._page_edit.setText(too_high)
win._jump_typed_page()
app.processEvents()
check("overshoot clamps to last page", win._page == pages - 1, f"page={win._page} pages={pages}")
win._page_edit.setText("abc")
win._jump_typed_page()
app.processEvents()
check("garbage restores current page", win._page_edit.text() == str(win._page + 1))

print("\n=== 7. select_station jumps pages ===")
target = win._filtered_rows[75]
win.select_station(target.get("url"))
app.processEvents()
check("jumped to target page", win._page == 75 // 30, f"page={win._page}")
check("target selected",
      win.model.station_at(win.table.currentIndex().row()).get("url") == target.get("url"))

print("\n=== 8. empty filter overlay ===")
from radio.taxonomy import GENRES  # noqa: E402

have = {(s.get("genre"), s.get("country")) for s in win.library.all_stations()}
countries = [n for n, _ in win.library.country_options()]
empty_pair = None
for g, _zh, _en, _kws in GENRES:
    for c in countries:
        if (g, c) not in have:
            empty_pair = (g, c)
            break
    if empty_pair:
        break
check("found empty genre+country pair", empty_pair is not None, str(empty_pair))
if empty_pair:
    win.search.blockSignals(True)
    win.search.setText("")
    win.search.blockSignals(False)
    win._on_nav(empty_pair[0])
    win._set_country_filter(empty_pair[1])
    win._apply_filters()
    app.processEvents()
    check("overlay shown on empty list", win._empty_state.isVisible())
    check("empty hint mentions filters",
          empty_pair[1] in win._empty_hint.text(), win._empty_hint.text())
    win._empty_clear_country.click()
    app.processEvents()
    check("clear country restores rows or overlay", True)
    country_cleared = (win._country_combo.currentData() or "all") == "all"
    check("country filter cleared", country_cleared)
    if win._empty_state.isVisible():
        win._empty_clear_genre.click()
        app.processEvents()
    else:
        win._clear_genre_filter()
        app.processEvents()
    check("genre back to all", win._section == "all")
    check("overlay hidden when rows exist",
          (not win._empty_state.isVisible()) == (len(win._filtered_rows) > 0),
          f"empty={win._empty_state.isVisible()} rows={len(win._filtered_rows)}")

print("\n=== 9. locate playing station ===")
win._clear_list_filters()
app.processEvents()
target = win._filtered_rows[80]
win.engine.station = dict(target)
win._sync_locate_enabled()
check("locate enabled when tuned", win._locate_btn.isEnabled())
win.search.setText("zzz-no-such-station-xyz-locate")
app.processEvents()
check("search hides the tuned station",
      not any(r.get("url") == target.get("url") for r in win._filtered_rows))
win._locate_playing()
app.processEvents()
check("locate clears search", win.search.text() == "")
check("tuned station is in the list again",
      any(r.get("url") == target.get("url") for r in win._filtered_rows))
sel = win.model.station_at(win.table.currentIndex().row())
check("located row selected",
      bool(sel) and sel.get("url") == target.get("url"))
win.engine.station = {}
win._sync_locate_enabled()
check("locate disabled when idle", not win._locate_btn.isEnabled())

print()
passed = sum(1 for _, ok in results if ok)
failed = [n for n, ok in results if not ok]
print(f"{passed}/{len(results)} checks passed")
if failed:
    print("FAILED: " + ", ".join(failed))
win._really_quit = True
win.close()
sys.exit(1 if failed else 0)
