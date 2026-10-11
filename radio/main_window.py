"""Main application window."""
from __future__ import annotations

import os
import time

from PySide6.QtCore import QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QGuiApplication, QKeySequence, QPainter
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QMenu,
    QPushButton, QScrollArea, QSizeGrip, QSizePolicy, QVBoxLayout, QWidget,
)

from . import icons, paths, theme
from .dialogs import (
    ExportDialog, PreferencesDialog, ReportDialog, StationDialog, confirm, info,
)
from .library import SORT_MODES, Library
from .player import PlayerEngine
from .table import GENRE_ZH, StationModel, StationTable
from .widgets import (
    ArtTile, Chip, ElideLabel, IconButton, KeyValueRow, LevelMeter, NavItem,
    PlayingIndicator, SearchField, SpectrumWidget, StatRow, TextButton, TransportButton,
    VolumeControl, hline, section_label, vline,
)


class MiniBar(QWidget):
    """Thin horizontal capacity bar used in the status strip."""

    def __init__(self, parent=None, color: str = theme.ACCENT):
        super().__init__(parent)
        self._value = 0.0
        self._color = color
        self.setFixedSize(52, 6)

    def set_value(self, value: float) -> None:
        self._value = max(0.0, min(1.0, float(value)))
        self.update()

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.c("#252b32"))
        p.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), 3, 3)
        if self._value > 0.01:
            p.setBrush(theme.c(self._color))
            p.drawRoundedRect(QRectF(0, 0, self.width() * self._value, self.height()), 3, 3)
        p.end()


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("Root")
        self.setWindowTitle(f"{paths.APP_TITLE} — 网络收音机")
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setMinimumSize(1180, 700)

        self.library = Library(self)
        self.engine = PlayerEngine(self.library.settings, self)
        self.engine.set_proxy(self.library.proxy_config())

        self._section = self.library.get("genre", "all")
        self._sleep_deadline = 0.0
        self._play_started = 0.0
        self._resize_edge = None
        self._resize_origin = None
        self._record_started = 0.0

        self._build()
        self._wire()
        self._restore_geometry()

        self._apply_filters(select_last=True)
        self._refresh_sidebar_counts()
        self._update_status()
        self._update_proxy_indicator()
        self._restore_last_station()

        self._clock = QTimer(self)
        self._clock.setInterval(500)
        self._clock.timeout.connect(self._tick)
        self._clock.start()

    # ================================================================== #
    #  construction
    # ================================================================== #
    def _build(self) -> None:
        from .widgets import TitleBar

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.titlebar = TitleBar(self)
        root.addWidget(self.titlebar)
        root.addWidget(hline(theme.STROKE))

        body = QWidget()
        body_lay = QHBoxLayout(body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(0)

        body_lay.addWidget(self._build_sidebar())
        body_lay.addWidget(vline(theme.STROKE))
        body_lay.addWidget(self._build_center(), 1)
        body_lay.addWidget(vline(theme.STROKE))
        body_lay.addWidget(self._build_right_panel())
        root.addWidget(body, 1)

        root.addWidget(hline(theme.STROKE))
        root.addWidget(self._build_statusbar())

    # ---------------------------------------------------------------- sidebar
    def _build_sidebar(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("Sidebar")
        panel.setFixedWidth(theme.SIDEBAR_W)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 12, 0, 8)
        lay.setSpacing(4)

        lay.addWidget(self._padded(section_label("浏览 / BROWSE")))
        lay.addSpacing(2)

        self._nav_items: dict[str, NavItem] = {}
        browse = [
            ("all", "全部电台", "list"),
            ("top", "常听电台", "star"),
            ("recent", "最近播放", "clock"),
            ("favorites", "我的收藏", "heart"),
            ("custom", "自建电台", "edit"),
            ("zh", "中文电台", "globe"),
        ]
        for key, label, icon_name in browse:
            item = NavItem(key, label, -1, icon_name)
            item.clicked.connect(self._on_nav)
            self._nav_items[key] = item
            lay.addWidget(item)

        lay.addSpacing(10)
        lay.addWidget(self._padded(section_label("类型 / GENRES")))
        lay.addSpacing(2)

        scroll = QScrollArea()
        scroll.setObjectName("SideScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        inner_lay = QVBoxLayout(inner)
        inner_lay.setContentsMargins(0, 0, 0, 0)
        inner_lay.setSpacing(0)
        for key, zh, en, count in self.library.genre_options():
            item = NavItem(key, zh, count)
            item.clicked.connect(self._on_nav)
            self._nav_items[key] = item
            inner_lay.addWidget(item)
        inner_lay.addStretch(1)
        scroll.setWidget(inner)
        lay.addWidget(scroll, 1)

        lay.addSpacing(6)
        lay.addWidget(self._padded(section_label("地区 / REGION")))
        self._country_combo = QComboBox()
        self._country_combo.setObjectName("Field")
        self._country_combo.addItem("全部地区", "all")
        for name, count in self.library.country_options():
            self._country_combo.addItem(f"{name}  ({count})", name)
        self._country_combo.setFixedHeight(26)
        self._country_combo.setFont(theme.font(11, 400))
        self._country_combo.currentIndexChanged.connect(self._on_country)
        wrap = QWidget()
        wl = QHBoxLayout(wrap)
        wl.setContentsMargins(10, 0, 10, 0)
        wl.addWidget(self._country_combo)
        lay.addWidget(wrap)

        lay.addSpacing(4)
        self._quality_chip = Chip("高音质 ≥128k", "只显示码率 128 kbps 以上的电台")
        self._quality_chip.toggled.connect(self._on_quality)
        qw = QWidget()
        ql = QHBoxLayout(qw)
        ql.setContentsMargins(10, 0, 10, 0)
        ql.addWidget(self._quality_chip)
        lay.addWidget(qw)
        return panel

    @staticmethod
    def _padded(widget: QWidget) -> QWidget:
        wrap = QWidget()
        lay = QHBoxLayout(wrap)
        lay.setContentsMargins(12, 0, 12, 0)
        lay.addWidget(widget)
        return wrap

    # ---------------------------------------------------------------- center
    def _build_center(self) -> QWidget:
        center = QWidget()
        center.setObjectName("Center")
        center.setStyleSheet(f"QWidget#Center {{ background: {theme.BG_APP}; }}")
        lay = QVBoxLayout(center)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        lay.addWidget(self._build_toolbar())
        lay.addWidget(hline(theme.STROKE))

        self.model = StationModel(self.library, self)
        self.table = StationTable(self.model, self)
        lay.addWidget(self.table, 1)

        lay.addWidget(hline(theme.STROKE))
        lay.addWidget(self._build_nowbar())
        return center

    def _build_toolbar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("Toolbar")
        bar.setFixedHeight(46)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(12, 0, 12, 0)
        lay.setSpacing(8)

        self.search = SearchField()
        self.search.setFixedWidth(280)
        lay.addWidget(self.search)

        self._fav_chip = Chip("仅收藏", "只显示已收藏的电台")
        self._fav_chip.toggled.connect(self._on_fav_filter)
        lay.addWidget(self._fav_chip)

        self._zh_chip = Chip("仅中文", "只显示中文电台")
        self._zh_chip.toggled.connect(self._on_zh_filter)
        lay.addWidget(self._zh_chip)

        self._sort_combo = QComboBox()
        self._sort_combo.setObjectName("Field")
        self._sort_combo.setFixedHeight(26)
        self._sort_combo.setFixedWidth(122)
        self._sort_combo.setFont(theme.font(11, 400))
        for key, label in SORT_MODES:
            self._sort_combo.addItem(label, key)
        idx = self._sort_combo.findData(self.library.get("sort", "score"))
        self._sort_combo.setCurrentIndex(max(0, idx))
        self._sort_combo.currentIndexChanged.connect(self._on_sort)
        lay.addWidget(self._sort_combo)

        lay.addStretch(1)

        self._count_label = QLabel("")
        self._count_label.setObjectName("CountLabel")
        self._count_label.setFont(theme.font(11, 500, mono=True))
        lay.addWidget(self._count_label)

        lay.addSpacing(4)
        self._export_btn = IconButton("download", 28, 15, "导出收藏为 M3U")
        self._export_btn.clicked.connect(self._export_favorites)
        lay.addWidget(self._export_btn)

        self._refresh_btn = IconButton("refresh", 28, 15, "重新载入列表")
        self._refresh_btn.clicked.connect(lambda: self._apply_filters())
        lay.addWidget(self._refresh_btn)

        self._settings_btn = IconButton("sliders", 28, 15, "设置")
        self._settings_btn.clicked.connect(self._open_preferences)
        lay.addWidget(self._settings_btn)
        return bar

    def _build_nowbar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("Toolbar")
        bar.setFixedHeight(84)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(12)

        self._mini_art = ArtTile(56, self)
        lay.addWidget(self._mini_art)

        info_col = QVBoxLayout()
        info_col.setContentsMargins(0, 0, 0, 0)
        info_col.setSpacing(1)
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(7)
        self._mini_indicator = PlayingIndicator(self, 3)
        title_row.addWidget(self._mini_indicator)
        self._mini_title = ElideLabel("未选择电台")
        self._mini_title.setFont(theme.font(14, 700))
        self._mini_title.setStyleSheet(f"color: {theme.TEXT};")
        title_row.addWidget(self._mini_title, 1)
        info_col.addLayout(title_row)

        self._mini_meta = ElideLabel("从左侧列表中选择一个电台开始收听")
        self._mini_meta.setFont(theme.font(11, 400))
        self._mini_meta.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        info_col.addWidget(self._mini_meta)

        self._mini_track = ElideLabel("")
        self._mini_track.setFont(theme.font(11, 500))
        self._mini_track.setStyleSheet(f"color: {theme.ACCENT};")
        info_col.addWidget(self._mini_track)
        lay.addLayout(info_col, 1)

        # level meter + timer
        meter_col = QVBoxLayout()
        meter_col.setContentsMargins(0, 0, 0, 0)
        meter_col.setSpacing(3)
        meter_caption = QLabel("输出电平")
        meter_caption.setObjectName("CardLabel")
        meter_caption.setFont(theme.label_font(8, 700, 1.1))
        meter_col.addWidget(meter_caption)
        self._level = LevelMeter(self)
        self._level.setFixedWidth(96)
        meter_col.addWidget(self._level)
        self._mini_time = QLabel("00:00:00")
        self._mini_time.setFont(theme.font(10, 500, mono=True))
        self._mini_time.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-family: '{theme.mono_family()}';")
        meter_col.addWidget(self._mini_time)
        lay.addLayout(meter_col)

        lay.addWidget(vline(theme.STROKE, 1))

        # transport
        self._btn_prev = TransportButton("prev", 34, 15, "上一个电台  (Ctrl+Left)")
        self._btn_play = TransportButton("play", 44, 20, "播放 / 暂停  (Space)", primary=True)
        self._btn_stop = TransportButton("stop", 34, 15, "停止")
        self._btn_next = TransportButton("next", 34, 15, "下一个电台  (Ctrl+Right)")
        self._btn_rec = TransportButton("record", 34, 15, "录制当前电台")
        self._btn_rec.setCheckable(True)
        for b in (self._btn_prev, self._btn_play, self._btn_stop, self._btn_next):
            lay.addWidget(b)
        lay.addSpacing(4)
        lay.addWidget(self._btn_rec)

        lay.addWidget(vline(theme.STROKE, 1))

        self._volume = VolumeControl(int(self.library.get("volume", 72)))
        self._volume.setFixedWidth(158)
        lay.addWidget(self._volume)
        return bar

    # ------------------------------------------------------------ right panel
    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("RightPanel")
        panel.setFixedWidth(theme.RIGHTPANEL_W)
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setObjectName("SideScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        inner = QWidget()
        inner.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)

        # ---- hero ------------------------------------------------------
        self._art = ArtTile(134, self)
        art_wrap = QWidget()
        aw = QHBoxLayout(art_wrap)
        aw.setContentsMargins(0, 0, 0, 0)
        aw.addStretch(1)
        aw.addWidget(self._art)
        aw.addStretch(1)
        lay.addWidget(art_wrap)

        self._np_title = ElideLabel("未选择电台")
        self._np_title.setObjectName("NpTitle")
        self._np_title.setFont(theme.font(16, 700))
        self._np_title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(self._np_title)

        self._np_sub = ElideLabel("")
        self._np_sub.setObjectName("NpSub")
        self._np_sub.setFont(theme.font(11, 400))
        self._np_sub.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(self._np_sub)

        self._np_track = ElideLabel("")
        self._np_track.setObjectName("NpMeta")
        self._np_track.setFont(theme.font(11, 600))
        self._np_track.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(self._np_track)

        # ---- spectrum --------------------------------------------------
        lay.addWidget(hline(theme.STROKE_SOFT))
        lay.addWidget(section_label("频谱 / SPECTRUM"))
        self._spectrum = SpectrumWidget(40, self)
        self._spectrum.setFixedHeight(72)
        lay.addWidget(self._spectrum)

        # ---- quality ---------------------------------------------------
        lay.addWidget(hline(theme.STROKE_SOFT))
        lay.addWidget(section_label("音质 / QUALITY"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        self._q_codec = StatRow("编码", "--")
        self._q_bitrate = StatRow("标称码率", "--")
        self._q_measured = StatRow("实测码率", "--")
        self._q_sample = StatRow("采样率", "--")
        self._q_channels = StatRow("声道", "--")
        self._q_buffer = StatRow("缓冲", "--")
        grid.addWidget(self._q_codec, 0, 0)
        grid.addWidget(self._q_bitrate, 0, 1)
        grid.addWidget(self._q_measured, 1, 0)
        grid.addWidget(self._q_sample, 1, 1)
        grid.addWidget(self._q_channels, 2, 0)
        grid.addWidget(self._q_buffer, 2, 1)
        lay.addLayout(grid)

        # ---- station info ----------------------------------------------
        lay.addWidget(hline(theme.STROKE_SOFT))
        lay.addWidget(section_label("电台信息 / STATION"))
        self._info_rows: dict[str, KeyValueRow] = {}
        for key in ("国家", "地区", "语言", "类型", "标签", "投票", "播放次数"):
            row = KeyValueRow(key, "--")
            self._info_rows[key] = row
            lay.addWidget(row)

        # ---- recording -------------------------------------------------
        lay.addWidget(hline(theme.STROKE_SOFT))
        lay.addWidget(section_label("录制 / RECORDING"))
        rec_row = QWidget()
        rl = QHBoxLayout(rec_row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(8)
        self._rec_button = QPushButton("开始录制")
        self._rec_button.setObjectName("RecBtn")
        self._rec_button.setCheckable(True)
        self._rec_button.setFixedHeight(28)
        self._rec_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._rec_button.clicked.connect(self._toggle_record)
        rl.addWidget(self._rec_button, 1)
        self._rec_folder_btn = IconButton("folder", 28, 15, "打开录音目录")
        self._rec_folder_btn.clicked.connect(self._open_recordings)
        rl.addWidget(self._rec_folder_btn)
        lay.addWidget(rec_row)

        self._rec_status = ElideLabel("未在录制")
        self._rec_status.setFont(theme.font(10, 400, mono=True))
        self._rec_status.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-family: '{theme.mono_family()}';")
        lay.addWidget(self._rec_status)

        # ---- actions ---------------------------------------------------
        lay.addWidget(hline(theme.STROKE_SOFT))
        lay.addWidget(section_label("操作 / ACTIONS"))
        acts = QGridLayout()
        acts.setHorizontalSpacing(8)
        acts.setVerticalSpacing(8)
        self._act_fav = TextButton("收藏", "heart")
        self._act_fav.clicked.connect(self._toggle_favorite_current)
        self._act_copy = TextButton("复制地址", "external")
        self._act_copy.clicked.connect(self._copy_url)
        self._act_report = TextButton("诊断", "signal")
        self._act_report.clicked.connect(self._open_report)
        self._act_home = TextButton("官网", "globe")
        self._act_home.clicked.connect(self._open_homepage)
        acts.addWidget(self._act_fav, 0, 0)
        acts.addWidget(self._act_copy, 0, 1)
        acts.addWidget(self._act_report, 1, 0)
        acts.addWidget(self._act_home, 1, 1)
        lay.addLayout(acts)

        lay.addStretch(1)
        scroll.setWidget(inner)
        outer.addWidget(scroll)
        return panel

    # -------------------------------------------------------------- statusbar
    def _build_statusbar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("StatusBar")
        bar.setFixedHeight(theme.STATUSBAR_H)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(12, 0, 12, 0)
        lay.setSpacing(10)

        self._status_text = QLabel("就绪")
        self._status_text.setObjectName("StatusText")
        self._status_text.setFont(theme.font(11, 400, mono=True))
        lay.addWidget(self._status_text)

        lay.addSpacing(8)
        self._proxy_btn = QPushButton()
        self._proxy_btn.setObjectName("Flat")
        self._proxy_btn.setFixedHeight(18)
        self._proxy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._proxy_btn.setIconSize(QSize(12, 12))
        self._proxy_btn.setFont(theme.font(10, 500, mono=True))
        self._proxy_btn.clicked.connect(self._open_preferences)
        lay.addWidget(self._proxy_btn)

        lay.addStretch(1)

        self._status_center = QLabel("")
        self._status_center.setObjectName("StatusText")
        self._status_center.setFont(theme.font(11, 400, mono=True))
        lay.addWidget(self._status_center)

        lay.addStretch(1)

        cap = QLabel("缓冲")
        cap.setObjectName("CardLabel")
        cap.setFont(theme.label_font(8, 700, 1.0))
        lay.addWidget(cap)
        self._buffer_bar = MiniBar(self)
        lay.addWidget(self._buffer_bar)

        self._status_right = QLabel("--")
        self._status_right.setObjectName("StatusText")
        self._status_right.setFont(theme.font(11, 400, mono=True))
        self._status_right.setMinimumWidth(190)
        self._status_right.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(self._status_right)

        grip = QSizeGrip(bar)
        grip.setFixedSize(14, 14)
        lay.addWidget(grip, 0, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)
        return bar

    # ================================================================== #
    #  wiring
    # ================================================================== #
    def _wire(self) -> None:
        self.titlebar.minimize_clicked.connect(self.showMinimized)
        self.titlebar.maximize_clicked.connect(self._toggle_max)
        self.titlebar.close_clicked.connect(self.close)

        self.search.textChanged.connect(lambda _: self._apply_filters())
        self.table.station_activated.connect(self._on_station_activated)
        self.table.favorite_toggled.connect(self._on_favorite_toggled)
        self.table.context_requested.connect(self._on_context_menu)
        self.table.selection_changed.connect(self._on_selection_changed)

        self._btn_play.clicked.connect(self._on_play_clicked)
        self._btn_stop.clicked.connect(self._on_stop_clicked)
        self._btn_prev.clicked.connect(lambda: self._step(-1))
        self._btn_next.clicked.connect(lambda: self._step(1))
        self._btn_rec.clicked.connect(self._toggle_record)

        self._volume.volume_changed.connect(self._on_volume)
        self._volume.mute_toggled.connect(self._on_mute)

        self.engine.state_changed.connect(self._on_state)
        self.engine.station_changed.connect(self._on_station_changed)
        self.engine.metadata_changed.connect(self._on_metadata)
        self.engine.error_occurred.connect(self._on_error)
        self.engine.level_changed.connect(self._level.set_level)
        self.engine.spectrum_changed.connect(self._spectrum.set_values)
        self.engine.stats_changed.connect(self._on_stats)
        self.engine.recording_changed.connect(self._on_recording_changed)
        self.engine.buffer_health.connect(self._buffer_bar.set_value)
        self.engine.icy_name_changed.connect(self._on_icy_name)

        self.library.favorites_changed.connect(self._on_favorites_changed)
        self.library.custom_changed.connect(lambda: self._apply_filters())
        self.library.history_changed.connect(self._refresh_sidebar_counts)

        # shortcuts
        from PySide6.QtGui import QShortcut

        QShortcut(QKeySequence("Space"), self, self._on_play_clicked)
        QShortcut(QKeySequence("Ctrl+F"), self, self.search.setFocus)
        QShortcut(QKeySequence("Ctrl+Left"), self, lambda: self._step(-1))
        QShortcut(QKeySequence("Ctrl+Right"), self, lambda: self._step(1))
        QShortcut(QKeySequence("Ctrl+R"), self, self._toggle_record)
        QShortcut(QKeySequence("Ctrl+E"), self, self._export_favorites)
        QShortcut(QKeySequence("Ctrl+Comma"), self, self._open_preferences)
        QShortcut(QKeySequence("Ctrl+N"), self, self._add_station)
        QShortcut(QKeySequence("Ctrl+D"), self, self._toggle_favorite_current)
        QShortcut(QKeySequence("Escape"), self, self._on_escape)
        QShortcut(QKeySequence("F11"), self, self._toggle_max)

    # ================================================================== #
    #  data flow
    # ================================================================== #
    def _apply_filters(self, select_last: bool = False) -> None:
        text = self.search.text().strip()
        country = self._country_combo.currentData() or "all"
        min_br = 128 if self._quality_chip.isChecked() else int(self.library.get("min_bitrate", 0))
        rows = self.library.query(
            section=self._section,
            text=text,
            country=country,
            min_bitrate=min_br,
            favorites_only=self._fav_chip.isChecked(),
            zh_only=self._zh_chip.isChecked(),
            sort=self._sort_combo.currentData() or "score",
        )
        self.model.set_rows(rows)
        self.model.set_playing(
            self.engine.station.get("url", "") if self.engine.state != "idle" else "",
            self.engine.station.get("url", "") if self.engine.state == "connecting" else "",
        )
        self._count_label.setText(f"{len(rows)} / {len(self.library.all_stations())}")
        self._update_status()

        if select_last and self.engine.station:
            self.table.select_url(self.engine.station.get("url", ""))
        elif rows and not self.table.currentIndex().isValid():
            self.table.setCurrentIndex(self.model.index(0, 1))
        if self.engine.station:
            self._show_station_detail(self.engine.station)

    def _refresh_sidebar_counts(self) -> None:
        counts = {
            "all": len(self.library.stations) + len(self.library.custom),
            "favorites": len(self.library.favorites),
            "recent": len(self.library.history),
            "top": len(self.library.most_played()),
            "custom": len(self.library.custom),
            "zh": sum(1 for s in self.library.all_stations() if s.get("zh")),
        }
        for key, item in self._nav_items.items():
            if key in counts:
                item.set_count(counts[key])
        self._update_status()

    def _update_status(self) -> None:
        stats = self.library.stats()
        self._status_center.setText(
            f"电台库 {stats['builtin']} · 自建 {stats['custom']} · "
            f"收藏 {stats['favorites']} · 覆盖 {stats['countries']} 个国家/地区"
        )

    def _update_proxy_indicator(self) -> None:
        """Keep the active proxy visible; unreachable stations are often a proxy issue."""
        cfg = self.engine.proxy
        if cfg is None or cfg.mode == "none":
            self._proxy_btn.setText("  代理：关闭")
            self._proxy_btn.setIcon(icons.icon("globe", 12, theme.TEXT_MUTED))
            self._proxy_btn.setToolTip("当前不使用代理，点击打开网络设置")
            self._proxy_btn.setStyleSheet(
                f"color: {theme.TEXT_MUTED}; font-family: '{theme.mono_family()}'; font-size: 10px;")
        elif cfg.usable:
            self._proxy_btn.setText(f"  代理：{cfg.host}:{cfg.port}")
            self._proxy_btn.setIcon(icons.icon("globe", 12, theme.ACCENT))
            self._proxy_btn.setToolTip(f"{cfg.describe()}\n点击打开网络设置")
            self._proxy_btn.setStyleSheet(
                f"color: {theme.ACCENT}; font-family: '{theme.mono_family()}'; font-size: 10px;")
        else:
            self._proxy_btn.setText("  代理：未检测到")
            self._proxy_btn.setIcon(icons.icon("globe", 12, theme.WARN))
            self._proxy_btn.setToolTip(
                (cfg.unresolved or "未检测到系统代理") + "\n点击打开网络设置"
            )
            self._proxy_btn.setStyleSheet(
                f"color: {theme.WARN}; font-family: '{theme.mono_family()}'; font-size: 10px;")

    # ================================================================== #
    #  selection / detail
    # ================================================================== #
    def _restore_last_station(self) -> None:
        """Re-show (and optionally resume) the station from the previous session."""
        url = self.library.get("last_station", "")
        if not url:
            return
        station = self.library.find(url)
        if not station:
            return
        self._show_station_detail(station)
        self._mini_title.setText(station.get("name", ""))
        self.table.select_url(url)
        if self.library.get("resume_last", True):
            QTimer.singleShot(400, lambda: self.engine.tune(station))

    def _on_selection_changed(self, station) -> None:
        if station:
            self._show_station_detail(station)

    def _show_station_detail(self, station: dict) -> None:
        name = station.get("name", "")
        country = station.get("country", "") or "未知"
        genre = GENRE_ZH.get(station.get("genre", ""), station.get("genre", ""))
        self._np_title.setText(name)
        self._np_sub.setText(" · ".join([b for b in [country, genre] if b]))
        self._art.set_station(name, (station.get("codec") or "").upper())

        self._info_rows["国家"].set_value(country)
        self._info_rows["地区"].set_value(station.get("state", "") or "--")
        self._info_rows["语言"].set_value(station.get("language", "") or "--")
        self._info_rows["类型"].set_value(genre)
        self._info_rows["标签"].set_value(station.get("tags", "") or "--")
        votes = int(station.get("votes") or 0)
        self._info_rows["投票"].set_value(str(votes) if votes else "--")
        count = self.library.play_count(station.get("url", ""))
        self._info_rows["播放次数"].set_value(str(count) if count else "0")

        br = int(station.get("bitrate") or 0)
        self._q_codec.set_value((station.get("codec") or "--").upper())
        self._q_bitrate.set_value(f"{br} kbps" if br else "未知")
        sr = station.get("sample_rate") or ""
        self._q_sample.set_value(f"{sr} Hz" if sr else "--")
        ch = int(station.get("channels") or 0)
        self._q_channels.set_value({1: "单声道", 2: "立体声"}.get(ch, "--"))

        url = station.get("url", "")
        fav = self.library.is_favorite(url)
        self._act_fav.setText("已收藏" if fav else "收藏")
        self._act_fav.setIcon(icons.icon("heart_filled" if fav else "heart", 14,
                                         theme.REC if fav else theme.TEXT_DIM))
        self._act_home.setEnabled(bool(station.get("homepage")))
        self._mini_art.set_station(name, (station.get("codec") or "").upper())

    def _current_station(self) -> dict | None:
        idx = self.table.currentIndex()
        if idx.isValid():
            station = self.model.station_at(idx.row())
            if station:
                return station
        return self.engine.station or None

    # ================================================================== #
    #  playback
    # ================================================================== #
    def _on_station_activated(self, station: dict) -> None:
        if station.get("url") == self.engine.station.get("url") and self.engine.state == "playing":
            self.engine.stop()
            return
        self.engine.tune(station)

    def _on_play_clicked(self) -> None:
        if self.engine.state in ("playing", "buffering", "connecting"):
            self.engine.stop()
            return
        station = self._current_station()
        if station:
            self.engine.tune(station)
        else:
            info(self, "没有选中电台", "请先在列表中选择一个电台。")

    def _on_stop_clicked(self) -> None:
        self.engine.stop()

    def _step(self, delta: int) -> None:
        rows = self.model.rows
        if not rows:
            return
        current = self.model.row_of(self.engine.station.get("url", ""))
        if current < 0:
            current = self.table.currentIndex().row()
        nxt = (current + delta) % len(rows)
        station = self.model.station_at(nxt)
        if station:
            self.table.setCurrentIndex(self.model.index(nxt, 1))
            self.table.scrollTo(self.model.index(nxt, 1))
            self.engine.tune(station)

    def _on_volume(self, value: int) -> None:
        self.engine.set_volume(value)
        self.library.set("volume", value, save=False)

    def _on_mute(self, muted: bool) -> None:
        self.engine.set_muted(muted)
        self.library.set("muted", muted, save=False)

    # -- engine callbacks --------------------------------------------------
    def _on_state(self, state: str) -> None:
        labels = {
            "idle": "已停止", "connecting": "正在连接 …", "buffering": "缓冲中 …",
            "playing": "播放中", "error": "播放错误",
        }
        self._status_text.setText(labels.get(state, state))
        obj = "StatusTextLive" if state == "playing" else "StatusText"
        self._status_text.setObjectName(obj)
        self._status_text.setStyleSheet(
            f"color: {theme.ACCENT if state == 'playing' else theme.TEXT_MUTED};"
            f"font-family: '{theme.mono_family()}'; font-size: 11px;"
        )
        self._status_text.style().unpolish(self._status_text)
        self._status_text.style().polish(self._status_text)

        playing = state in ("playing", "buffering")
        self._btn_play.set_icon_name("pause" if playing else "play")
        self._mini_indicator.set_active(state == "playing")
        self.titlebar.set_now_playing(self._mini_track.fullText(), state == "playing")
        self._spectrum.set_active(state == "playing")
        self._art.set_playing(state == "playing")

        if state == "idle":
            # Keep the last station on screen when playback stops: an operator
            # needs to see what was tuned, not a blank panel.
            if self.engine.station:
                self._mini_track.setText("")
                self._np_track.setText("")
            else:
                self._mini_title.setText("未选择电台")
                self._mini_meta.setText("从左侧列表中选择一个电台开始收听")
                self._mini_track.setText("")
                self._np_track.setText("")
            self._mini_time.setText("00:00:00")
            self._q_measured.set_value("--")
            self._q_buffer.set_value("--")
            self._buffer_bar.set_value(0.0)
            self._status_right.setText("--")
            self.model.set_playing("", "")
        else:
            self.model.set_playing(
                self.engine.station.get("url", "") if state in ("playing", "buffering") else "",
                self.engine.station.get("url", "") if state == "connecting" else "",
            )

        if state == "playing" and self._play_started == 0.0:
            self._play_started = time.time()
            self._arm_sleep_timer()

    def _on_station_changed(self, station: dict) -> None:
        self._show_station_detail(station)
        self.library.set("last_station", station.get("url", ""), save=False)
        self._mini_title.setText(station.get("name", ""))
        bits = []
        if station.get("country"):
            bits.append(station["country"])
        if station.get("genre"):
            bits.append(GENRE_ZH.get(station["genre"], station["genre"]))
        if station.get("codec"):
            bits.append((station["codec"] or "").upper())
        if station.get("bitrate"):
            bits.append(f"{station['bitrate']} kbps")
        self._mini_meta.setText(" · ".join(bits))
        self.titlebar.set_codec(f"{station.get('codec', '')} {station.get('bitrate', '')}k".strip())
        self.library.record_play(station)
        self._refresh_sidebar_counts()
        self.model.refresh_row(station.get("url", ""))

    def _on_metadata(self, title: str) -> None:
        self._mini_track.setText(title)
        self._np_track.setText(title)
        self.titlebar.set_now_playing(title, self.engine.state == "playing")

    def _on_icy_name(self, name: str) -> None:
        if name and not self._mini_track.fullText():
            self._mini_meta.setText(name)

    def _on_error(self, message: str) -> None:
        self._status_text.setText(message)
        self._status_text.setStyleSheet(
            f"color: {theme.REC}; font-family: '{theme.mono_family()}'; font-size: 11px;")
        self._mini_track.setText(message)
        self._np_track.setText(message)

    def _on_stats(self, stats: dict) -> None:
        kbps = stats.get("kbps", 0.0)
        self._q_measured.set_value(f"{kbps:.0f} kbps" if kbps else "--")
        rate = int(stats.get("encoded_rate") or 0)
        if rate:
            self._q_sample.set_value(f"{rate} Hz")
        ch = int(stats.get("encoded_channels") or 0)
        if ch:
            self._q_channels.set_value({1: "单声道", 2: "立体声"}.get(ch, f"{ch} 声道"))
        buf = stats.get("buffer", 0)
        self._q_buffer.set_value(f"{buf/1024:.0f} KB")
        dropped = stats.get("dropped", 0)
        elapsed = stats.get("elapsed", 0.0)
        self._mini_time.setText(
            f"{int(elapsed//3600):02d}:{int(elapsed%3600//60):02d}:{int(elapsed%60):02d}")
        self._status_right.setText(
            f"{kbps:6.0f} kbps   缓冲 {buf/1024:5.0f} KB   "
            f"丢帧 {dropped/1024:4.0f} KB"
        )

    def _on_favorites_changed(self) -> None:
        self._refresh_sidebar_counts()
        if self._section == "favorites":
            self._apply_filters()
        station = self._current_station()
        if station:
            self._show_station_detail(station)
        self.table.viewport().update()

    # ================================================================== #
    #  favourites / stations
    # ================================================================== #
    def _on_favorite_toggled(self, url: str) -> None:
        self.library.toggle_favorite(url)
        self.model.refresh_row(url)
        self.table.viewport().update()

    def _toggle_favorite_current(self) -> None:
        station = self._current_station()
        if not station:
            return
        self._on_favorite_toggled(station.get("url", ""))
        self._show_station_detail(station)

    def _copy_url(self) -> None:
        station = self._current_station()
        if station:
            QApplication.clipboard().setText(station.get("url", ""))
            self._status_text.setText("已复制流地址")

    def _open_homepage(self) -> None:
        station = self._current_station()
        if station and station.get("homepage"):
            from PySide6.QtGui import QDesktopServices
            from PySide6.QtCore import QUrl
            QDesktopServices.openUrl(QUrl(station["homepage"]))

    def _open_recordings(self) -> None:
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        path = self.library.get("recordings_dir") or paths.default_recordings_dir()
        os.makedirs(path, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _open_report(self) -> None:
        station = self._current_station()
        if station:
            ReportDialog(self, station, self.engine).exec()

    def _add_station(self) -> None:
        dlg = StationDialog(self, None, self.engine)
        if dlg.exec() and dlg.result_station:
            station = self.library.add_custom(dlg.result_station)
            self._section = "custom"
            self._set_nav("custom")
            self._apply_filters()
            self.table.select_url(station.get("url", ""))

    def _edit_station(self, station: dict) -> None:
        dlg = StationDialog(self, station, self.engine)
        if dlg.exec() and dlg.result_station:
            self.library.update_custom(station.get("id", ""), dlg.result_station)
            self._apply_filters()

    def _delete_station(self, station: dict) -> None:
        if confirm(self, "删除电台", f"确定要从自建电台中删除「{station.get('name', '')}」吗？", danger=True):
            self.library.remove_custom(station.get("id", ""))
            self._apply_filters()

    def _export_favorites(self) -> None:
        if not self.library.favorites:
            info(self, "没有收藏", "请先收藏一些电台，再导出播放列表。")
            return
        dlg = ExportDialog(self, self.library)
        if dlg.exec() and dlg.path:
            self._status_text.setText(f"已导出到 {dlg.path}")

    def _open_preferences(self) -> None:
        dlg = PreferencesDialog(self, self.library, self.engine)
        if dlg.exec():
            dlg.apply()
            self.engine.set_proxy(self.library.proxy_config())
            self._update_proxy_indicator()
            self._fav_chip.setChecked(bool(self.library.get("favorites_only", False)))
            self._zh_chip.setChecked(bool(self.library.get("zh_only", False)))
            self._spectrum.setVisible(bool(self.library.get("show_spectrum", True)))
            idx = self._sort_combo.findData(self.library.get("sort", "score"))
            if idx >= 0:
                self._sort_combo.setCurrentIndex(idx)
            self._apply_filters()

    # ================================================================== #
    #  recording
    # ================================================================== #
    def _toggle_record(self) -> None:
        if self.engine.is_recording:
            path = self.engine.stop_recording()
            self._btn_rec.setChecked(False)
            self._rec_button.setChecked(False)
            if path:
                self._status_text.setText(f"录音已保存：{path}")
        else:
            if self.engine.state not in ("playing", "buffering"):
                info(self, "无法录制", "请先播放一个电台，再开始录制。")
                self._btn_rec.setChecked(False)
                self._rec_button.setChecked(False)
                return
            if self.engine.start_recording():
                self._record_started = time.time()
                self._btn_rec.setChecked(True)
                self._rec_button.setChecked(True)

    def _on_recording_changed(self, active: bool, path: str) -> None:
        self._btn_rec.setChecked(active)
        self._rec_button.setChecked(active)
        self._rec_button.setText("停止录制" if active else "开始录制")
        if active:
            name = os.path.basename(path) if path else ""
            self._rec_status.setText(f"录制中 · {name}")
            self._rec_status.setStyleSheet(
                f"color: {theme.REC}; font-family: '{theme.mono_family()}'; font-size: 10px;")
        else:
            self._record_started = 0.0
            if path:
                size = os.path.getsize(path) / 1048576 if os.path.exists(path) else 0
                self._rec_status.setText(f"已保存 · {os.path.basename(path)} · {size:.1f} MB")
                self._rec_status.setStyleSheet(
                    f"color: {theme.GOOD}; font-family: '{theme.mono_family()}'; font-size: 10px;")
            else:
                self._rec_status.setText("未在录制")
                self._rec_status.setStyleSheet(
                    f"color: {theme.TEXT_MUTED}; font-family: '{theme.mono_family()}'; font-size: 10px;")

    # ================================================================== #
    #  filters / nav
    # ================================================================== #
    def _on_nav(self, key: str) -> None:
        self._section = key
        self._set_nav(key)
        self.library.set("genre", key, save=False)
        self._apply_filters()

    def _set_nav(self, key: str) -> None:
        for nav_key, item in self._nav_items.items():
            item.set_selected(nav_key == key)

    def _on_country(self) -> None:
        self._apply_filters()

    def _on_quality(self) -> None:
        self._apply_filters()

    def _on_fav_filter(self) -> None:
        self.library.set("favorites_only", self._fav_chip.isChecked(), save=False)
        self._apply_filters()

    def _on_zh_filter(self) -> None:
        self.library.set("zh_only", self._zh_chip.isChecked(), save=False)
        self._apply_filters()

    def _on_sort(self) -> None:
        self.library.set("sort", self._sort_combo.currentData(), save=False)
        self._apply_filters()

    # ================================================================== #
    #  context menu
    # ================================================================== #
    def _on_context_menu(self, station, global_pos) -> None:
        if station is None:
            return
        menu = QMenu(self)
        menu.setStyleSheet(theme.stylesheet())
        url = station.get("url", "")

        act_play = QAction("播放", self)
        act_play.triggered.connect(lambda: self.engine.tune(station))
        menu.addAction(act_play)

        fav_label = "取消收藏" if self.library.is_favorite(url) else "加入收藏"
        act_fav = QAction(fav_label, self)
        act_fav.triggered.connect(lambda: self._on_favorite_toggled(url))
        menu.addAction(act_fav)

        act_copy = QAction("复制流地址", self)
        act_copy.triggered.connect(lambda: QApplication.clipboard().setText(url))
        menu.addAction(act_copy)

        if station.get("homepage"):
            act_home = QAction("打开官网", self)
            act_home.triggered.connect(lambda: self._open_homepage_for(station))
            menu.addAction(act_home)

        menu.addSeparator()
        act_report = QAction("连接诊断", self)
        act_report.triggered.connect(lambda: ReportDialog(self, station, self.engine).exec())
        menu.addAction(act_report)

        if station.get("custom"):
            menu.addSeparator()
            act_edit = QAction("编辑电台", self)
            act_edit.triggered.connect(lambda: self._edit_station(station))
            menu.addAction(act_edit)
            act_del = QAction("删除电台", self)
            act_del.triggered.connect(lambda: self._delete_station(station))
            menu.addAction(act_del)

        menu.exec(global_pos)

    def _open_homepage_for(self, station: dict) -> None:
        if station.get("homepage"):
            from PySide6.QtGui import QDesktopServices
            from PySide6.QtCore import QUrl
            QDesktopServices.openUrl(QUrl(station["homepage"]))

    # ================================================================== #
    #  sleep timer / clock
    # ================================================================== #
    def _arm_sleep_timer(self) -> None:
        minutes = int(self.library.get("sleep_minutes", 0) or 0)
        if minutes > 0 and self._play_started:
            self._sleep_deadline = self._play_started + minutes * 60
        else:
            self._sleep_deadline = 0.0

    def _tick(self) -> None:
        if self.engine.state == "playing" and self.engine.is_recording and self._record_started:
            elapsed = time.time() - self._record_started
            size = 0
            rec = getattr(self.engine, "_recorder", None)
            if rec is not None:
                size = rec.size
            self._rec_status.setText(
                f"录制中 · {int(elapsed//60):02d}:{int(elapsed%60):02d} · {size/1048576:.1f} MB")

        if self._sleep_deadline:
            remaining = self._sleep_deadline - time.time()
            if remaining <= 0:
                self._sleep_deadline = 0.0
                action = self.library.get("sleep_action", "stop")
                if action == "quit":
                    self.close()
                else:
                    self.engine.stop()
                    self._status_text.setText("定时器到时，已停止播放")
            elif self.engine.state == "playing":
                mins, secs = divmod(int(remaining), 60)
                self._status_text.setText(f"播放中 · 定时关闭 {mins:02d}:{secs:02d}")

        if self.engine.state == "idle":
            self._play_started = 0.0

    def _on_escape(self) -> None:
        if self.search.text():
            self.search.clear()
        else:
            self.search.clearFocus()

    # ================================================================== #
    #  window chrome
    # ================================================================== #
    def _toggle_max(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()
        self.titlebar.set_maximized(self.isMaximized())

    def changeEvent(self, event):  # noqa: N802
        super().changeEvent(event)
        if event.type() == event.Type.WindowStateChange:
            self.titlebar.set_maximized(self.isMaximized())

    def _restore_geometry(self) -> None:
        geo = self.library.get("window_geometry", "")
        restored = False
        if geo:
            parts = geo.split(",")
            if len(parts) == 4:
                try:
                    x, y, w, h = (int(p) for p in parts)
                    screens = QGuiApplication.screens()
                    if any(s.availableGeometry().intersects(
                            self.frameGeometry().adjusted(0, 0, 0, 0).translated(x, y))
                            for s in screens):
                        self.setGeometry(x, y, max(1180, w), max(700, h))
                        restored = True
                except ValueError:
                    restored = False
        if not restored:
            screen = QGuiApplication.primaryScreen().availableGeometry()
            w = min(1560, int(screen.width() * 0.86))
            h = min(940, int(screen.height() * 0.88))
            self.resize(w, h)
            self.move(screen.center().x() - w // 2, screen.center().y() - h // 2)

    def closeEvent(self, event):  # noqa: N802
        rect = self.normalGeometry() if self.isMaximized() else self.geometry()
        self.library.set(
            "window_geometry",
            f"{rect.x()},{rect.y()},{rect.width()},{rect.height()}",
            save=False,
        )
        if self.engine.is_recording:
            self.engine.stop_recording()
        self.engine.stop()
        self.library.save()
        super().closeEvent(event)

    # -- frameless resize --------------------------------------------------
    MARGIN = 6

    def _edge_at(self, pos) -> Qt.Edge | None:
        x, y, w, h = pos.x(), pos.y(), self.width(), self.height()
        m = self.MARGIN
        left, right = x <= m, x >= w - m
        top, bottom = y <= m, y >= h - m
        if top and left:
            return Qt.Edge.TopEdge | Qt.Edge.LeftEdge
        if top and right:
            return Qt.Edge.TopEdge | Qt.Edge.RightEdge
        if bottom and left:
            return Qt.Edge.BottomEdge | Qt.Edge.LeftEdge
        if bottom and right:
            return Qt.Edge.BottomEdge | Qt.Edge.RightEdge
        if left:
            return Qt.Edge.LeftEdge
        if right:
            return Qt.Edge.RightEdge
        if top:
            return Qt.Edge.TopEdge
        if bottom:
            return Qt.Edge.BottomEdge
        return None

    def _cursor_for(self, edge) -> Qt.CursorShape:
        if edge is None:
            return Qt.CursorShape.ArrowCursor
        if edge in (Qt.Edge.LeftEdge, Qt.Edge.RightEdge):
            return Qt.CursorShape.SizeHorCursor
        if edge in (Qt.Edge.TopEdge, Qt.Edge.BottomEdge):
            return Qt.CursorShape.SizeVerCursor
        if edge in (Qt.Edge.TopEdge | Qt.Edge.LeftEdge,
                    Qt.Edge.BottomEdge | Qt.Edge.RightEdge):
            return Qt.CursorShape.SizeFDiagCursor
        return Qt.CursorShape.SizeBDiagCursor

    def mouseMoveEvent(self, event):  # noqa: N802
        if self.isMaximized():
            self.setCursor(Qt.CursorShape.ArrowCursor)
            return
        edge = self._edge_at(event.position().toPoint())
        self.setCursor(self._cursor_for(edge))

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and not self.isMaximized():
            edge = self._edge_at(event.position().toPoint())
            if edge is not None:
                handle = self.windowHandle()
                if handle is not None:
                    handle.startSystemResize(edge)
                    event.accept()
                    return
        super().mousePressEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        self.setCursor(Qt.CursorShape.ArrowCursor)
        super().leaveEvent(event)
