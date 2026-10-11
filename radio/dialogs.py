"""Dialogs: station editor, preferences, about, and the transport report."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QStackedWidget, QVBoxLayout, QWidget,
)

from . import icons, paths, theme
from .recorder import RECORD_FORMATS, ffmpeg_available, ffmpeg_path
from .widgets import ElideLabel, IconButton, KeyValueRow, TextButton, hline, vline

GENRE_CHOICES = [
    ("news", "新闻资讯"), ("classical", "古典音乐"), ("jazz", "爵士蓝调"),
    ("electronic", "电子舞曲"), ("chill", "氛围休闲"), ("rock", "摇滚金属"),
    ("pop", "流行金曲"), ("urban", "嘻哈节奏"), ("folk", "民谣乡村"),
    ("world", "世界拉丁"), ("oldies", "怀旧年代"), ("screen", "影视原声"),
    ("sport", "体育赛事"), ("culture", "文化谈话"), ("varied", "综合电台"),
]


class DialogBase(QDialog):
    """Frameless dialog with the application's own chrome."""

    def __init__(self, parent=None, title: str = "", width: int = 520, height: int = 0):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setModal(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setStyleSheet(theme.stylesheet())
        self._drag: object = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.frame = QWidget()
        self.frame.setObjectName("Root")
        self.frame.setStyleSheet(f"QWidget#Root {{ background: {theme.BG_APP}; border: 1px solid {theme.STROKE_STRONG}; }}")
        outer.addWidget(self.frame)

        root = QVBoxLayout(self.frame)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        bar = QWidget()
        bar.setObjectName("TitleBar")
        bar.setFixedHeight(40)
        bar_lay = QHBoxLayout(bar)
        bar_lay.setContentsMargins(14, 0, 6, 0)
        bar_lay.setSpacing(8)
        self._title = QLabel(title)
        self._title.setFont(theme.font(13, 700))
        self._title.setStyleSheet(f"color: {theme.TEXT};")
        bar_lay.addWidget(self._title)
        bar_lay.addStretch(1)
        close = QPushButton()
        close.setObjectName("WinBtn")
        close.setFixedSize(36, 34)
        close.setIcon(icons.icon("close", 12, theme.TEXT_DIM))
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.clicked.connect(self.reject)
        bar_lay.addWidget(close)
        root.addWidget(bar)
        root.addWidget(hline(theme.STROKE))

        self.body = QWidget()
        self.body_lay = QVBoxLayout(self.body)
        self.body_lay.setContentsMargins(18, 16, 18, 16)
        self.body_lay.setSpacing(12)
        root.addWidget(self.body, 1)

        root.addWidget(hline(theme.STROKE))
        self.footer = QWidget()
        self.footer.setObjectName("TitleBar")
        self.footer.setFixedHeight(52)
        self.footer_lay = QHBoxLayout(self.footer)
        self.footer_lay.setContentsMargins(14, 0, 14, 0)
        self.footer_lay.setSpacing(8)
        root.addWidget(self.footer)

        self.setFixedWidth(width)
        if height:
            self.setFixedHeight(height)
        bar.mousePressEvent = self._bar_press
        bar.mouseMoveEvent = self._bar_move

    def _bar_press(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def _bar_move(self, event):
        if self._drag is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag)

    def add_footer_stretch(self) -> None:
        self.footer_lay.addStretch(1)


# --------------------------------------------------------------------------- #
#  station editor
# --------------------------------------------------------------------------- #
class StationDialog(DialogBase):
    """Add or edit a user station, with a live connection test."""

    def __init__(self, parent=None, station: dict | None = None, engine=None):
        editing = bool(station and station.get("custom"))
        super().__init__(parent, "编辑电台" if editing else "添加电台", width=560)
        self.station = station or {}
        self.engine = engine
        self.result_station: dict | None = None
        self._test_thread: QThread | None = None

        form = QGridLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)
        form.setColumnStretch(1, 1)

        def field_label(text: str) -> QLabel:
            lab = QLabel(text)
            lab.setFont(theme.label_font(8, 700, 1.2))
            lab.setStyleSheet(f"color: {theme.TEXT_FAINT};")
            lab.setFixedWidth(66)
            lab.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            return lab

        self.name_edit = QLineEdit(self.station.get("name", ""))
        self.name_edit.setObjectName("Field")
        self.name_edit.setPlaceholderText("例如：Classic FM")
        self.url_edit = QLineEdit(self.station.get("url", ""))
        self.url_edit.setObjectName("Field")
        self.url_edit.setPlaceholderText("http:// 或 https:// 音频流地址")

        self.genre_combo = QComboBox()
        self.genre_combo.setObjectName("Field")
        for key, label in GENRE_CHOICES:
            self.genre_combo.addItem(label, key)
        idx = self.genre_combo.findData(self.station.get("genre", "varied"))
        self.genre_combo.setCurrentIndex(max(0, idx))

        self.country_edit = QLineEdit(self.station.get("country", ""))
        self.country_edit.setObjectName("Field")
        self.country_edit.setPlaceholderText("例如：英国")

        self.tags_edit = QLineEdit(self.station.get("tags", ""))
        self.tags_edit.setObjectName("Field")
        self.tags_edit.setPlaceholderText("以逗号分隔，用于搜索")

        rows = [
            ("名称", self.name_edit),
            ("流地址", self.url_edit),
            ("类型", self.genre_combo),
            ("地区", self.country_edit),
            ("标签", self.tags_edit),
        ]
        for i, (label, widget) in enumerate(rows):
            form.addWidget(field_label(label), i, 0)
            form.addWidget(widget, i, 1)
        self.body_lay.addLayout(form)

        # ---- test panel ------------------------------------------------
        test_box = QWidget()
        test_box.setObjectName("ArtFrame")
        test_box.setStyleSheet(
            f"QWidget#ArtFrame {{ background: {theme.BG_PANEL}; border: 1px solid {theme.STROKE};"
            f" border-radius: {theme.RADIUS}px; }}"
        )
        tb = QHBoxLayout(test_box)
        tb.setContentsMargins(12, 9, 12, 9)
        tb.setSpacing(10)
        self._test_icon = QLabel()
        self._test_icon.setPixmap(icons.pixmap("signal", 15, theme.TEXT_MUTED))
        self._test_icon.setFixedSize(15, 15)
        tb.addWidget(self._test_icon)
        self._test_label = QLabel("尚未测试。点击「测试连接」验证该地址是否可以播放。")
        self._test_label.setFont(theme.font(11, 400))
        self._test_label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        self._test_label.setWordWrap(True)
        tb.addWidget(self._test_label, 1)
        self.body_lay.addWidget(test_box)
        self.body_lay.addStretch(1)

        self._test_btn = TextButton("测试连接", "refresh")
        self._test_btn.clicked.connect(self._run_test)
        self.footer_lay.addWidget(self._test_btn)
        self.add_footer_stretch()
        cancel = TextButton("取消")
        cancel.clicked.connect(self.reject)
        self.footer_lay.addWidget(cancel)
        save = TextButton("保存", "", primary=True)
        save.clicked.connect(self._accept)
        self.footer_lay.addWidget(save)

    def _accept(self) -> None:
        name = self.name_edit.text().strip()
        url = self.url_edit.text().strip()
        if not name:
            self._warn("请填写电台名称。")
            return
        if not url.lower().startswith(("http://", "https://")):
            self._warn("流地址必须以 http:// 或 https:// 开头。")
            return
        self.result_station = {
            "name": name,
            "url": url,
            "genre": self.genre_combo.currentData(),
            "country": self.country_edit.text().strip() or "自定义",
            "tags": self.tags_edit.text().strip(),
        }
        self.accept()

    def _warn(self, text: str) -> None:
        self._test_label.setText(text)
        self._test_label.setStyleSheet(f"color: {theme.WARN};")
        self._test_icon.setPixmap(icons.pixmap("info", 15, theme.WARN))

    # -- connection test ---------------------------------------------------
    def _run_test(self) -> None:
        url = self.url_edit.text().strip()
        if not url.lower().startswith(("http://", "https://")):
            self._warn("请先填写有效的 http(s) 流地址。")
            return
        if self._test_thread is not None and self._test_thread.isRunning():
            return
        self._test_btn.setEnabled(False)
        self._test_label.setText("正在连接并读取音频数据 …")
        self._test_label.setStyleSheet(f"color: {theme.TEXT_DIM};")
        self._test_icon.setPixmap(icons.pixmap("refresh", 15, theme.ACCENT))

        class Tester(QThread):
            done = Signal(dict)

            def __init__(self, target: str, proxy=None):
                super().__init__()
                self.target = target
                self.proxy = proxy

            def run(self):
                from .net import probe
                self.done.emit(probe(self.target, timeout=12, proxy=self.proxy))

        self._test_thread = Tester(url, self.engine.proxy if self.engine else None)
        self._test_thread.done.connect(self._on_test_done)
        self._test_thread.start()

    def _on_test_done(self, result: dict) -> None:
        self._test_btn.setEnabled(True)
        if result.get("ok"):
            kbps = result.get("kbps", 0)
            self._test_icon.setPixmap(icons.pixmap("check", 15, theme.GOOD))
            self._test_label.setStyleSheet(f"color: {theme.GOOD};")
            extra = f"  现在播放：{result['now_playing']}" if result.get("now_playing") else ""
            self._test_label.setText(
                f"连接成功 · {result.get('content_type', '')} · 实测约 {kbps:.0f} kbps · "
                f"{result.get('seconds', 0):.1f}s{extra}"
            )
        else:
            self._test_icon.setPixmap(icons.pixmap("close", 15, theme.REC))
            self._test_label.setStyleSheet(f"color: {theme.REC};")
            self._test_label.setText(f"连接失败：{result.get('error', '未知错误')}")


