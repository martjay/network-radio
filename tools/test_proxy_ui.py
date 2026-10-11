"""Verify the proxy setting actually governs playback and connection tests."""
from __future__ import annotations

import sys

sys.path.insert(0, r"E:\KU\AI\deepseek-harness\network-radio")
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from radio import theme  # noqa: E402
from radio.main_window import MainWindow  # noqa: E402
from radio.proxy import MODE_CUSTOM, MODE_NONE, MODE_SYSTEM, ProxyConfig  # noqa: E402

app = QApplication(sys.argv)
app.setStyle("Fusion")
app.setStyleSheet(theme.stylesheet())
win = MainWindow()
win.resize(1560, 940)
win.show()

results = []


def check(name, ok, detail=""):
    results.append((name, ok))
    print(f"  {'PASS' if ok else 'FAIL'}  {name:<46} {detail}")


def run():
    lib, eng = win.library, win.engine
    print("\n--- proxy configuration plumbing ---")

    # system mode (this machine has a live proxy configured)
    lib.set("proxy_mode", MODE_SYSTEM)
    cfg = lib.proxy_config()
    check("system mode resolves a proxy", cfg.usable, cfg.describe())
    check("system mode reports source", bool(cfg.source), cfg.source)

    eng.set_proxy(cfg)
    win._update_proxy_indicator()
    check("status bar shows proxy", cfg.host in win._proxy_btn.text(),
          win._proxy_btn.text().strip())

    # custom mode
    lib.set("proxy_mode", MODE_CUSTOM)
    lib.set("proxy_scheme", "http")
    lib.set("proxy_host", "127.0.0.1")
    lib.set("proxy_port", 7890)
    cfg2 = lib.proxy_config()
    check("custom mode resolves", cfg2.usable and cfg2.host == "127.0.0.1" and cfg2.port == 7890,
          cfg2.describe())

    # none mode
    lib.set("proxy_mode", MODE_NONE)
    cfg3 = lib.proxy_config()
    check("none mode is not usable", cfg3.usable is False, cfg3.describe())
    check("none mode bypasses everything", cfg3.should_proxy("ice1.somafm.com") is False)
    # mirror what the preferences dialog does: push the config into the engine
    eng.set_proxy(cfg3)
    win._update_proxy_indicator()
    check("status bar shows disabled", "关闭" in win._proxy_btn.text(), win._proxy_btn.text().strip())

    # loopback must never be proxied, or the audio relay would break
    custom = ProxyConfig(MODE_CUSTOM, "http", "127.0.0.1", 7890)
    check("relay loopback never proxied", custom.should_proxy("127.0.0.1") is False)

    print("\n--- persistence ---")
    lib.set_proxy_config(custom)
    from radio.library import Library
    fresh = Library()
    again = fresh.proxy_config()
    check("custom proxy persisted", again.usable and again.port == 7890, again.describe())

    # restore to system for the playback test
    lib.set("proxy_mode", MODE_SYSTEM)
    eng.set_proxy(lib.proxy_config())
    QTimer.singleShot(200, phase_play)


def phase_play():
    print("\n--- playback through the active proxy ---")
    target = None
    for r in win.model.rows:
        if "somafm" in r.get("url", "").lower() and "reggae" in r.get("url", "").lower():
            target = r
            break
    if target is None:
        for r in win.model.rows:
            if (r.get("codec") or "").upper() == "MP3":
                target = r
                break
    print(f"        tuning: {target['name']}  proxy={win.engine.proxy.describe()}")
    win.engine.tune(target)
    QTimer.singleShot(11000, phase_verify)


def phase_verify():
    st = win.engine.state
    check("playing via proxy", st == "playing", f"state={st}")
    check("audio decoded", float(win.engine._prev_bands.max()) > 0.3,
          f"spectrum peak={float(win.engine._prev_bands.max()):.3f}")
    relay = win.engine._relay
    check("relay attached", relay is not None, "")
    if relay is not None:
        check("proxy recorded on relay", relay.proxy is not None and relay.proxy.usable,
              relay.proxy.describe() if relay.proxy else "none")

    print("\n--- connection test honours the proxy ---")
    res = win.engine.test_station("https://ice1.somafm.com/groovesalad-128-mp3", timeout=12)
    check("test_station succeeds", res["ok"], f"{res.get('kbps', 0):.0f} kbps")

    win.engine.stop()
    win.grab().save(r"E:\KU\AI\deepseek-harness\network-radio\tools\_testout\proxy_play.png")

    print("\n=== SUMMARY ===")
    passed = sum(1 for _, ok in results if ok)
    failed = [n for n, ok in results if not ok]
    print(f"{passed}/{len(results)} checks passed")
    if failed:
        print("FAILED: " + ", ".join(failed))
    app.quit()
    sys.exit(1 if failed else 0)


QTimer.singleShot(700, run)
app.exec()
