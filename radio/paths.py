"""Application data locations."""
from __future__ import annotations

import os
import sys

APP_NAME = "NetworkRadio"
APP_TITLE = "BROADCAST"
APP_VERSION = "1.0.0"
APP_AUTHOR_QQ = "398511660"
APP_REPO = "https://github.com/martjay/network-radio"

_DATA_DIR: str | None = None


def _writable(path: str) -> bool:
    """True when `path` can be created and written to."""
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".write-test")
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("ok")
        os.remove(probe)
        return True
    except (OSError, PermissionError):
        return False


def _candidates() -> list[str]:
    home = os.path.expanduser("~")
    if os.name == "nt":
        roaming = os.environ.get("APPDATA") or os.path.join(home, "AppData", "Roaming")
        local = os.environ.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
        primary = [os.path.join(roaming, APP_NAME), os.path.join(local, APP_NAME)]
    elif sys.platform == "darwin":
        primary = [os.path.join(home, "Library", "Application Support", APP_NAME)]
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
        primary = [os.path.join(base, APP_NAME)]

    # A frozen build unpacks to a temporary directory that is wiped on exit, so
    # it must never be used for user data.
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        return primary + [os.path.join(exe_dir, "userdata"), os.path.join(home, f".{APP_NAME.lower()}")]

    package_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return primary + [
        os.path.join(home, f".{APP_NAME.lower()}"),
        os.path.join(package_root, "userdata"),
        os.path.join(os.path.dirname(package_root), "userdata"),
    ]


def app_dir() -> str:
    """Per-user writable data directory.

    Falls back through a list of candidates so the application still runs when
    the preferred location is not writable (locked-down machine, read-only
    install, or a restricted execution sandbox).
    """
    global _DATA_DIR
    if _DATA_DIR is not None:
        return _DATA_DIR
    for candidate in _candidates():
        if _writable(candidate):
            _DATA_DIR = candidate
            return _DATA_DIR
    import tempfile

    fallback = os.path.join(tempfile.gettempdir(), APP_NAME)
    os.makedirs(fallback, exist_ok=True)
    _DATA_DIR = fallback
    return _DATA_DIR


def user_file(name: str) -> str:
    return os.path.join(app_dir(), name)


def install_dir() -> str:
    """Folder that holds the executable (or the project root when run from source)."""
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def default_recordings_dir() -> str:
    """Where recordings go when no custom directory is configured.

    Always `<exe or project>/REC`, so a packaged build drops files next to
    the executable instead of under AppData.
    """
    return os.path.join(install_dir(), "REC")


def is_builtin_recordings_dir(path: str) -> bool:
    """True when `path` is empty or one of the historical default folders."""
    if not (path or "").strip():
        return True
    norm = os.path.normcase(os.path.abspath(path))
    aliases = (
        default_recordings_dir(),
        os.path.join(install_dir(), "Rec"),
        os.path.join(app_dir(), "recordings"),
    )
    return any(norm == os.path.normcase(os.path.abspath(item)) for item in aliases)


def recordings_dir(configured: str = "") -> str:
    """Resolve the recordings folder from a stored setting."""
    if is_builtin_recordings_dir(configured):
        return default_recordings_dir()
    return configured


def _resource_root() -> str:
    """Directory holding bundled read-only resources.

    Under PyInstaller the package is unpacked to a temporary directory
    (`sys._MEIPASS`), so the source-relative path no longer applies.
    """
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def bundled(name: str) -> str:
    """Path to a resource shipped with the application."""
    return os.path.join(_resource_root(), "assets", name)


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


USERDATA = "userdata.json"
SETTINGS = "settings.json"
