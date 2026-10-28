"""The main window: link input, download options, the queue and its log."""
from __future__ import annotations

import re
import sys
import time
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QByteArray, QItemSelectionModel, Qt, QTimer, QUrl, qVersion
from PySide6.QtGui import QAction, QDesktopServices, QFont, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from .. import APP_ID, APP_NAME, __version__, system
from ..components import Components, old_executable
from ..jobs import Job, Status
from ..options import AUDIO_FORMATS, AUDIO_QUALITIES, VIDEO_CONTAINERS, VIDEO_QUALITIES, ToolPaths
from ..settings import Settings
from . import icons, theme
from .components_dialog import ComponentsDialog
from .formats_dialog import FormatsDialog
from .preferences import PreferencesDialog
from .queue import QueueManager
from .queue_model import COL_FORMAT, COL_PROGRESS, COL_STATUS, COL_TITLE, JOB_ROLE, ProgressDelegate, QueueModel
from .updates import UpdateService

URL_RE = re.compile(r"https?://[^\s<>\"'`]+", re.IGNORECASE)
UPDATE_CHECK_INTERVAL = 6 * 3600


def extract_urls(text: str) -> list[str]:
    seen: dict[str, None] = {}
    for match in URL_RE.finditer(text):
        url = match.group(0).rstrip(".,;:!?)]}>")
        seen.setdefault(url, None)
    return list(seen)