# --------------------------------------------------------------------------- #
#  preferences
# --------------------------------------------------------------------------- #
class PreferencesDialog(DialogBase):
    PAGES = [("playback", "播放", "headphones"), ("network", "网络代理", "globe"),
             ("recording", "录制", "record_ring"),
             ("interface", "界面", "grid"), ("about", "关于", "info")]

    def __init__(self, parent, library, engine):
        super().__init__(parent, "设置", width=700, height=520)
        self.library = library
        self.engine = engine
        self._reset_done = False
        self._proxy_test_thread = None

        content = QHBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(0)

        # -- nav ---------------------------------------------------------
        nav_wrap = QWidget()
        nav_wrap.setFixedWidth(168)
        nav_wrap.setStyleSheet(f"background: {theme.BG_SIDEBAR};")
        nav_lay = QVBoxLayout(nav_wrap)
        nav_lay.setContentsMargins(0, 12, 0, 12)
        nav_lay.setSpacing(2)
        self.nav = QListWidget()
        self.nav.setObjectName("NavList")
        self.nav.setFrameShape(QFrame.Shape.NoFrame)
        for key, label, icon_name in self.PAGES:
            item = QListWidgetItem(icons.icon(icon_name, 14, theme.TEXT_MUTED), "  " + label)
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.nav.addItem(item)
        self.nav.setCurrentRow(0)
        self.nav.currentRowChanged.connect(self._switch)
        nav_lay.addWidget(self.nav, 1)
        content.addWidget(nav_wrap)
        content.addWidget(vline(theme.STROKE))

        # -- stack -------------------------------------------------------
        self.stack = QStackedWidget()
        self.stack.addWidget(self._page_playback())
        self.stack.addWidget(self._page_network())
        self.stack.addWidget(self._page_recording())
        self.stack.addWidget(self._page_interface())
        self.stack.addWidget(self._page_about())
        content.addWidget(self.stack, 1)
        self.body_lay.addLayout(content)

        self.add_footer_stretch()
        reset = TextButton("恢复默认", "refresh")
        reset.clicked.connect(self._reset)
        self.footer_lay.addWidget(reset)
        close = TextButton("完成", "", primary=True)
        close.clicked.connect(self.accept)
        self.footer_lay.addWidget(close)

    def _switch(self, row: int) -> None:
        if 0 <= row < self.stack.count():
            self.stack.setCurrentIndex(row)

    # -- helpers -----------------------------------------------------------
    def _page(self) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(20, 6, 20, 6)
        lay.setSpacing(10)
        return page, lay

    def _heading(self, text: str) -> QLabel:
        lab = QLabel(text)
        lab.setFont(theme.label_font(9, 700, 1.4))
        lab.setStyleSheet(f"color: {theme.TEXT_FAINT};")
        return lab

    def _hint(self, text: str) -> QLabel:
        lab = QLabel(text)
        lab.setFont(theme.font(11, 400))
        lab.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        lab.setWordWrap(True)
        return lab

    def _row(self, label: str, widget: QWidget, hint: str = "") -> QWidget:
        wrap = QWidget()
        lay = QHBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        lab = QLabel(label)
        lab.setFont(theme.font(12, 400))
        lab.setStyleSheet(f"color: {theme.TEXT};")
        lab.setFixedWidth(104)
        lay.addWidget(lab)
        lay.addWidget(widget, 1)
        if hint:
            h = QLabel(hint)
            h.setFont(theme.font(10, 400))
            h.setStyleSheet(f"color: {theme.TEXT_MUTED};")
            lay.addWidget(h)
        return wrap

    def _combo(self, items: list[tuple[str, object]], current) -> QComboBox:
        combo = QComboBox()
        combo.setObjectName("Field")
        for label, value in items:
            combo.addItem(label, value)
        idx = combo.findData(current)
        combo.setCurrentIndex(max(0, idx))
        return combo

    # -- pages -------------------------------------------------------------
    def _page_playback(self) -> QWidget:
        page, lay = self._page()
        lay.addWidget(self._heading("播放"))
        self._resume = QCheckBox("启动时恢复上次收听的电台")
        self._resume.setChecked(bool(self.library.get("resume_last", True)))
        lay.addWidget(self._resume)

        self._notify = QCheckBox("切换曲目时在标题栏显示提示")
        self._notify.setChecked(bool(self.library.get("notify_track", False)))
        lay.addWidget(self._notify)

        self._spectrum = QCheckBox("显示频谱分析")
        self._spectrum.setChecked(bool(self.library.get("show_spectrum", True)))
        lay.addWidget(self._spectrum)

        lay.addWidget(hline(theme.STROKE_SOFT))
        lay.addWidget(self._heading("定时关闭"))
        sleep_combo = self._combo([
            ("关闭", 0), ("15 分钟", 15), ("30 分钟", 30),
            ("45 分钟", 45), ("60 分钟", 60), ("90 分钟", 90), ("120 分钟", 120),
        ], int(self.library.get("sleep_minutes", 0)))
        sleep_combo.currentIndexChanged.connect(
            lambda: self.library.set("sleep_minutes", sleep_combo.currentData())
        )
        self._sleep_combo = sleep_combo
        lay.addWidget(self._row("定时关闭", sleep_combo))
        action = self._combo([("停止播放", "stop"), ("关闭程序", "quit")],
                             self.library.get("sleep_action", "stop"))
        action.currentIndexChanged.connect(
            lambda: self.library.set("sleep_action", action.currentData())
        )
        lay.addWidget(self._row("到时动作", action))
        lay.addWidget(self._hint("定时器在开始播放后计时，重新选台不会重置。"))
        lay.addStretch(1)
        return page

    # -- network / proxy ---------------------------------------------------
    def _page_network(self) -> QWidget:
        from .proxy import MODE_CUSTOM, MODE_NONE, MODE_SYSTEM

        page, lay = self._page()
        lay.addWidget(self._heading("代理模式"))

        self._proxy_mode = self._combo(
            [("自动（跟随系统代理）", MODE_SYSTEM),
             ("不使用代理", MODE_NONE),
             ("自定义代理", MODE_CUSTOM)],
            self.library.get("proxy_mode", MODE_SYSTEM),
        )
        self._proxy_mode.currentIndexChanged.connect(self._on_proxy_mode)
        lay.addWidget(self._row("模式", self._proxy_mode))

        # detected system proxy readout
        self._sys_label = QLabel("")
        self._sys_label.setFont(theme.font(10, 400, mono=True))
        self._sys_label.setWordWrap(True)
        lay.addWidget(self._sys_label)

        lay.addWidget(hline(theme.STROKE_SOFT))
        lay.addWidget(self._heading("自定义代理"))

        self._proxy_scheme = self._combo(
            [("HTTP / HTTPS", "http"), ("SOCKS5", "socks5")],
            self.library.get("proxy_scheme", "http"),
        )
        lay.addWidget(self._row("协议", self._proxy_scheme))

        addr_row = QWidget()
        al = QHBoxLayout(addr_row)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(8)
        self._proxy_host = QLineEdit(self.library.get("proxy_host", ""))
        self._proxy_host.setObjectName("Field")
        self._proxy_host.setPlaceholderText("127.0.0.1")
        self._proxy_port = QLineEdit(
            str(self.library.get("proxy_port") or "") if self.library.get("proxy_port") else ""
        )
        self._proxy_port.setObjectName("Field")
        self._proxy_port.setPlaceholderText("7890")
        self._proxy_port.setFixedWidth(76)
        self._proxy_port.setMaxLength(5)
        al.addWidget(self._proxy_host, 1)
        al.addWidget(QLabel(":"))
        al.addWidget(self._proxy_port)
        lay.addWidget(self._row("地址端口", addr_row))

        cred_row = QWidget()
        cl = QHBoxLayout(cred_row)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(8)
        self._proxy_user = QLineEdit(self.library.get("proxy_username", ""))
        self._proxy_user.setObjectName("Field")
        self._proxy_user.setPlaceholderText("用户名（可选）")
        self._proxy_pass = QLineEdit(self.library.get("proxy_password", ""))
        self._proxy_pass.setObjectName("Field")
        self._proxy_pass.setPlaceholderText("密码（可选）")
        self._proxy_pass.setEchoMode(QLineEdit.EchoMode.Password)
        cl.addWidget(self._proxy_user, 1)
        cl.addWidget(self._proxy_pass, 1)
        lay.addWidget(self._row("认证", cred_row))

        # ---- test panel ---------------------------------------------------
        test_box = QWidget()
        test_box.setObjectName("ArtFrame")
        test_box.setStyleSheet(
            f"QWidget#ArtFrame {{ background: {theme.BG_PANEL}; border: 1px solid {theme.STROKE};"
            f" border-radius: {theme.RADIUS}px; }}"
        )
        tb = QHBoxLayout(test_box)
        tb.setContentsMargins(12, 9, 12, 9)
        tb.setSpacing(10)
        self._proxy_icon = QLabel()
        self._proxy_icon.setPixmap(icons.pixmap("globe", 15, theme.TEXT_MUTED))
        self._proxy_icon.setFixedSize(15, 15)
        tb.addWidget(self._proxy_icon)
        self._proxy_status = QLabel("点击「测试代理」验证当前设置是否可以访问境外网络。")
        self._proxy_status.setFont(theme.font(11, 400))
        self._proxy_status.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        self._proxy_status.setWordWrap(True)
        tb.addWidget(self._proxy_status, 1)
        self._test_btn = TextButton("测试代理", "signal")
        self._test_btn.clicked.connect(self._run_proxy_test)
        tb.addWidget(self._test_btn)
        lay.addWidget(test_box)

        lay.addWidget(self._hint(
            "国内电台直连即可；部分境外电台在无代理时无法连接。"
            "代理设置对所有电台、HLS 流与连接测试立即生效，正在播放的电台需重新选台。"
            "本机地址（127.0.0.1）始终直连，不会经过代理。"
        ))

        self._on_proxy_mode()
        return page

    def _on_proxy_mode(self) -> None:
        from .proxy import MODE_CUSTOM, MODE_NONE, system_proxy

        mode = self._proxy_mode.currentData()
        custom = mode == MODE_CUSTOM
        for widget in (self._proxy_scheme, self._proxy_host, self._proxy_port,
                       self._proxy_user, self._proxy_pass):
            widget.setEnabled(custom)
        # the address row's children need explicit toggling too
        for parent in (self._proxy_host.parentWidget(), self._proxy_user.parentWidget()):
            if parent is not None:
                for child in parent.findChildren(QLineEdit):
                    child.setEnabled(custom)

        if mode == MODE_NONE:
            self._sys_label.setText("所有连接直连，不使用代理。")
            self._sys_label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        else:
            detected = system_proxy()
            if detected.usable:
                self._sys_label.setText(
                    f"已检测到系统代理：{detected.describe()}"
                    + (f"　（来源：{detected.source}）" if detected.source else "")
                )
                self._sys_label.setStyleSheet(f"color: {theme.GOOD};")
            else:
                text = detected.unresolved or "未检测到系统代理设置，将使用直连。"
                self._sys_label.setText(text)
                self._sys_label.setStyleSheet(f"color: {theme.WARN};")

    def _current_proxy(self):
        from .proxy import MODE_CUSTOM, ProxyConfig

        mode = self._proxy_mode.currentData()
        if mode != MODE_CUSTOM:
            return self.library.proxy_config() if mode == "system" else ProxyConfig(mode)
        try:
            port = int(self._proxy_port.text().strip() or 0)
        except ValueError:
            port = 0
        return ProxyConfig(
            mode=MODE_CUSTOM,
            scheme=self._proxy_scheme.currentData(),
            host=self._proxy_host.text().strip(),
            port=port,
            username=self._proxy_user.text().strip(),
            password=self._proxy_pass.text(),
        )

    def _run_proxy_test(self) -> None:
        from PySide6.QtCore import QThread, Signal

        cfg = self._current_proxy()
        if cfg.mode == "custom" and not cfg.usable:
            self._proxy_icon.setPixmap(icons.pixmap("info", 15, theme.WARN))
            self._proxy_status.setStyleSheet(f"color: {theme.WARN};")
            self._proxy_status.setText("请先填写有效的代理地址和端口（端口需为 1–65535）。")
            return

        self._test_btn.setEnabled(False)
        self._proxy_status.setStyleSheet(f"color: {theme.TEXT_DIM};")
        self._proxy_status.setText("正在测试连接 …")
        self._proxy_icon.setPixmap(icons.pixmap("refresh", 15, theme.ACCENT))

        class Tester(QThread):
            done = Signal(dict)

            def __init__(self, config):
                super().__init__()
                self.config = config

            def run(self):
                from .proxy import test_proxy
                self.done.emit(test_proxy(self.config, timeout=10))

        self._proxy_test_thread = Tester(cfg)
        self._proxy_test_thread.done.connect(self._on_proxy_test_done)
        self._proxy_test_thread.start()

    def _on_proxy_test_done(self, result: dict) -> None:
        self._test_btn.setEnabled(True)
        if result.get("ok"):
            self._proxy_icon.setPixmap(icons.pixmap("check", 15, theme.GOOD))
            self._proxy_status.setStyleSheet(f"color: {theme.GOOD};")
            self._proxy_status.setText(result["message"])
        else:
            self._proxy_icon.setPixmap(icons.pixmap("close", 15, theme.REC))
            self._proxy_status.setStyleSheet(f"color: {theme.REC};")
            self._proxy_status.setText(f"连接失败：{result.get('message', '未知错误')}")

    def _page_recording(self) -> QWidget:
        page, lay = self._page()
        lay.addWidget(self._heading("录制"))
        self._rec_dir = QLineEdit(self.library.get("recordings_dir") or paths.default_recordings_dir())
        self._rec_dir.setObjectName("Field")
        browse = IconButton("folder", 28, 15, "选择目录", color=theme.TEXT_DIM)
        browse.clicked.connect(self._choose_dir)
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(8)
        rl.addWidget(self._rec_dir, 1)
        rl.addWidget(browse)
        lay.addWidget(self._row("保存目录", row))

        fmt = self._combo([(label, key) for key, label in RECORD_FORMATS],
                          self.library.get("record_format", "mp3"))
        fmt.currentIndexChanged.connect(lambda: self.library.set("record_format", fmt.currentData()))
        lay.addWidget(self._row("格式", fmt))

        br = self._combo([("128 kbps", 128), ("192 kbps", 192), ("256 kbps", 256), ("320 kbps", 320)],
                         int(self.library.get("record_bitrate", 192)))
        br.currentIndexChanged.connect(lambda: self.library.set("record_bitrate", br.currentData()))
        lay.addWidget(self._row("转码码率", br, "仅对需要转码的格式生效"))

        self._auto_rec = QCheckBox("每次开始播放时自动录制")
        self._auto_rec.setChecked(bool(self.library.get("auto_record", False)))
        lay.addWidget(self._auto_rec)

        lay.addWidget(hline(theme.STROKE_SOFT))
        if ffmpeg_available():
            info = QLabel(f"ffmpeg：{ffmpeg_path()}")
            info.setFont(theme.font(10, 400, mono=True))
            info.setStyleSheet(f"color: {theme.GOOD};")
        else:
            info = QLabel("未找到 ffmpeg —— 录制功能不可用。请安装 ffmpeg 并加入 PATH。")
            info.setFont(theme.font(10, 400))
            info.setStyleSheet(f"color: {theme.WARN};")
            info.setWordWrap(True)
        lay.addWidget(info)
        lay.addWidget(self._hint(
            "MP3 / AAC 选项直接复制原始数据流，不做二次编码，音质与电台播出完全一致；"
            "选择其它格式时会按上面的码率转码。"
        ))
        lay.addStretch(1)
        return page

    def _page_interface(self) -> QWidget:
        page, lay = self._page()
        lay.addWidget(self._heading("界面"))
        sort = self._combo(
            [(label, key) for key, label in [
                ("推荐排序", "score"), ("听众投票", "votes"), ("音质优先", "bitrate"),
                ("名称 A-Z", "name"), ("国家地区", "country"), ("类型", "genre"),
            ]], self.library.get("sort", "score"))
        sort.currentIndexChanged.connect(lambda: self.library.set("sort", sort.currentData()))
        lay.addWidget(self._row("默认排序", sort))

        mb = self._combo([("不限", 0), ("≥ 64 kbps", 64), ("≥ 128 kbps", 128),
                          ("≥ 192 kbps", 192), ("≥ 256 kbps", 256)],
                         int(self.library.get("min_bitrate", 0)))
        mb.currentIndexChanged.connect(lambda: self.library.set("min_bitrate", mb.currentData()))
        lay.addWidget(self._row("最低码率", mb))

        self._zh = QCheckBox("只显示中文电台")
        self._zh.setChecked(bool(self.library.get("zh_only", False)))
        lay.addWidget(self._zh)
        self._fav = QCheckBox("只显示收藏的电台")
        self._fav.setChecked(bool(self.library.get("favorites_only", False)))
        lay.addWidget(self._fav)

        lay.addWidget(hline(theme.STROKE_SOFT))
        lay.addWidget(self._heading("托盘"))
        self._tray_close = QCheckBox("关闭窗口时最小化到托盘（不退出程序）")
        self._tray_close.setChecked(bool(self.library.get("close_to_tray", True)))
        lay.addWidget(self._tray_close)
        self._tray_notify = QCheckBox("最小化到托盘时显示提示")
        self._tray_notify.setChecked(bool(self.library.get("tray_notifications", True)))
        lay.addWidget(self._tray_notify)
        tray_note = self._hint(
            "托盘图标右键可播放 / 暂停、切换电台、录制、收藏或退出。"
            "双击托盘图标可恢复窗口。"
        )
        lay.addWidget(tray_note)
        lay.addStretch(1)
        return page

    def _page_about(self) -> QWidget:
        page, lay = self._page()
        lay.addWidget(self._heading("关于"))
        stats = self.library.stats()

        head = QWidget()
        hl = QHBoxLayout(head)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(12)
        mark = QLabel()
        mark.setPixmap(icons.brand_pixmap(44, theme.ACCENT))
        mark.setFixedSize(44, 44)
        hl.addWidget(mark)
        txt = QWidget()
        tl = QVBoxLayout(txt)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(2)
        t1 = QLabel(f"{paths.APP_TITLE}  {paths.APP_VERSION}")
        t1.setFont(theme.font(15, 700))
        t1.setStyleSheet(f"color: {theme.TEXT};")
        t2 = QLabel("网络收音机 · 桌面客户端")
        t2.setFont(theme.font(11, 400))
        t2.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        tl.addWidget(t1)
        tl.addWidget(t2)
        hl.addWidget(txt, 1)
        lay.addWidget(head)

        lay.addWidget(hline(theme.STROKE_SOFT))
        for key, value in [
            ("内置电台", f"{stats['builtin']} 个"),
            ("自建电台", f"{stats['custom']} 个"),
            ("收藏", f"{stats['favorites']} 个"),
            ("覆盖国家", f"{stats['countries']} 个"),
            ("电台库更新", stats.get("generated") or "--"),
        ]:
            lay.addWidget(KeyValueRow(key, value))

        lay.addWidget(hline(theme.STROKE_SOFT))

        # ---- author --------------------------------------------------------
        author_row = QWidget()
        ar = QHBoxLayout(author_row)
        ar.setContentsMargins(0, 0, 0, 0)
        ar.setSpacing(8)
        a_label = QLabel("作者")
        a_label.setObjectName("CardLabel")
        a_label.setFont(theme.label_font(8, 700, 1.1))
        a_label.setFixedWidth(76)
        a_value = ElideLabel(f"QQ  {paths.APP_AUTHOR_QQ}")
        a_value.setFont(theme.font(11, 500, mono=True))
        a_value.setStyleSheet(
            f"color: {theme.TEXT}; font-family: '{theme.mono_family()}'; font-size: 11px;")
        copy_qq = IconButton("list", 24, 13, "复制 QQ 号", color=theme.TEXT_DIM)
        copy_qq.clicked.connect(lambda: self._copy_qq(paths.APP_AUTHOR_QQ))
        ar.addWidget(a_label)
        ar.addWidget(a_value, 1)
        ar.addWidget(copy_qq)
        lay.addWidget(author_row)

        lay.addWidget(hline(theme.STROKE_SOFT))
        note = QLabel(
            "电台目录来自社区维护的公开电台数据库，每一条流都在收录时经过实际解码验证。"
            "广播内容版权归各电台所有，本程序仅提供播放与录制工具。"
        )
        note.setFont(theme.font(11, 400))
        note.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        note.setWordWrap(True)
        lay.addWidget(note)

        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(8)
        data_btn = TextButton("数据目录", "folder")
        data_btn.clicked.connect(lambda: self._open_path(paths.app_dir()))
        rec_btn = TextButton("录音目录", "folder")
        rec_btn.clicked.connect(lambda: self._open_path(self._recordings_dir()))
        repo_btn = TextButton("项目主页", "external")
        repo_btn.clicked.connect(lambda: self._open_url(paths.APP_REPO))
        rl.addWidget(data_btn)
        rl.addWidget(rec_btn)
        rl.addWidget(repo_btn)
        rl.addStretch(1)
        lay.addWidget(row)
        lay.addStretch(1)
        return page

    def _copy_qq(self, qq: str) -> None:
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(qq)
        self._flash("已复制作者 QQ 号")

    def _recordings_dir(self) -> str:
        """Recording directory, created if possible, with a writable fallback."""
        from .main_window import _ensure_dir

        wanted = self.library.get("recordings_dir") or paths.default_recordings_dir()
        if _ensure_dir(wanted):
            return wanted
        fallback = os.path.join(paths.app_dir(), "recordings")
        return fallback if _ensure_dir(fallback) else wanted

    def _open_path(self, path: str) -> None:
        from .main_window import _reveal_in_file_manager
        if _reveal_in_file_manager(path):
            self._flash("已打开目录")
        else:
            from PySide6.QtWidgets import QApplication
            QApplication.clipboard().setText(path)
            self._flash("无法打开，路径已复制")

    def _open_url(self, url: str) -> None:
        try:
            if not QDesktopServices.openUrl(QUrl(url)):
                from PySide6.QtWidgets import QApplication
                QApplication.clipboard().setText(url)
                self._flash("无法打开浏览器，链接已复制")
        except Exception:  # noqa: BLE001
            from PySide6.QtWidgets import QApplication
            QApplication.clipboard().setText(url)
            self._flash("无法打开浏览器，链接已复制")

    def _flash(self, text: str) -> None:
        """Temporary confirmation in the dialog footer."""
        if not hasattr(self, "_flash_label"):
            self._flash_label = QLabel("")
            self._flash_label.setFont(theme.font(10, 400, mono=True))
            self._flash_label.setStyleSheet(
                f"color: {theme.GOOD}; font-family: '{theme.mono_family()}'; font-size: 10px;")
            self.footer_lay.insertWidget(0, self._flash_label)
        self._flash_label.setText(text)
        QTimer.singleShot(2200, lambda: self._flash_label.setText(""))

    # -- actions -----------------------------------------------------------
    def _choose_dir(self) -> None:
        start = self._rec_dir.text() or paths.default_recordings_dir()
        chosen = QFileDialog.getExistingDirectory(self, "选择录音保存目录", start)
        if chosen:
            self._rec_dir.setText(chosen)

    def _reset(self) -> None:
        if QMessageBox.question(
            self, "恢复默认", "确定要把所有设置恢复为默认值吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        ) == QMessageBox.StandardButton.Yes:
            for key, value in library_defaults().items():
                self.library.set(key, value, save=False)
            self.library.save()
            self._reset_done = True
            self.accept()

    def apply(self) -> None:
        if self._reset_done:
            # defaults were already written; do not let the (now stale) widget
            # values in this dialog overwrite them
            return
        self.library.set_proxy_config(self._current_proxy())
        self.library.set("resume_last", self._resume.isChecked(), save=False)
        self.library.set("notify_track", self._notify.isChecked(), save=False)
        self.library.set("show_spectrum", self._spectrum.isChecked(), save=False)
        self.library.set("recordings_dir", self._rec_dir.text().strip(), save=False)
        self.library.set("auto_record", self._auto_rec.isChecked(), save=False)
        self.library.set("zh_only", self._zh.isChecked(), save=False)
        self.library.set("favorites_only", self._fav.isChecked(), save=False)
        self.library.set("close_to_tray", self._tray_close.isChecked(), save=False)
        self.library.set("tray_notifications", self._tray_notify.isChecked(), save=False)
        self.library.save()


def library_defaults() -> dict:
    from .library import DEFAULTS
    return dict(DEFAULTS)


# --------------------------------------------------------------------------- #
#  transport report
# --------------------------------------------------------------------------- #
class ReportDialog(DialogBase):
    """Live diagnostics for the current stream."""

    def __init__(self, parent, station: dict, engine):
        super().__init__(parent, "连接诊断", width=560, height=430)
        self.engine = engine
        self.station = station

        lay = self.body_lay
        lay.setSpacing(10)

        head = QWidget()
        hl = QHBoxLayout(head)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(10)
        self._art = QLabel()
        self._art.setFixedSize(40, 40)
        hl.addWidget(self._art)
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(1)
        self._name = ElideLabel(station.get("name", ""))
        self._name.setFont(theme.font(14, 700))
        self._name.setStyleSheet(f"color: {theme.TEXT};")
        self._sub = ElideLabel("")
        self._sub.setFont(theme.font(11, 400))
        self._sub.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        col.addWidget(self._name)
        col.addWidget(self._sub)
        hl.addLayout(col, 1)
        lay.addWidget(head)
        lay.addWidget(hline(theme.STROKE))

        self._rows: dict[str, KeyValueRow] = {}
        for key in ("状态", "上游地址", "内容类型", "实测码率", "已接收", "缓冲", "丢帧",
                    "客户端", "开始时间"):
            row = KeyValueRow(key, "--")
            self._rows[key] = row
            lay.addWidget(row)
        lay.addStretch(1)

        self._timer = None
        from PySide6.QtCore import QTimer
        self._timer = QTimer(self)
        self._timer.setInterval(700)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()
        self._refresh()

        self.add_footer_stretch()
        copy = TextButton("复制地址", "external")
        copy.clicked.connect(self._copy)
        self.footer_lay.addWidget(copy)
        close = TextButton("关闭", "", primary=True)
        close.clicked.connect(self.accept)
        self.footer_lay.addWidget(close)

    def _copy(self) -> None:
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.station.get("url", ""))

    def _refresh(self) -> None:
        station = self.station
        self._sub.setText(" · ".join([b for b in [
            station.get("country", ""), station.get("codec", ""),
            f"{station.get('bitrate')} kbps" if station.get("bitrate") else "",
        ] if b]))
        relay = getattr(self.engine, "_relay", None)
        state = self.engine.state
        state_label = {
            "idle": "已停止", "connecting": "正在连接", "buffering": "缓冲中",
            "playing": "播放中", "error": "错误",
        }.get(state, state)
        self._rows["状态"].set_value(state_label)
        if relay is None:
            for key in ("上游地址", "内容类型", "实测码率", "已接收", "缓冲", "丢帧", "客户端"):
                self._rows[key].set_value("--", dim=True)
            return
        self._rows["上游地址"].set_value(relay.final_url or station.get("url", ""))
        self._rows["内容类型"].set_value(relay.content_type or "--")
        self._rows["实测码率"].set_value(f"{relay.measured_kbps:.0f} kbps")
        self._rows["已接收"].set_value(f"{relay.bytes_audio/1048576:.2f} MB")
        self._rows["缓冲"].set_value(f"{relay.buffer_bytes/1024:.0f} KB")
        self._rows["丢帧"].set_value(f"{relay.dropped_bytes/1024:.0f} KB",
                                     dim=relay.dropped_bytes == 0)
        self._rows["客户端"].set_value(str(relay.clients))
        elapsed = relay.elapsed
        self._rows["开始时间"].set_value(
            f"{int(elapsed//3600):02d}:{int(elapsed%3600//60):02d}:{int(elapsed%60):02d}"
        )


