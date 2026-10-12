"""Refresh bundled station stream URLs from radio-browser.info.

The catalogue shipped in the exe is a snapshot. This module downloads the
current community database (via the same servers used to build it) and
matches our stations by name + country so a moved stream can be patched
without waiting for a new release.
"""
from __future__ import annotations

import json
import re
import unicodedata
import urllib.parse

from .proxy import make_http_connection

SERVERS = (
    "https://de1.api.radio-browser.info",
    "https://de2.api.radio-browser.info",
    "https://nl1.api.radio-browser.info",
    "https://at1.api.radio-browser.info",
    "https://fi1.api.radio-browser.info",
)
UA = "BROADCAST/1.0.4 (https://github.com/martjay/network-radio)"


def _norm_name(name: str) -> str:
    text = unicodedata.normalize("NFKC", name or "").casefold()
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _fetch_json(path: str, proxy=None, timeout: float = 40.0) -> list:
    last = None
    for base in SERVERS:
        parsed = urllib.parse.urlsplit(base)
        host = parsed.hostname or ""
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        conn = None
        try:
            conn = make_http_connection(
                parsed.scheme, host, port, timeout, verify=True, proxy=proxy,
            )
            conn.request("GET", path, headers={"User-Agent": UA, "Accept": "application/json"})
            resp = conn.getresponse()
            body = resp.read()
            if resp.status != 200:
                last = f"HTTP {resp.status}"
                continue
            data = json.loads(body.decode("utf-8", "replace"))
            return data if isinstance(data, list) else []
        except Exception as exc:  # noqa: BLE001
            last = exc
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:  # noqa: BLE001
                    pass
    raise RuntimeError(f"无法连接电台数据库：{last}")


def _best_url(row: dict) -> str:
    for key in ("url_resolved", "url"):
        u = (row.get(key) or "").strip()
        if u.startswith(("http://", "https://")):
            return u
    return ""


def _index_remote(rows: list[dict]) -> dict[tuple[str, str], dict]:
    best: dict[tuple[str, str], dict] = {}
    for row in rows:
        name = _norm_name(row.get("name") or "")
        cc = (row.get("countrycode") or "").strip().upper()
        url = _best_url(row)
        if not name or not cc or not url:
            continue
        if int(row.get("lastcheckok") or 1) == 0:
            continue
        key = (name, cc)
        prev = best.get(key)
        votes = int(row.get("votes") or 0)
        if prev is None or votes > int(prev.get("votes") or 0):
            best[key] = row
    return best


def collect_url_patches(stations: list[dict], proxy=None) -> dict:
    """Compare local builtin stations to radio-browser. Returns a result dict."""
    empty = {
        "ok": False, "updated": 0, "checked": 0, "unmatched": 0,
        "patches": [], "error": "",
    }
    remote: dict[tuple[str, str], dict] = {}
    last_err = ""
    try:
        remote = _index_remote(
            _fetch_json("/json/stations?hidebroken=true&limit=50000", proxy=proxy)
        )
    except Exception as exc:  # noqa: BLE001
        last_err = str(exc)
        codes = sorted({
            (s.get("cc") or "").strip().upper()
            for s in stations
            if not s.get("custom") and (s.get("cc") or "").strip()
        })
        for cc in codes:
            path = (
                f"/json/stations/bycountrycodeexact/{urllib.parse.quote(cc)}"
                f"?hidebroken=true&limit=5000"
            )
            try:
                remote.update(_index_remote(_fetch_json(path, proxy=proxy)))
            except Exception as inner:  # noqa: BLE001
                last_err = str(inner)
    if not remote:
        empty["error"] = last_err or "电台数据库没有返回可用条目"
        return empty

    patches: list[dict] = []
    unmatched = 0
    for s in stations:
        if s.get("custom"):
            continue
        name = s.get("name") or ""
        cc = (s.get("cc") or "").strip().upper()
        old = (s.get("url") or "").strip()
        hit = remote.get((_norm_name(name), cc))
        if not hit:
            unmatched += 1
            continue
        new = _best_url(hit)
        if not new or new == old:
            continue
        patches.append({
            "name": name,
            "cc": cc,
            "from": old,
            "to": new,
            "codec": (hit.get("codec") or s.get("codec") or "").upper(),
            "bitrate": int(hit.get("bitrate") or s.get("bitrate") or 0),
            "homepage": (hit.get("homepage") or s.get("homepage") or "").strip(),
        })
    return {
        "ok": True,
        "updated": len(patches),
        "checked": len(remote),
        "unmatched": unmatched,
        "patches": patches,
        "error": "",
    }
