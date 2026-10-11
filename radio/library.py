"""Catalogue and user data.

The bundled catalogue is read-only. Everything the user changes - favourites,
custom stations, listening history, play counts, preferences - lives in a
single JSON document under the per-user data directory and is written
atomically.
"""
from __future__ import annotations

import json
import os
import tempfile
import time

from PySide6.QtCore import QObject, Signal

from . import paths

DEFAULTS: dict = {
    "volume": 72,
    "muted": False,
    "last_station": "",
    "recordings_dir": "",
    "record_format": "mp3",
    "record_bitrate": 192,
    "auto_record": False,
    "sleep_minutes": 0,
    "sleep_action": "stop",
    "window_geometry": "",
    "window_maximized": False,
    "close_to_tray": True,
    "tray_notifications": True,
    "genre": "all",
    "country": "all",
    "sort": "score",
    "favorites_only": False,
    "zh_only": False,
    "min_bitrate": 0,
    "show_spectrum": True,
    "resume_last": True,
    "notify_track": False,
    "sidebar_width": 208,
    "right_width": 344,
    # proxy
    "proxy_mode": "system",          # system | none | custom
    "proxy_scheme": "http",          # http | socks5
    "proxy_host": "",
    "proxy_port": 0,
    "proxy_username": "",
    "proxy_password": "",
}

SORT_MODES = [
    ("score", "推荐排序"),
    ("votes", "听众投票"),
    ("bitrate", "音质优先"),
    ("name", "名称 A-Z"),
    ("country", "国家地区"),
    ("genre", "类型"),
]

GENRE_LABELS = {
    "all": ("全部电台", "ALL STATIONS"),
    "favorites": ("我的收藏", "FAVOURITES"),
    "recent": ("最近播放", "RECENTLY PLAYED"),
    "top": ("常听电台", "MOST PLAYED"),
    "custom": ("自建电台", "MY STATIONS"),
    "zh": ("中文电台", "CHINESE"),
}


def _atomic_write(path: str, payload: str) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tmp", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