# --------------------------------------------------------------------------- #
#  export dialog
# --------------------------------------------------------------------------- #
class ExportDialog(DialogBase):
    def __init__(self, parent, library):
        super().__init__(parent, "导出收藏", width=460)
        self.library = library
        self.path = ""
        lay = self.body_lay
        count = len(library.favorites)
        lay.addWidget(self._body(f"将把 {count} 个收藏电台导出为 M3U 播放列表，"
                                 "可在其它播放器中直接打开。"))
        self._edit = QLineEdit(os.path.join(
            os.path.expanduser("~"), "Desktop", "broadcast-favorites.m3u"))
        self._edit.setObjectName("Field")
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(8)
        rl.addWidget(self._edit, 1)
        browse = IconButton("folder", 28, 15, "选择位置", color=theme.TEXT_DIM)
        browse.clicked.connect(self._browse)
        rl.addWidget(browse)
        lay.addWidget(row)
        lay.addStretch(1)

        self.add_footer_stretch()
        cancel = TextButton("取消")
        cancel.clicked.connect(self.reject)
        self.footer_lay.addWidget(cancel)
        ok = TextButton("导出", "download", primary=True)
        ok.clicked.connect(self._export)
        self.footer_lay.addWidget(ok)

    def _body(self, text: str) -> QLabel:
        lab = QLabel(text)
        lab.setFont(theme.font(12, 400))
        lab.setStyleSheet(f"color: {theme.TEXT_DIM};")
        lab.setWordWrap(True)
        return lab

    def _browse(self) -> None:
        chosen, _ = QFileDialog.getSaveFileName(
            self, "导出为 M3U", self._edit.text(), "M3U 播放列表 (*.m3u)")
        if chosen:
            self._edit.setText(chosen)

    def _export(self) -> None:
        path = self._edit.text().strip()
        if not path:
            return
        if not path.lower().endswith(".m3u"):
            path += ".m3u"
        try:
            self.library.export_favorites(path)
        except OSError as exc:
            QMessageBox.warning(self, "导出失败", str(exc))
            return
        self.path = path
        self.accept()


# --------------------------------------------------------------------------- #
#  confirmation
# --------------------------------------------------------------------------- #
def confirm(parent, title: str, text: str, danger: bool = False) -> bool:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    box.setIcon(QMessageBox.Icon.Warning if danger else QMessageBox.Icon.Question)
    box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    box.setDefaultButton(QMessageBox.StandardButton.No)
    box.setStyleSheet(theme.stylesheet())
    return box.exec() == QMessageBox.StandardButton.Yes


def info(parent, title: str, text: str) -> None:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    box.setIcon(QMessageBox.Icon.Information)
    box.setStyleSheet(theme.stylesheet())
    box.exec()
