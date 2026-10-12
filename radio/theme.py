"""Design tokens and the global stylesheet.

Visual language: precision audio-hardware console. Near-neutral graphite
surfaces, hairline strokes, a single cyan accent, condensed uppercase
micro-labels, monospaced numerics. No gradients-as-decoration, no glassmorphism,
no rounded-everything.
"""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QFontDatabase

# --------------------------------------------------------------------------- #
#  Palette
# --------------------------------------------------------------------------- #
BG_APP = "#0e1013"
BG_TITLEBAR = "#141619"
BG_SIDEBAR = "#121417"
BG_PANEL = "#171a1e"
BG_PANEL_ALT = "#1c2025"
BG_ROW_HOVER = "#1e2228"
BG_ROW_SEL = "#12303a"
BG_INPUT = "#0b0d10"
BG_TOOLBAR = "#15181c"

STROKE = "#272c33"
STROKE_SOFT = "#1f242a"
STROKE_STRONG = "#39414a"

TEXT = "#e7eaee"
TEXT_DIM = "#98a1ab"
TEXT_MUTED = "#666f79"
TEXT_FAINT = "#4a525b"

ACCENT = "#00c2d7"
ACCENT_DIM = "#0b8a99"
ACCENT_SOFT = "#0e3d45"
REC = "#ff4438"
REC_DIM = "#7a231d"
WARN = "#f5a524"
GOOD = "#3ddc84"

# --------------------------------------------------------------------------- #
#  Metrics
# --------------------------------------------------------------------------- #
RADIUS = 3
RADIUS_LG = 5
TITLEBAR_H = 42
STATUSBAR_H = 26
SIDEBAR_W = 208
RIGHTPANEL_W = 344
ROW_H = 44

# --------------------------------------------------------------------------- #
#  Fonts
# --------------------------------------------------------------------------- #
_UI_STACK = [
    "Segoe UI Variable Text",
    "Segoe UI Variable Display",
    "Segoe UI",
    "Inter",
    "Noto Sans",
    "Arial",
]
_MONO_STACK = ["Cascadia Mono", "Consolas", "JetBrains Mono", "DejaVu Sans Mono", "Courier New"]


def _first_available(stack: list[str]) -> str:
    families = set(QFontDatabase.families())
    for name in stack:
        if name in families:
            return name
    return stack[-1]


_ui_family: str | None = None
_mono_family: str | None = None


def ui_family() -> str:
    global _ui_family
    if _ui_family is None:
        _ui_family = _first_available(_UI_STACK)
    return _ui_family


def mono_family() -> str:
    global _mono_family
    if _mono_family is None:
        _mono_family = _first_available(_MONO_STACK)
    return _mono_family


def font(size: int = 9, weight: int = 400, mono: bool = False, spacing: float = 0.0) -> QFont:
    f = QFont(mono_family() if mono else ui_family())
    f.setPixelSize(size)
    f.setWeight(QFont.Weight(weight))
    if spacing:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    return f


def label_font(size: int = 8, weight: int = 700, spacing: float = 1.4) -> QFont:
    """Condensed uppercase micro-label used for section headers."""
    return font(size, weight, spacing=spacing)


def c(hex_color: str, alpha: float = 1.0) -> QColor:
    col = QColor(hex_color)
    if alpha < 1.0:
        col.setAlphaF(alpha)
    return col