class Library(QObject):
    favorites_changed = Signal()
    custom_changed = Signal()
    history_changed = Signal()
    setting_changed = Signal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.stations: list[dict] = []
        self.meta: dict = {}
        self.custom: list[dict] = []
        self.favorites: list[str] = []          # ordered, most recent first
        self.history: list[dict] = []           # most recent first
        self.play_counts: dict[str, int] = {}
        self.settings: dict = dict(DEFAULTS)
        self._by_url: dict[str, dict] = {}
        self._load_catalogue()
        self._load_userdata()

    # ------------------------------------------------------------------ #
    #  catalogue
    # ------------------------------------------------------------------ #
    def _load_catalogue(self) -> None:
        path = paths.bundled("stations.json")
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            data = {"stations": [], "genres": [], "countries": []}
        self.meta = {
            "generated": data.get("generated", ""),
            "source": data.get("source", ""),
            "genres": data.get("genres", []),
            "countries": data.get("countries", []),
        }
        self.stations = data.get("stations", [])
        for i, s in enumerate(self.stations):
            s["id"] = f"s{i}"
            s["custom"] = False
        self._reindex()

    def _reindex(self) -> None:
        self._by_url = {}
        for s in self.all_stations():
            self._by_url.setdefault(s.get("url", ""), s)

    def all_stations(self) -> list[dict]:
        return self.stations + self.custom

    def by_url(self, url: str) -> dict | None:
        return self._by_url.get(url)

    def find(self, url: str) -> dict | None:
        """Return a catalogue/custom entry, or a minimal station for a bare URL."""
        hit = self._by_url.get(url)
        if hit:
            return hit
        for s in self.all_stations():
            if s.get("url") == url:
                return s
        return None

    # ------------------------------------------------------------------ #
    #  user data
    # ------------------------------------------------------------------ #
    def _load_userdata(self) -> None:
        path = paths.user_file(paths.USERDATA)
        if os.path.isfile(path):
            try:
                with open(path, encoding="utf-8") as fh:
                    data = json.load(fh)
            except (OSError, json.JSONDecodeError):
                data = {}
            self.custom = data.get("custom", []) or []
            self.favorites = data.get("favorites", []) or []
            self.history = data.get("history", []) or []
            self.play_counts = data.get("play_counts", {}) or {}
            stored = data.get("settings", {}) or {}
            for key, value in stored.items():
                if key in DEFAULTS:
                    self.settings[key] = value
                else:
                    self.settings[key] = value
        for i, s in enumerate(self.custom):
            s.setdefault("id", f"c{i}")
            s["custom"] = True
            s.setdefault("country", "自定义")
            s.setdefault("cc", "")
            s.setdefault("genre", "varied")
            s.setdefault("codec", "")
            s.setdefault("bitrate", 0)
            s.setdefault("votes", 0)
            s.setdefault("score", 0.0)
            s.setdefault("zh", False)
        self._reindex()

    def save(self) -> None:
        payload = json.dumps(
            {
                "version": 1,
                "custom": self.custom,
                "favorites": self.favorites,
                "history": self.history[:400],
                "play_counts": self.play_counts,
                "settings": self.settings,
            },
            ensure_ascii=False,
            indent=1,
        )
        try:
            _atomic_write(paths.user_file(paths.USERDATA), payload)
        except OSError:
            pass

    # ------------------------------------------------------------------ #
    #  settings
    # ------------------------------------------------------------------ #
    def get(self, key: str, fallback=None):
        if key in self.settings:
            return self.settings[key]
        return DEFAULTS.get(key, fallback)

    def set(self, key: str, value, save: bool = True) -> None:
        if self.settings.get(key) == value:
            return
        self.settings[key] = value
        self.setting_changed.emit(key, value)
        if save:
            self.save()

    # ------------------------------------------------------------------ #
    #  favourites
    # ------------------------------------------------------------------ #
    def is_favorite(self, url: str) -> bool:
        return url in self.favorites

    def toggle_favorite(self, url: str) -> bool:
        if url in self.favorites:
            self.favorites.remove(url)
            state = False
        else:
            self.favorites.insert(0, url)
            state = True
        self.save()
        self.favorites_changed.emit()
        return state

    def favorite_stations(self) -> list[dict]:
        out = []
        for url in self.favorites:
            s = self.find(url)
            if s:
                out.append(s)
        return out

    # ------------------------------------------------------------------ #
    #  custom stations
    # ------------------------------------------------------------------ #
    def add_custom(self, station: dict) -> dict:
        url = station.get("url", "").strip()
        existing = self.find(url)
        if existing and not existing.get("custom"):
            # already in the catalogue: just favourite it
            if url not in self.favorites:
                self.favorites.insert(0, url)
                self.save()
                self.favorites_changed.emit()
            return existing
        if existing and existing.get("custom"):
            existing.update({k: v for k, v in station.items() if v})
            self.save()
            self.custom_changed.emit()
            return existing

        rec = {
            "id": f"c{int(time.time()*1000)}",
            "name": station.get("name", "未命名电台").strip() or "未命名电台",
            "url": url,
            "genre": station.get("genre", "varied"),
            "country": station.get("country", "自定义"),
            "cc": station.get("cc", ""),
            "language": station.get("language", ""),
            "tags": station.get("tags", ""),
            "homepage": station.get("homepage", ""),
            "favicon": "",
            "codec": station.get("codec", ""),
            "bitrate": int(station.get("bitrate") or 0),
            "sample_rate": "",
            "channels": 2,
            "votes": 0,
            "clicks": 0,
            "zh": bool(station.get("zh", False)),
            "score": 0.0,
            "custom": True,
        }
        self.custom.append(rec)
        self._reindex()
        self.save()
        self.custom_changed.emit()
        return rec

    def update_custom(self, station_id: str, changes: dict) -> None:
        for s in self.custom:
            if s.get("id") == station_id:
                old_url = s.get("url")
                s.update(changes)
                if old_url != s.get("url") and old_url in self.favorites:
                    self.favorites = [s["url"] if u == old_url else u for u in self.favorites]
                self._reindex()
                self.save()
                self.custom_changed.emit()
                return

    def remove_custom(self, station_id: str) -> None:
        target = next((s for s in self.custom if s.get("id") == station_id), None)
        self.custom = [s for s in self.custom if s.get("id") != station_id]
        if target:
            url = target.get("url")
            self.favorites = [u for u in self.favorites if u != url]
            self.history = [h for h in self.history if h.get("url") != url]
        self._reindex()
        self.save()
        self.custom_changed.emit()
        self.favorites_changed.emit()

    # ------------------------------------------------------------------ #
    #  history
    # ------------------------------------------------------------------ #
    def record_play(self, station: dict) -> None:
        url = station.get("url", "")
        if not url:
            return
        entry = {
            "url": url,
            "name": station.get("name", ""),
            "genre": station.get("genre", ""),
            "country": station.get("country", ""),
            "ts": time.time(),
        }
        self.history = [h for h in self.history if h.get("url") != url]
        self.history.insert(0, entry)
        del self.history[400:]
        self.play_counts[url] = self.play_counts.get(url, 0) + 1
        self.save()
        self.history_changed.emit()

    def recent_stations(self, limit: int = 80) -> list[dict]:
        out = []
        for h in self.history[:limit]:
            s = self.find(h["url"])
            if s:
                out.append(s)
            else:
                out.append({
                    "id": "h" + h["url"][-8:],
                    "name": h.get("name", h["url"]),
                    "url": h["url"],
                    "genre": h.get("genre", "varied"),
                    "country": h.get("country", ""),
                    "cc": "",
                    "codec": "",
                    "bitrate": 0,
                    "votes": 0,
                    "score": 0.0,
                    "zh": False,
                    "custom": False,
                })
        return out

    def most_played(self, limit: int = 60) -> list[dict]:
        ranked = sorted(self.play_counts.items(), key=lambda kv: -kv[1])
        out = []
        for url, count in ranked[:limit]:
            s = self.find(url)
            if s:
                out.append(s)
        return out

    def play_count(self, url: str) -> int:
        return self.play_counts.get(url, 0)

    # ------------------------------------------------------------------ #
    #  querying
    # ------------------------------------------------------------------ #
    def genre_options(self) -> list[tuple[str, str, str, int]]:
        """(key, zh label, en label, count) for the sidebar."""
        counts: dict[str, int] = {}
        for s in self.stations:
            g = s.get("genre", "varied")
            counts[g] = counts.get(g, 0) + 1
        order = {g["key"]: i for i, g in enumerate(self.meta.get("genres", []))}
        labels = {g["key"]: (g["zh"], g["en"]) for g in self.meta.get("genres", [])}
        rows = []
        for key, count in counts.items():
            zh, en = labels.get(key, (key, key.upper()))
            rows.append((key, zh, en, count))
        rows.sort(key=lambda r: order.get(r[0], 999))
        return rows

    def country_options(self) -> list[tuple[str, int]]:
        counts: dict[str, int] = {}
        for s in self.stations:
            name = s.get("country") or "其他"
            counts[name] = counts.get(name, 0) + 1
        return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))

    def query(
        self,
        section: str = "all",
        text: str = "",
        country: str = "all",
        min_bitrate: int = 0,
        favorites_only: bool = False,
        zh_only: bool = False,
        sort: str = "score",
        limit: int = 0,
    ) -> list[dict]:
        if section == "favorites":
            rows = self.favorite_stations()
        elif section == "recent":
            rows = self.recent_stations()
        elif section == "top":
            rows = self.most_played()
        elif section == "custom":
            rows = list(self.custom)
        elif section == "zh":
            rows = [s for s in self.all_stations() if s.get("zh")]
        elif section == "all":
            rows = list(self.all_stations())
        else:
            rows = [s for s in self.all_stations() if s.get("genre") == section]

        if favorites_only and section not in ("favorites", "recent", "top"):
            rows = [s for s in rows if s.get("url") in self.favorites]
        if zh_only and section != "zh":
            rows = [s for s in rows if s.get("zh")]
        if country != "all":
            rows = [s for s in rows if (s.get("country") or "") == country]
        if min_bitrate > 0:
            rows = [s for s in rows if int(s.get("bitrate") or 0) >= min_bitrate]
        if text:
            terms = [t for t in text.lower().split() if t]
            if terms:
                def match(s: dict) -> bool:
                    hay = " ".join([
                        s.get("name", ""), s.get("country", ""), s.get("tags", ""),
                        s.get("language", ""), s.get("state", ""), s.get("genre", ""),
                    ]).lower()
                    return all(t in hay for t in terms)
                rows = [s for s in rows if match(s)]

        if section not in ("recent", "top"):
            rows = self._sort(rows, sort)
        if limit:
            rows = rows[:limit]
        return rows

    @staticmethod
    def _sort(rows: list[dict], sort: str) -> list[dict]:
        if sort == "votes":
            return sorted(rows, key=lambda s: (-int(s.get("votes") or 0), -float(s.get("score") or 0)))
        if sort == "bitrate":
            return sorted(rows, key=lambda s: (-int(s.get("bitrate") or 0), -float(s.get("score") or 0)))
        if sort == "name":
            return sorted(rows, key=lambda s: (s.get("name") or "").lower())
        if sort == "country":
            return sorted(rows, key=lambda s: ((s.get("country") or "zz"), -float(s.get("score") or 0)))
        if sort == "genre":
            return sorted(rows, key=lambda s: ((s.get("genre") or "zz"), -float(s.get("score") or 0)))
        return sorted(rows, key=lambda s: -float(s.get("score") or 0))

    def stats(self) -> dict:
        return {
            "total": len(self.all_stations()),
            "builtin": len(self.stations),
            "custom": len(self.custom),
            "favorites": len(self.favorites),
            "history": len(self.history),
            "countries": len({s.get("country") for s in self.stations if s.get("country")}),
            "generated": self.meta.get("generated", ""),
        }

    # ------------------------------------------------------------------ #
    #  proxy
    # ------------------------------------------------------------------ #
    def proxy_config(self):
        """Build the effective ProxyConfig from stored settings."""
        from .proxy import MODE_SYSTEM, ProxyConfig, system_proxy

        mode = self.get("proxy_mode", MODE_SYSTEM)
        if mode == MODE_SYSTEM:
            cfg = system_proxy()
            cfg.mode = MODE_SYSTEM
            return cfg
        return ProxyConfig(
            mode=mode,
            scheme=self.get("proxy_scheme", "http"),
            host=self.get("proxy_host", ""),
            port=int(self.get("proxy_port", 0) or 0),
            username=self.get("proxy_username", ""),
            password=self.get("proxy_password", ""),
        )

    def set_proxy_config(self, cfg) -> None:
        """Persist a ProxyConfig. System mode stores only the mode."""
        self.settings["proxy_mode"] = cfg.mode
        if cfg.mode == "custom":
            self.settings["proxy_scheme"] = cfg.scheme
            self.settings["proxy_host"] = cfg.host
            self.settings["proxy_port"] = int(cfg.port or 0)
            self.settings["proxy_username"] = cfg.username
            self.settings["proxy_password"] = cfg.password
        self.save()
        self.setting_changed.emit("proxy_mode", cfg.mode)

    def export_favorites(self, path: str) -> int:
        lines = ["#EXTM3U", f"# Broadcast favourites - {time.strftime('%Y-%m-%d %H:%M')}"]
        count = 0
        for s in self.favorite_stations():
            lines.append(f"#EXTINF:-1,{s.get('name', '')} ({s.get('country', '')})")
            lines.append(s.get("url", ""))
            count += 1
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        return count