def queue_file() -> Path:
    return system.data_dir() / "queue.json"


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings, components: Components, initial_urls: list[str] | None = None):
        super().__init__()
        self.settings = settings
        self.components = components
        self.queue = QueueManager(self.tool_paths, settings.max_concurrent, paused=not settings.auto_start)
        self.updates = UpdateService(components, settings, self.queue)
        self._log_job: int | None = None
        self._log_seq = 0
        self._setup_open = False
        self._restart = False

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(icons.app_icon())
        self.setAcceptDrops(True)
        self.resize(1080, 720)

        self.model = QueueModel(self.queue)
        self._build_ui()
        self._build_menus()
        self._load_options_into_ui()

        self.queue.activity_changed.connect(self._update_summary)
        self.queue.job_added.connect(lambda _: self._update_summary())
        self.queue.job_removed.connect(lambda _: self._update_summary())
        self.queue.job_finished.connect(self._on_job_finished)
        self.queue.tools_missing.connect(self._on_tools_missing)
        self.updates.checked.connect(self._update_badge)
        self.updates.busy_changed.connect(self._update_badge)
        self.updates.installed.connect(self._on_component_installed)
        self.updates.install_failed.connect(self._on_component_failed)
        self.updates.progress.connect(self._on_component_progress)
        self.updates.restart_requested.connect(self._offer_restart)
        QGuiApplication.clipboard().dataChanged.connect(self._on_clipboard)
        QGuiApplication.styleHints().colorSchemeChanged.connect(self._on_system_theme)

        self._log_timer = QTimer(self, interval=300)
        self._log_timer.timeout.connect(self._refresh_log)
        self._log_timer.start()
        self._update_timer = QTimer(self, interval=3600 * 1000)
        self._update_timer.timeout.connect(self._maybe_check_updates)
        self._update_timer.start()

        if settings.window_geometry:
            self.restoreGeometry(QByteArray.fromBase64(settings.window_geometry.encode()))
        if settings.window_state:
            self.splitter.restoreState(QByteArray.fromBase64(settings.window_state.encode()))

        self.queue.load(queue_file())
        if initial_urls:
            self.url_box.setPlainText("\n".join(initial_urls))
        self._update_summary()
        self._update_badge()
        QTimer.singleShot(250, self._startup)

    # --- tools -----------------------------------------------------------------------------------
    def tool_paths(self) -> ToolPaths | None:
        ytdlp = self.components.ytdlp.path()
        if ytdlp is None:
            return None
        return ToolPaths(
            ytdlp=ytdlp,
            ffmpeg_dir=self.components.ffmpeg.location(),
            deno=self.components.deno.path(),
            archive_file=system.data_dir() / "archive.txt",
        )

    # --- layout ----------------------------------------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 6)
        root.setSpacing(10)

        # Links
        self.url_box = QPlainTextEdit()
        self.url_box.setPlaceholderText("Paste links here: one or many, from any site yt-dlp supports. "
                                        "Ctrl+Enter adds them to the queue.")
        self.url_box.setFixedHeight(76)
        self.url_box.setTabChangesFocus(True)
        self.add_btn = QPushButton("Add to queue")
        self.add_btn.setObjectName("primary")
        self.add_btn.setToolTip("Ctrl+Enter")
        self.add_btn.clicked.connect(self.add_from_box)
        paste_btn = QPushButton("Paste && add")
        paste_btn.setToolTip("Add the links on the clipboard")
        paste_btn.clicked.connect(self.paste_and_add)
        self.formats_btn = QPushButton("Choose format…")
        self.formats_btn.setToolTip("See every format of a single video and pick exactly what to download")
        self.formats_btn.clicked.connect(self.choose_formats)
        side = QVBoxLayout()
        side.setSpacing(6)
        for b in (self.add_btn, paste_btn, self.formats_btn):
            b.setMinimumWidth(130)
            side.addWidget(b)
        side.addStretch(1)
        links = QHBoxLayout()
        links.addWidget(self.url_box, 1)
        links.addLayout(side)
        root.addLayout(links)

        root.addWidget(self._build_options())

        # Queue toolbar
        bar = QHBoxLayout()
        title = QLabel("Queue")
        title.setObjectName("heading")
        bar.addWidget(title)
        self.summary = QLabel()
        self.summary.setObjectName("muted")
        bar.addWidget(self.summary)
        bar.addStretch(1)
        self.run_btn = QPushButton()
        self.run_btn.clicked.connect(lambda: self._set_paused(not self.queue.paused))
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(lambda: self.queue.cancel(self.selected_ids()))
        self.retry_btn = QPushButton("Retry")
        self.retry_btn.clicked.connect(lambda: self.queue.retry(self.selected_ids()))
        self.remove_btn = QPushButton("Remove")
        self.remove_btn.clicked.connect(self.remove_selected)
        clear_btn = QPushButton("Clear")
        clear_btn.setToolTip("Remove every download that is no longer queued or running")
        clear_btn.clicked.connect(self.queue.clear_finished)
        for b in (self.run_btn, self.cancel_btn, self.retry_btn, self.remove_btn, clear_btn):
            bar.addWidget(b)
        root.addLayout(bar)

        # Queue table + log
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setItemDelegateForColumn(COL_PROGRESS, ProgressDelegate(self.table))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(30)
        header = self.table.horizontalHeader()
        header.setHighlightSections(False)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(COL_TITLE, QHeaderView.ResizeMode.Stretch)
        for col, width in ((COL_STATUS, 150), (COL_PROGRESS, 150), (COL_FORMAT, 150)):
            self.table.setColumnWidth(col, width)
        for col in (3, 4, 5):
            self.table.setColumnWidth(col, 86)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.table.doubleClicked.connect(self._on_double_click)
        self.table.selectionModel().selectionChanged.connect(self._on_selection)

        log_panel = QWidget()
        log_lay = QVBoxLayout(log_panel)
        log_lay.setContentsMargins(0, 4, 0, 0)
        log_lay.setSpacing(4)
        self.log_title = QLabel("Log: select a download to see yt-dlp's output")
        self.log_title.setObjectName("muted")
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.log.setMaximumBlockCount(5000)
        mono = QFont("Consolas" if system.IS_WINDOWS else "Monospace")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setPointSize(9)
        self.log.setFont(mono)
        log_lay.addWidget(self.log_title)
        log_lay.addWidget(self.log)

        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.addWidget(self.table)
        self.splitter.addWidget(log_panel)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setChildrenCollapsible(True)
        root.addWidget(self.splitter, 1)
        self.setCentralWidget(central)

        # Status bar
        self.badge = QPushButton()
        self.badge.setObjectName("badge")
        self.badge.setCursor(Qt.CursorShape.PointingHandCursor)
        self.badge.clicked.connect(self.open_components)
        self.statusBar().addPermanentWidget(self.badge)
        self.statusBar().setSizeGripEnabled(True)
        self._on_selection()

    def _build_options(self) -> QGroupBox:
        box = QGroupBox("Download as")
        grid = QGridLayout(box)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)

        # Video / audio switch
        self.video_btn = QPushButton("Video")
        self.audio_btn = QPushButton("Audio only")
        self.mode_group = QButtonGroup(self)
        self.video_btn.setObjectName("segmentLeft")
        self.audio_btn.setObjectName("segmentRight")
        for i, b in enumerate((self.video_btn, self.audio_btn)):
            b.setCheckable(True)
            b.setMinimumWidth(90)
            self.mode_group.addButton(b, i)
        self.mode_group.idToggled.connect(self._on_mode)
        mode = QHBoxLayout()
        mode.setSpacing(0)
        mode.addWidget(self.video_btn)
        mode.addWidget(self.audio_btn)

        self.quality = QComboBox()
        for q in VIDEO_QUALITIES:
            self.quality.addItem("Best available" if q == "best" else f"Up to {q}p", q)
        self.container = QComboBox()
        for c in VIDEO_CONTAINERS:
            self.container.addItem("Any (no conversion)" if c == "auto" else c.upper(), c)
        self.container.setToolTip("MP4 plays everywhere; MKV keeps every stream as is; Any avoids remuxing.")
        video_opts = QWidget()
        v = QHBoxLayout(video_opts)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(QLabel("Quality"))
        v.addWidget(self.quality)
        v.addSpacing(8)
        v.addWidget(QLabel("Container"))
        v.addWidget(self.container)
        v.addStretch(1)

        self.audio_format = QComboBox()
        for f in AUDIO_FORMATS:
            self.audio_format.addItem("Original (no conversion)" if f == "best" else f.upper(), f)
        self.audio_quality = QComboBox()
        for label in AUDIO_QUALITIES:
            self.audio_quality.addItem("Best" if label == "best" else label, label)
        audio_opts = QWidget()
        a = QHBoxLayout(audio_opts)
        a.setContentsMargins(0, 0, 0, 0)
        a.addWidget(QLabel("Format"))
        a.addWidget(self.audio_format)
        a.addSpacing(8)
        self.audio_quality_label = QLabel("Quality")
        a.addWidget(self.audio_quality_label)
        a.addWidget(self.audio_quality)
        a.addStretch(1)

        self.mode_stack = QStackedWidget()
        self.mode_stack.addWidget(video_opts)
        self.mode_stack.addWidget(audio_opts)
        self.mode_stack.setSizePolicy(video_opts.sizePolicy())

        grid.addLayout(mode, 0, 0)
        grid.addWidget(self.mode_stack, 0, 1, 1, 2)

        # Destination
        self.out_dir = QLineEdit()
        self.out_dir.setPlaceholderText(str(system.default_download_dir()))
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._pick_folder)
        open_dir = QPushButton("Open")
        open_dir.clicked.connect(self.open_download_folder)
        dest = QHBoxLayout()
        dest.addWidget(self.out_dir, 1)
        dest.addWidget(browse)
        dest.addWidget(open_dir)
        grid.addWidget(QLabel("Save to"), 1, 0)
        grid.addLayout(dest, 1, 1, 1, 2)

        # Extras
        self.playlist = QCheckBox("Whole playlist")
        self.playlist.setToolTip("For links to a video inside a playlist: download the entire playlist into a folder")
        self.subtitles = QCheckBox("Subtitles")
        self.thumbnail = QCheckBox("Embed thumbnail")
        self.metadata = QCheckBox("Embed metadata")
        self.sponsorblock = QCheckBox("Cut sponsors")
        self.sponsorblock.setToolTip("Remove SponsorBlock segments (YouTube); categories in Preferences")
        more = QPushButton("More options…")
        more.clicked.connect(self.open_preferences)
        extras = QHBoxLayout()
        for w in (self.playlist, self.subtitles, self.thumbnail, self.metadata, self.sponsorblock):
            extras.addWidget(w)
            extras.addSpacing(6)
        extras.addStretch(1)
        extras.addWidget(more)
        grid.addLayout(extras, 2, 0, 1, 3)
        grid.setColumnStretch(2, 1)

        for combo in (self.quality, self.container, self.audio_format, self.audio_quality):
            combo.currentIndexChanged.connect(self._save_options_from_ui)
        for check in (self.playlist, self.subtitles, self.thumbnail, self.metadata, self.sponsorblock):
            check.toggled.connect(self._save_options_from_ui)
        self.out_dir.editingFinished.connect(self._save_options_from_ui)
        return box

    def _build_menus(self) -> None:
        def action(menu: QMenu, text: str, slot, shortcut=None) -> QAction:
            act = QAction(text, self)
            act.triggered.connect(slot)
            if shortcut:
                act.setShortcut(QKeySequence(shortcut))
            menu.addAction(act)
            return act

        mb = self.menuBar()
        m = mb.addMenu("&File")
        action(m, "Add links from a text file…", self.add_from_file)
        action(m, "Open download folder", self.open_download_folder)
        m.addSeparator()
        action(m, "Quit", self.close, QKeySequence.StandardKey.Quit)

        m = mb.addMenu("&Queue")
        action(m, "Add links", self.add_from_box, "Ctrl+Return")
        action(m, "Paste and add", self.paste_and_add, "Ctrl+Shift+V")
        m.addSeparator()
        self.pause_action = action(m, "Pause queue", lambda: self._set_paused(not self.queue.paused), "Ctrl+P")
        action(m, "Retry failed", self.retry_failed)
        action(m, "Remove selected", self.remove_selected, QKeySequence.StandardKey.Delete)
        action(m, "Clear", self.queue.clear_finished)

        m = mb.addMenu("&Tools")
        action(m, "Tools && updates…", self.open_components)
        action(m, "Preferences…", self.open_preferences, QKeySequence.StandardKey.Preferences)
        m.addSeparator()
        action(m, "Open data folder", lambda: system.open_path(system.data_dir()))
        if system.IS_LINUX:
            action(m, "Add to the applications menu", self.install_desktop_entry)

        m = mb.addMenu("&Help")
        action(m, "Supported sites", lambda: QDesktopServices.openUrl(
            QUrl("https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md")))
        action(m, "yt-dlp documentation", lambda: QDesktopServices.openUrl(
            QUrl("https://github.com/yt-dlp/yt-dlp#readme")))
        action(m, f"About {APP_NAME}", self.about)

    # --- options <-> settings --------------------------------------------------------------------
    def _load_options_into_ui(self) -> None:
        o = self.settings.options
        widgets = (self.quality, self.container, self.audio_format, self.audio_quality, self.playlist,
                   self.subtitles, self.thumbnail, self.metadata, self.sponsorblock, self.mode_group)
        for w in widgets:
            w.blockSignals(True)
        (self.audio_btn if o.mode == "audio" else self.video_btn).setChecked(True)
        self.mode_stack.setCurrentIndex(1 if o.mode == "audio" else 0)
        for combo, value in ((self.quality, o.quality), (self.container, o.container),
                             (self.audio_format, o.audio_format), (self.audio_quality, o.audio_quality)):
            combo.setCurrentIndex(max(0, combo.findData(value)))
        self.out_dir.setText(o.output_dir)
        self.playlist.setChecked(o.playlist)
        self.subtitles.setChecked(o.subtitles)
        self.thumbnail.setChecked(o.embed_thumbnail)
        self.metadata.setChecked(o.embed_metadata)
        self.sponsorblock.setChecked(o.sponsorblock)
        for w in widgets:
            w.blockSignals(False)
        self._sync_mode_widgets()

    def _save_options_from_ui(self) -> None:
        self.settings.options = replace(
            self.settings.options,
            mode="audio" if self.audio_btn.isChecked() else "video",
            quality=self.quality.currentData(),
            container=self.container.currentData(),
            audio_format=self.audio_format.currentData(),
            audio_quality=self.audio_quality.currentData(),
            output_dir=self.out_dir.text().strip() or str(system.default_download_dir()),
            playlist=self.playlist.isChecked(),
            subtitles=self.subtitles.isChecked(),
            embed_thumbnail=self.thumbnail.isChecked(),
            embed_metadata=self.metadata.isChecked(),
            sponsorblock=self.sponsorblock.isChecked(),
            custom_format="",
        )
        self._sync_mode_widgets()

    def _on_mode(self, _id: int, checked: bool) -> None:
        if checked:
            self.mode_stack.setCurrentIndex(self.mode_group.checkedId())
            self._save_options_from_ui()

    def _sync_mode_widgets(self) -> None:
        audio = self.audio_btn.isChecked()
        lossy = self.audio_format.currentData() in ("mp3", "m4a", "opus")
        self.audio_quality.setEnabled(lossy)
        self.audio_quality_label.setEnabled(lossy)
        self.subtitles.setEnabled(not audio)

    def _pick_folder(self) -> None:
        start = self.out_dir.text() or str(system.default_download_dir())
        folder = QFileDialog.getExistingDirectory(self, "Save downloads to", start)
        if folder:
            self.out_dir.setText(folder)
            self._save_options_from_ui()

    # --- adding ----------------------------------------------------------------------------------
    def add_urls(self, urls: list[str], options=None) -> int:
        urls = [u for u in urls if not self.queue.has_url(u)]
        if not urls:
            self.statusBar().showMessage("Those links are already in the queue.", 4000)
            return 0
        self._save_options_from_ui()
        self.queue.add(urls, options or self.settings.options)
        added = f"Added {len(urls)} link{'s' if len(urls) != 1 else ''}"
        self.statusBar().showMessage(added + (" (the queue is paused)." if self.queue.paused else "."), 4000)
        return len(urls)

    def add_from_box(self) -> None:
        urls = extract_urls(self.url_box.toPlainText())
        if not urls:
            self.statusBar().showMessage("No links found. Links start with http:// or https://", 5000)
            self.url_box.setFocus()
            return
        self.add_urls(urls)
        self.url_box.clear()

    def paste_and_add(self) -> None:
        urls = extract_urls(QGuiApplication.clipboard().text())
        if urls:
            self.add_urls(urls)
        else:
            self.statusBar().showMessage("The clipboard holds no links.", 4000)

    def add_from_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Text file with links", "", "Text (*.txt);;All files (*)")
        if path:
            try:
                text = Path(path).read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                QMessageBox.warning(self, "Could not read file", str(exc))
                return
            urls = extract_urls(text)
            if urls:
                self.add_urls(urls)
            else:
                self.statusBar().showMessage("No links found in that file.", 4000)

    def choose_formats(self) -> None:
        urls = extract_urls(self.url_box.toPlainText())
        if not urls:
            job = self.current_job()
            urls = [job.url] if job else []
        if not urls:
            self.statusBar().showMessage("Paste a link first.", 4000)
            self.url_box.setFocus()
            return
        tools = self.tool_paths()
        if tools is None:
            self._ask_for_ytdlp()
            return
        self._save_options_from_ui()
        url = urls[0]
        dialog = FormatsDialog(url, tools, self.settings.options, self)
        if dialog.exec() and dialog.selector:
            options = replace(self.settings.options, mode="video", custom_format=dialog.selector,
                              container=dialog.chosen_container, playlist=False)
            self.queue.add([url], options)
            remaining = [u for u in extract_urls(self.url_box.toPlainText()) if u != url]
            self.url_box.setPlainText("\n".join(remaining))

    def _on_clipboard(self) -> None:
        if not self.settings.watch_clipboard:
            return
        present = set(extract_urls(self.url_box.toPlainText()))
        fresh = [u for u in extract_urls(QGuiApplication.clipboard().text())
                 if u not in present and not self.queue.has_url(u)]
        if fresh:
            text = self.url_box.toPlainText().rstrip()
            self.url_box.setPlainText((text + "\n" if text else "") + "\n".join(fresh))
            self.statusBar().showMessage(f"Picked up {len(fresh)} link(s) from the clipboard.", 4000)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasText() or event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        mime = event.mimeData()
        text = mime.text() if mime.hasText() else "\n".join(u.toString() for u in mime.urls())
        urls = extract_urls(text)
        if urls:
            self.add_urls(urls)
            event.acceptProposedAction()


    # --- queue actions ---------------------------------------------------------------------------
    def selected_ids(self) -> list[int]:
        rows = sorted({i.row() for i in self.table.selectionModel().selectedRows()})
        return [job.id for job in (self.model.job(r) for r in rows) if job]

    def current_job(self) -> Job | None:
        ids = self.selected_ids()
        return self.queue.jobs.get(ids[0]) if ids else None

    def remove_selected(self) -> None:
        ids = self.selected_ids()
        running = [i for i in ids if self.queue.jobs[i].status.active]
        if running:
            answer = QMessageBox.question(self, "Remove downloads",
                                          f"{len(running)} of these are still downloading. Cancel and remove them?")
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.queue.remove(ids)

    def retry_failed(self) -> None:
        self.queue.retry([j.id for j in self.queue.jobs.values()
                          if j.status in (Status.FAILED, Status.PARTIAL, Status.CANCELLED)])

    def _set_paused(self, paused: bool) -> None:
        self.queue.set_paused(paused)
        if not paused and self.tool_paths() is None:
            self._ask_for_ytdlp()

    def _ask_for_ytdlp(self) -> None:
        """The user wants to download something but yt-dlp is missing: offer the setup."""
        if self.updates.installing("yt-dlp"):
            self.statusBar().showMessage("Waiting for yt-dlp to finish installing…", 5000)
        else:
            self.open_setup()

    def _context_menu(self, pos) -> None:
        index = self.table.indexAt(pos)
        if not index.isValid():
            return
        if not self.table.selectionModel().isRowSelected(index.row()):
            self.table.selectionModel().select(
                index, QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows)
        job: Job = index.data(JOB_ROLE)
        menu = QMenu(self)
        last_file = Path(job.files[-1]) if job.files else None
        if last_file and last_file.exists():
            menu.addAction("Open file", lambda: system.open_path(last_file))
            menu.addAction("Show in folder", lambda: system.reveal_in_file_manager(last_file))
        else:
            menu.addAction("Open download folder", lambda: system.open_path(Path(job.options.output_dir)))
        menu.addAction("Copy link", lambda: QGuiApplication.clipboard().setText(
            "\n".join(self.queue.jobs[i].url for i in self.selected_ids())))
        if job.error:
            menu.addAction("Copy error", lambda: QGuiApplication.clipboard().setText(job.error))
        menu.addSeparator()
        if job.status.active or job.status == Status.QUEUED:
            menu.addAction("Cancel", lambda: self.queue.cancel(self.selected_ids()))
        if job.status.finished:
            menu.addAction("Retry", lambda: self.queue.retry(self.selected_ids()))
        menu.addAction("Remove", self.remove_selected)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _on_double_click(self, index) -> None:
        job: Job = index.data(JOB_ROLE)
        if job and job.files and Path(job.files[-1]).exists():
            system.open_path(Path(job.files[-1]))

    def open_download_folder(self) -> None:
        folder = Path(self.out_dir.text().strip() or system.default_download_dir())
        folder.mkdir(parents=True, exist_ok=True)
        system.open_path(folder)

    # --- status ----------------------------------------------------------------------------------
    def _update_summary(self) -> None:
        q = self.queue
        running = q.count(Status.RUNNING, Status.PROCESSING)
        waiting = q.count(Status.QUEUED)
        failed = q.count(Status.FAILED, Status.PARTIAL)
        parts = []
        if running:
            parts.append(f"{running} downloading")
        if waiting:
            parts.append(f"{waiting} waiting")
        if failed:
            parts.append(f"{failed} failed")
        if q.paused and (waiting or not parts):
            parts.append("paused")
        if q.blocked:
            parts.append("updating tools…")
        self.summary.setText("  ·  ".join(parts) if parts else "empty" if not q.jobs else "all done")
        self.run_btn.setText("Resume queue" if q.paused else "Pause queue")
        self.run_btn.setToolTip("Running downloads finish; queued ones wait until the queue is resumed"
                                if not q.paused else "Start the queued downloads")
        self.run_btn.setObjectName("primary" if q.paused and waiting else "")
        self.run_btn.style().unpolish(self.run_btn)
        self.run_btn.style().polish(self.run_btn)
        self.pause_action.setText("Resume queue" if q.paused else "Pause queue")

    def _update_badge(self) -> None:
        ytdlp = self.components.ytdlp
        updates = self.updates.updates_available()
        if self.updates.installing():
            text, alert = "Updating tools…", False
        elif ytdlp.path() is None:
            text, alert = "yt-dlp is not installed. Set up", True
        elif updates:
            names = ", ".join(self.components.get(k).title for k in updates)
            text, alert = f"Update available: {names}", True
        else:
            version = ytdlp.installed_version() if ytdlp.is_managed() else "system"
            text, alert = f"yt-dlp {version}", False
        self.badge.setText(text)
        self.badge.setObjectName("badgeAlert" if alert else "badge")
        self.badge.style().unpolish(self.badge)
        self.badge.style().polish(self.badge)
        self._update_summary()

    def _on_selection(self, *_) -> None:
        ids = self.selected_ids()
        jobs = [self.queue.jobs[i] for i in ids]
        self.cancel_btn.setEnabled(any(j.status.active or j.status == Status.QUEUED for j in jobs))
        self.retry_btn.setEnabled(any(j.status.finished for j in jobs))
        self.remove_btn.setEnabled(bool(jobs))
        self._log_job = ids[0] if ids else None
        self._log_seq = -1
        self._refresh_log()

    def _refresh_log(self) -> None:
        job = self.queue.jobs.get(self._log_job) if self._log_job is not None else None
        if job is None:
            if self._log_seq != 0:
                self.log.clear()
                self.log_title.setText("Log: select a download to see yt-dlp's output")
                self._log_seq = 0
            return
        if self._log_seq == -1:
            self.log_title.setText(f"Log: {job.display_title}")
        new = job.log_seq - self._log_seq
        if new <= 0 and self._log_seq != -1:
            return
        if self._log_seq == -1 or new > len(job.log):
            self.log.setPlainText("\n".join(job.log))
        else:
            for line in list(job.log)[-new:]:
                self.log.appendPlainText(line)
        self._log_seq = job.log_seq
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())
        # Buttons depend on the job's status, which changes while it runs.
        jobs = [self.queue.jobs[i] for i in self.selected_ids() if i in self.queue.jobs]
        self.cancel_btn.setEnabled(any(j.status.active or j.status == Status.QUEUED for j in jobs))
        self.retry_btn.setEnabled(any(j.status.finished for j in jobs))

    def _on_job_finished(self, job: Job) -> None:
        self._update_summary()
        if job.status == Status.DONE:
            self.statusBar().showMessage(f"Finished: {job.title or job.url}", 6000)
        elif job.status in (Status.FAILED, Status.PARTIAL):
            self.statusBar().showMessage(f"Failed: {job.title or job.url}: {job.error}", 10000)
        if not self.queue.running and not self.isActiveWindow():
            QApplication.alert(self)
        self._on_selection()

    # --- components ------------------------------------------------------------------------------
    def _startup(self) -> None:
        if system.IS_WINDOWS and system.FROZEN:
            try:  # the executable an update replaced; still locked if that process hasn't quite exited
                old_executable().unlink(missing_ok=True)
            except OSError:
                pass
        if not self.settings.setup_done or self.components.ytdlp.path() is None:
            self.open_setup()
        else:
            self._maybe_check_updates()
            self.queue.schedule()

    def _maybe_check_updates(self) -> None:
        if self.settings.check_updates and time.time() - self.settings.last_update_check > UPDATE_CHECK_INTERVAL:
            self.updates.check(auto=True)

    def open_setup(self) -> None:
        if self._setup_open:
            return
        self._setup_open = True
        try:
            ComponentsDialog(self.updates, self.settings, setup=True, parent=self).exec()
        finally:
            self._setup_open = False
        self.settings.save()
        self._after_components_changed()

    def open_components(self) -> None:
        if self.components.ytdlp.path() is None and not self.updates.installing():
            self.open_setup()
            return
        ComponentsDialog(self.updates, self.settings, parent=self).exec()
        self.settings.save()
        self._after_components_changed()

    def _after_components_changed(self) -> None:
        self._update_badge()
        self.queue.schedule()

    def _on_tools_missing(self) -> None:
        if self.updates.installing("yt-dlp"):
            self.statusBar().showMessage("Waiting for yt-dlp to finish installing…", 5000)
        elif not self._setup_open:
            # Not the setup dialog: the queue retries on every change, which would reopen it over and over.
            self.statusBar().showMessage("yt-dlp is not installed, so queued downloads wait. "
                                         "Install it under Tools → Tools & updates.", 10000)

    def _on_component_installed(self, key: str, auto: bool) -> None:
        comp = self.components.get(key)
        if comp is self.components.app:
            self._update_badge()
            self._offer_restart()
            return
        self.statusBar().showMessage(f"{comp.title} {'updated' if auto else 'installed'}: "
                                     f"{comp.installed_version()}", 8000)
        self._after_components_changed()

    def _offer_restart(self) -> None:
        version = self.components.app.restart_pending
        running = self.queue.running
        note = (f"\n\n{running} running download(s) will stop and stay in the queue."
                if running else "")
        answer = QMessageBox.question(self, "Update installed",
                                      f"{APP_NAME} {version} is installed. Restart now to use it?{note}")
        if answer == QMessageBox.StandardButton.Yes:
            self._restart = True
            self.close()
        else:
            self.statusBar().showMessage(f"{APP_NAME} {version} will be used from the next start.", 8000)

    def _on_component_failed(self, key: str, error: str) -> None:
        comp = self.components.get(key)
        self.statusBar().showMessage(f"{comp.title} could not be installed: {error}", 12000)
        self._update_badge()

    def _on_component_progress(self, key: str, phase: str, done: int, total: int) -> None:
        if total:
            self.badge.setText(f"Updating {self.components.get(key).title}… {done * 100 // total}%")

    # --- dialogs ---------------------------------------------------------------------------------
    def open_preferences(self) -> None:
        self._save_options_from_ui()
        dialog = PreferencesDialog(self.settings, self)
        if dialog.exec():
            old_theme = self.settings.theme
            dialog.apply()
            self.queue.set_max_concurrent(self.settings.max_concurrent)
            if self.settings.theme != old_theme:
                self._apply_theme()
            self.settings.save()

    def _apply_theme(self) -> None:
        theme.apply(QApplication.instance(), self.settings.theme)
        self.model.refresh_all()
        self._update_badge()

    def _on_system_theme(self, *_):
        if self.settings.theme == "system":
            self._apply_theme()

    def about(self) -> None:
        rows = [f"<b>{APP_NAME}</b> {__version__}", "A desktop front-end for yt-dlp.", ""]
        for comp in self.components.tools():
            if comp.is_managed():
                state = comp.installed_version() or "installed"
            elif comp.system_path():
                state = "installed on this system"
            else:
                state = "not installed"
            rows.append(f"{comp.title}: {state}")
        rows += ["", f"Qt {qVersion()} · Python {sys.version.split()[0]}"]

        QMessageBox.about(self, f"About {APP_NAME}", "<br>".join(rows))

    def install_desktop_entry(self) -> None:
        apps = Path.home() / ".local" / "share" / "applications"
        icon_dir = Path.home() / ".local" / "share" / "icons" / "hicolor" / "256x256" / "apps"
        try:
            apps.mkdir(parents=True, exist_ok=True)
            icon_dir.mkdir(parents=True, exist_ok=True)
            icons.render(256).save(str(icon_dir / f"{APP_ID}.png"))
            exec_line = f'"{sys.executable}"' + ("" if system.FROZEN else " -m ytdlp_gui") + " %U"
            (apps / f"{APP_ID}.desktop").write_text(
                "[Desktop Entry]\nType=Application\n"
                f"Name={APP_NAME}\nComment=Download videos and audio with yt-dlp\n"
                f"Exec={exec_line}\nPath={system.app_dir()}\nIcon={APP_ID}\nTerminal=false\n"
                "Categories=Network;AudioVideo;\nStartupWMClass=ytdlp-gui\n",
                encoding="utf-8",
            )
        except OSError as exc:
            QMessageBox.warning(self, "Could not add the menu entry", str(exc))
            return
        QMessageBox.information(self, "Added", f"{APP_NAME} is now in your applications menu. "
                                "If you move the executable, add it again.")

    # --- shutdown --------------------------------------------------------------------------------
    def closeEvent(self, event) -> None:
        if self.queue.running and not self._restart:  # a restart was already confirmed
            answer = QMessageBox.question(
                self, "Quit", f"{self.queue.running} download(s) still running. Stop them and quit? "
                "Unfinished downloads stay in the queue and resume next time.")
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        if self.updates.installing():
            for comp in self.components.all():
                self.updates.cancel_install(comp.key)
        self._save_options_from_ui()
        self.settings.window_geometry = bytes(self.saveGeometry().toBase64()).decode()
        self.settings.window_state = bytes(self.splitter.saveState().toBase64()).decode()
        self.queue.shutdown()
        try:
            self.settings.save()
            self.queue.save(queue_file())
        except OSError:
            pass
        event.accept()
        if self._restart:
            try:
                system.start_new_instance()
            except OSError as exc:
                QMessageBox.warning(self, "Restart", f"Could not start the new version: {exc}\n\nStart it yourself.")