# --------------------------------------------------------------------------- #
#  Stylesheet
# --------------------------------------------------------------------------- #
def stylesheet() -> str:
    uf = ui_family()
    mf = mono_family()
    return f"""
* {{
    font-family: "{uf}";
    outline: none;
}}
QWidget#Root {{
    background: {BG_APP};
    border: 1px solid {STROKE_STRONG};
}}
QWidget#Root[chrome="flush"] {{
    border: none;
}}
QToolTip {{
    background: {BG_PANEL_ALT};
    color: {TEXT};
    border: 1px solid {STROKE_STRONG};
    padding: 5px 8px;
    font-size: 11px;
}}

/* ---------------------------------------------------------------- titlebar */
QWidget#TitleBar {{
    background: {BG_TITLEBAR};
    border-bottom: 1px solid {STROKE};
}}
QLabel#BrandMark {{
    color: {ACCENT};
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 2.6px;
}}
QLabel#BrandSub {{
    color: {TEXT_FAINT};
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 1.2px;
}}
QPushButton#WinBtn {{
    background: transparent;
    border: none;
    color: {TEXT_DIM};
    font-size: 13px;
}}
QPushButton#WinBtn:hover {{
    background: {BG_ROW_HOVER};
    color: {TEXT};
}}
QPushButton#WinBtnClose:hover {{
    background: #c0392b;
    color: #ffffff;
}}

/* ---------------------------------------------------------------- sidebar */
QWidget#Sidebar {{
    background: {BG_SIDEBAR};
    border-right: 1px solid {STROKE};
}}
QLabel#SideHeader {{
    color: {TEXT_FAINT};
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 1.5px;
    padding: 0px 4px;
}}
QListWidget#NavList {{
    background: transparent;
    border: none;
    outline: none;
}}
QListWidget#NavList::item {{
    height: 26px;
    padding-left: 8px;
    color: {TEXT_DIM};
    border-left: 2px solid transparent;
    font-size: 12px;
}}
QListWidget#NavList::item:hover {{
    background: {BG_ROW_HOVER};
    color: {TEXT};
}}
QListWidget#NavList::item:selected {{
    background: {BG_ROW_SEL};
    color: {TEXT};
    border-left: 2px solid {ACCENT};
    font-weight: 600;
}}
QScrollArea#SideScroll {{
    background: transparent;
    border: none;
}}
QScrollArea#SideScroll > QWidget > QWidget {{
    background: transparent;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 9px;
    margin: 0px;
}}
QScrollBar::handle:vertical {{
    background: #333a42;
    min-height: 28px;
    border-radius: 4px;
}}
QScrollBar::handle:vertical:hover {{
    background: #47505a;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 9px;
}}
QScrollBar::handle:horizontal {{
    background: #333a42;
    min-width: 28px;
    border-radius: 4px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}

/* ---------------------------------------------------------------- toolbar */
QWidget#Toolbar {{
    background: {BG_TOOLBAR};
    border-bottom: 1px solid {STROKE};
}}
QLineEdit#Search {{
    background: {BG_INPUT};
    border: 1px solid {STROKE};
    border-radius: {RADIUS}px;
    padding: 0px 8px 0px 26px;
    color: {TEXT};
    font-size: 12px;
    selection-background-color: {ACCENT_DIM};
}}
QLineEdit#Search:focus {{
    border: 1px solid {ACCENT_DIM};
}}
QLabel#CountLabel {{
    color: {TEXT_MUTED};
    font-size: 11px;
    font-family: "{mf}";
}}
QWidget#PagerBar {{
    background: {BG_TOOLBAR};
}}
QWidget#PagerCluster {{
    background: {BG_INPUT};
    border: 1px solid {STROKE};
    border-radius: {RADIUS}px;
}}
QPushButton#PagerBtn {{
    background: transparent;
    border: none;
    border-radius: 0px;
}}
QPushButton#PagerBtn:hover {{
    background: {BG_ROW_HOVER};
}}
QPushButton#PagerBtn:pressed {{
    background: {BG_ROW_SEL};
}}
QPushButton#PagerBtn:disabled {{
    background: transparent;
}}
QLabel#PagerReadout {{
    color: {TEXT};
    background: transparent;
    font-size: 11px;
    font-weight: 600;
    font-family: "{mf}";
}}
QLabel#PagerRange {{
    color: {TEXT_MUTED};
    font-size: 10px;
    font-family: "{mf}";
    letter-spacing: 0.4px;
}}
QLabel#PagerMicro {{
    color: {TEXT_FAINT};
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 1.4px;
}}
QComboBox#PagerField {{
    background: {BG_INPUT};
    border: 1px solid {STROKE};
    border-radius: {RADIUS}px;
    padding: 0px 4px 0px 8px;
    color: {TEXT};
    font-size: 11px;
    font-family: "{mf}";
    font-weight: 600;
}}
QComboBox#PagerField:hover {{
    border-color: {STROKE_STRONG};
}}
QComboBox#PagerField:focus {{
    border-color: {ACCENT_DIM};
}}
QComboBox#PagerField::drop-down {{
    border: none;
    width: 16px;
}}
QComboBox#PagerField QAbstractItemView {{
    background: {BG_PANEL_ALT};
    border: 1px solid {STROKE_STRONG};
    color: {TEXT};
    selection-background-color: {BG_ROW_SEL};
    outline: none;
    font-family: "{mf}";
}}

/* ---------------------------------------------------------------- chips */
QPushButton#Chip {{
    background: {BG_PANEL_ALT};
    border: 1px solid {STROKE};
    border-radius: {RADIUS}px;
    color: {TEXT_DIM};
    font-size: 11px;
    padding: 0px 10px;
    height: 24px;
}}
QPushButton#Chip:hover {{
    border-color: {STROKE_STRONG};
    color: {TEXT};
}}
QPushButton#Chip:checked {{
    background: {ACCENT_SOFT};
    border-color: {ACCENT_DIM};
    color: {ACCENT};
    font-weight: 600;
}}

/* ---------------------------------------------------------------- station table */
QTreeView#StationTable {{
    background: {BG_PANEL};
    alternate-background-color: {BG_PANEL_ALT};
    border: none;
    color: {TEXT};
    font-size: 12px;
    selection-background-color: {BG_ROW_SEL};
    selection-color: {TEXT};
    show-decoration-selected: 1;
}}
QTreeView#StationTable::item {{
    border-bottom: 1px solid {STROKE_SOFT};
    padding: 0px 6px;
}}
QTreeView#StationTable::item:hover {{
    background: {BG_ROW_HOVER};
}}
QTreeView#StationTable::item:selected {{
    background: {BG_ROW_SEL};
    color: {TEXT};
}}
QHeaderView::section {{
    background: {BG_TOOLBAR};
    color: {TEXT_FAINT};
    border: none;
    border-bottom: 1px solid {STROKE};
    border-right: 1px solid {STROKE_SOFT};
    padding: 0px 6px;
    height: 26px;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.8px;
}}
QHeaderView::section:hover {{
    color: {TEXT_DIM};
}}
QHeaderView::down-arrow, QHeaderView::up-arrow {{
    width: 0px;
    height: 0px;
}}

/* ---------------------------------------------------------------- right panel */
QWidget#RightPanel {{
    background: {BG_SIDEBAR};
    border-left: 1px solid {STROKE};
}}
QWidget#ArtFrame {{
    background: {BG_PANEL};
    border: 1px solid {STROKE};
    border-radius: {RADIUS_LG}px;
}}
QLabel#NpTitle {{
    color: {TEXT};
    font-size: 19px;
    font-weight: 700;
}}
QLabel#NpSub {{
    color: {TEXT_DIM};
    font-size: 12px;
}}
QLabel#NpMeta {{
    color: {ACCENT};
    font-size: 12px;
    font-weight: 600;
}}
QLabel#CardLabel {{
    color: {TEXT_FAINT};
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 1.4px;
}}
QLabel#CardValue {{
    color: {TEXT};
    font-size: 11px;
    font-family: "{mf}";
}}
QLabel#CardValueDim {{
    color: {TEXT_MUTED};
    font-size: 11px;
    font-family: "{mf}";
}}
QFrame#HLine {{
    background: {STROKE};
    border: none;
    max-height: 1px;
}}

/* ---------------------------------------------------------------- buttons */
QPushButton#Transport {{
    background: {BG_PANEL_ALT};
    border: 1px solid {STROKE};
    border-radius: {RADIUS}px;
}}
QPushButton#Transport:hover {{
    background: #242932;
    border-color: {STROKE_STRONG};
}}
QPushButton#Transport:pressed {{
    background: #14181d;
}}
QPushButton#Transport:disabled {{
    background: #14171a;
    border-color: {STROKE_SOFT};
}}
QPushButton#PlayBtn {{
    background: {ACCENT};
    border: 1px solid {ACCENT};
    border-radius: {RADIUS_LG}px;
}}
QPushButton#PlayBtn:hover {{
    background: #16d3e8;
    border-color: #16d3e8;
}}
QPushButton#PlayBtn:pressed {{
    background: {ACCENT_DIM};
    border-color: {ACCENT_DIM};
}}
QPushButton#RecBtn {{
    background: {BG_PANEL_ALT};
    border: 1px solid {STROKE};
    border-radius: {RADIUS}px;
    color: {TEXT_DIM};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1.0px;
}}
QPushButton#RecBtn:hover {{
    border-color: {STROKE_STRONG};
    color: {TEXT};
}}
QPushButton#RecBtn:checked {{
    background: #2a1512;
    border-color: {REC};
    color: {REC};
}}
QPushButton#Flat {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: {RADIUS}px;
    color: {TEXT_DIM};
    font-size: 11px;
    padding: 0px 8px;
    height: 24px;
}}
QPushButton#Flat:hover {{
    background: {BG_ROW_HOVER};
    color: {TEXT};
}}
QPushButton#Flat:checked {{
    background: {ACCENT_SOFT};
    color: {ACCENT};
}}
QPushButton#IconBtn {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: {RADIUS}px;
}}
QPushButton#IconBtn:hover {{
    background: {BG_ROW_HOVER};
}}
QPushButton#IconBtn:checked {{
    background: {ACCENT_SOFT};
}}
QPushButton#Primary {{
    background: {ACCENT};
    border: none;
    border-radius: {RADIUS}px;
    color: #06222a;
    font-size: 12px;
    font-weight: 700;
    padding: 0px 14px;
    height: 28px;
}}
QPushButton#Primary:hover {{
    background: #16d3e8;
}}
QPushButton#Ghost {{
    background: {BG_PANEL_ALT};
    border: 1px solid {STROKE};
    border-radius: {RADIUS}px;
    color: {TEXT_DIM};
    font-size: 12px;
    padding: 0px 14px;
    height: 28px;
}}
QPushButton#Ghost:hover {{
    border-color: {STROKE_STRONG};
    color: {TEXT};
}}

/* ---------------------------------------------------------------- sliders */
QSlider::groove:horizontal {{
    height: 4px;
    background: #2b3138;
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: {ACCENT};
    border-radius: 2px;
}}
QSlider::add-page:horizontal {{
    background: #2b3138;
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: #e7eaee;
    width: 10px;
    height: 10px;
    margin: -4px 0px;
    border-radius: 5px;
}}
QSlider::handle:horizontal:hover {{
    background: #ffffff;
}}
QSlider#VolumeSlider::sub-page:horizontal {{
    background: {TEXT_DIM};
}}

/* ---------------------------------------------------------------- list/panel bits */
QListWidget#SimpleList {{
    background: {BG_PANEL};
    border: 1px solid {STROKE};
    border-radius: {RADIUS}px;
    color: {TEXT_DIM};
    font-size: 12px;
}}
QListWidget#SimpleList::item {{
    height: 30px;
    padding-left: 8px;
    border-bottom: 1px solid {STROKE_SOFT};
}}
QListWidget#SimpleList::item:hover {{
    background: {BG_ROW_HOVER};
    color: {TEXT};
}}
QListWidget#SimpleList::item:selected {{
    background: {BG_ROW_SEL};
    color: {TEXT};
}}

/* ---------------------------------------------------------------- statusbar */
QWidget#StatusBar {{
    background: {BG_TITLEBAR};
    border-top: 1px solid {STROKE};
}}
QLabel#StatusText {{
    color: {TEXT_MUTED};
    font-size: 11px;
    font-family: "{mf}";
}}
QLabel#StatusTextLive {{
    color: {ACCENT};
    font-size: 11px;
    font-family: "{mf}";
}}

/* ---------------------------------------------------------------- dialogs */
QDialog {{
    background: {BG_APP};
}}
QLabel#DlgTitle {{
    color: {TEXT};
    font-size: 15px;
    font-weight: 700;
}}
QLabel#DlgBody {{
    color: {TEXT_DIM};
    font-size: 12px;
}}
QLineEdit#Field, QComboBox#Field {{
    background: {BG_INPUT};
    border: 1px solid {STROKE};
    border-radius: {RADIUS}px;
    padding: 0px 8px;
    color: {TEXT};
    font-size: 12px;
    height: 28px;
    selection-background-color: {ACCENT_DIM};
}}
QLineEdit#Field:focus, QComboBox#Field:focus {{
    border-color: {ACCENT_DIM};
}}
QComboBox#Field::drop-down {{
    border: none;
    width: 20px;
}}
QComboBox#Field QAbstractItemView {{
    background: {BG_PANEL_ALT};
    border: 1px solid {STROKE_STRONG};
    color: {TEXT};
    selection-background-color: {BG_ROW_SEL};
    outline: none;
}}
QCheckBox {{
    color: {TEXT_DIM};
    font-size: 12px;
    spacing: 7px;
}}
QCheckBox::indicator {{
    width: 14px;
    height: 14px;
    border: 1px solid {STROKE_STRONG};
    border-radius: 2px;
    background: {BG_INPUT};
}}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
}}
QRadioButton {{
    color: {TEXT_DIM};
    font-size: 12px;
    spacing: 7px;
}}
QRadioButton::indicator {{
    width: 14px;
    height: 14px;
    border: 1px solid {STROKE_STRONG};
    border-radius: 7px;
    background: {BG_INPUT};
}}
QRadioButton::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
}}
QMenu {{
    background: {BG_PANEL_ALT};
    border: 1px solid {STROKE_STRONG};
    color: {TEXT};
    font-size: 12px;
    padding: 4px;
}}
QMenu::item {{
    padding: 5px 22px 5px 10px;
    border-radius: 2px;
}}
QMenu::item:selected {{
    background: {BG_ROW_SEL};
}}
QMenu::separator {{
    height: 1px;
    background: {STROKE};
    margin: 4px 6px;
}}
"""
