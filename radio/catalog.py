"""Sync the local catalogue against radio-browser.info.

The installer ships a verified snapshot. This module downloads the current
community database, patches stream URLs of stations we already have (matched
by name + country), and classifies leftover live entries into the same genre
taxonomy so the list can grow without a new release.
"""
from __future__ import annotations

import json
import re
import unicodedata
import urllib.parse

from . import paths
from .proxy import make_http_connection
from .taxonomy import (
    LIVE_MAX, LIVE_PER_COUNTRY, LIVE_PER_GENRE, LIVE_PER_GENRE_HARD,
    LIVE_PRIORITY, select_additions, station_from_source,
)

SERVERS = (
    "https://de1.api.radio-browser.info",
    "https://de2.api.radio-browser.info",
    "https://nl1.api.radio-browser.info",
    "https://at1.api.radio-browser.info",
    "https://fi1.api.radio-browser.info",
)
UA = f"BROADCAST/{paths.APP_VERSION} ({paths.APP_REPO})"


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
        if row.get("lastcheckok") is not None and int(row.get("lastcheckok") or 0) == 0:
            continue
        key = (name, cc)
        prev = best.get(key)
        votes = int(row.get("votes") or 0)
        if prev is None or votes > int(prev.get("votes") or 0):
            best[key] = row
    return best


def _fetch_remote_rows(stations: list[dict], proxy=None) -> tuple[list[dict], str]:
    last_err = ""
    try:
        rows = _fetch_json("/json/stations?hidebroken=true&limit=50000", proxy=proxy)
        if rows:
            return rows, ""
    except Exception as exc:  # noqa: BLE001
        last_err = str(exc)
    codes = {
        (s.get("cc") or "").strip().upper()
        for s in stations
        if not s.get("custom") and (s.get("cc") or "").strip()
    }
    codes.update(cc for cc, _quota in LIVE_PRIORITY)
    rows: list[dict] = []
    for cc in sorted(codes):
        path = (
            f"/json/stations/bycountrycodeexact/{urllib.parse.quote(cc)}"
            f"?hidebroken=true&limit=5000"
        )
        try:
            chunk = _fetch_json(path, proxy=proxy)
        except Exception as inner:  # noqa: BLE001
            last_err = str(inner)
            continue
        if chunk:
            rows.extend(chunk)
    return rows, last_err


def _patches_from_index(stations: list[dict], remote: dict) -> tuple[list[dict], int]:
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
    return patches, unmatched


def collect_catalogue_sync(stations: list[dict], proxy=None) -> dict:
    """Patch moved URLs and propose classified additions from radio-browser."""
    empty = {
        "ok": False, "updated": 0, "added": 0, "checked": 0, "unmatched": 0,
        "patches": [], "additions": [], "error": "",
    }
    rows, last_err = _fetch_remote_rows(stations, proxy=proxy)
    remote = _index_remote(rows)
    if not remote:
        empty["error"] = last_err or "电台数据库没有返回可用条目"
        return empty

    patches, unmatched = _patches_from_index(stations, remote)
    pool = []
    for row in rows:
        rec = station_from_source(row)
        if rec is not None:
            pool.append(rec)
    additions = select_additions(
        pool,
        existing=[s for s in stations if not s.get("custom")],
        max_total=LIVE_MAX,
        per_genre=LIVE_PER_GENRE,
        per_genre_hard=LIVE_PER_GENRE_HARD,
        per_country=LIVE_PER_COUNTRY,
        priority=LIVE_PRIORITY,
    )
    return {
        "ok": True,
        "updated": len(patches),
        "added": len(additions),
        "checked": len(remote),
        "unmatched": unmatched,
        "patches": patches,
        "additions": additions,
        "error": "",
    }


def collect_url_patches(stations: list[dict], proxy=None) -> dict:
    """Backward-compatible wrapper: URL patches only."""
    result = collect_catalogue_sync(stations, proxy=proxy)
    return result
