"""Preferences: everything that is not on the main window."""
from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import system
from ..options import COOKIE_BROWSERS, DEFAULT_TEMPLATE, PLAYLIST_TEMPLATE, SAMPLE_INFO, preview_filename
from ..settings import Settings

TEMPLATE_HELP = ("Fields like %(title)s, %(id)s, %(uploader)s, %(upload_date)s, %(ext)s; "
                 "\"/\" makes folders. See yt-dlp's \"Output template\" docs.")


def _form(parent: QTabWidget, title: str) -> QFormLayout:
    page = QWidget()
    form = QFormLayout(page)
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
    parent.addTab(page, title)
    return form


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("muted")
    label.setWordWrap(True)
    return label


def _preview() -> QLabel:
    """One line under a file name field; a long name is cut off rather than widening the dialog."""
    label = QLabel()
    label.setObjectName("muted")
    label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    label.setMinimumWidth(1)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


class PreferencesDialog(QDialog):
    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.setMinimumWidth(600)
        self.settings = settings
        o = settings.options
        tabs = QTabWidget()

        # General
        form = _form(tabs, "General")
        self.theme = QComboBox()
        for label, value in (("Use system", "system"), ("Light", "light"), ("Dark", "dark")):
            self.theme.addItem(label, value)
        self.theme.setCurrentIndex(max(0, self.theme.findData(settings.theme)))
        form.addRow("Theme:", self.theme)
        self.concurrent = QSpinBox()
        self.concurrent.setRange(1, 8)
        self.concurrent.setValue(settings.max_concurrent)
        form.addRow("Simultaneous downloads:", self.concurrent)
        self.auto_start = QCheckBox("Start the queue when the app opens (otherwise it opens paused)")
        self.auto_start.setChecked(settings.auto_start)
        form.addRow(self.auto_start)
        self.clipboard = QCheckBox("Pick up links copied to the clipboard")
        self.clipboard.setChecked(settings.watch_clipboard)
        form.addRow(self.clipboard)

        # Files
        form = _form(tabs, "Files")
        if o.mode == "audio":
            self._ext = "m4a" if o.audio_format == "best" else o.audio_format
        else:
            self._ext = "mp4" if o.container == "auto" else o.container
        self.template = QLineEdit(o.filename_template)
        self.template.setPlaceholderText(DEFAULT_TEMPLATE)
        self.template.setToolTip(TEMPLATE_HELP)
        self.preview = _preview()
        form.addRow("File name:", self.template)
        form.addRow("", self.preview)
        self.pl_template = QLineEdit(o.playlist_template)
        self.pl_template.setPlaceholderText(PLAYLIST_TEMPLATE)
        self.pl_template.setToolTip(TEMPLATE_HELP)
        self.pl_preview = _preview()
        form.addRow("File name (playlists):", self.pl_template)
        form.addRow("", self.pl_preview)
        self.restrict = QCheckBox("Use only ASCII characters without spaces in file names")
        self.restrict.setChecked(o.restrict_filenames)
        form.addRow(self.restrict)
        for signal in (self.template.textChanged, self.pl_template.textChanged, self.restrict.toggled):
            signal.connect(self._update_previews)
        self._update_previews()
        self.archive = QCheckBox("Remember downloaded videos and skip them next time")
        self.archive.setChecked(o.use_archive)
        form.addRow(self.archive)
        self.pl_items = QLineEdit(o.playlist_items)
        self.pl_items.setPlaceholderText("1-10,15,-5:")
        form.addRow("Playlist items:", self.pl_items)

        # Post-processing
        form = _form(tabs, "Subtitles && extras")
        self.sub_langs = QLineEdit(o.subtitle_langs)
        self.sub_langs.setPlaceholderText("en.*,de")
        form.addRow("Subtitle languages:", self.sub_langs)
        self.auto_subs = QCheckBox("Include automatically generated subtitles")
        self.auto_subs.setChecked(o.auto_subtitles)
        form.addRow(self.auto_subs)
        self.embed_subs = QCheckBox("Embed subtitles in the video (otherwise saved next to it)")
        self.embed_subs.setChecked(o.embed_subtitles)
        form.addRow(self.embed_subs)
        self.chapters = QCheckBox("Embed chapters")
        self.chapters.setChecked(o.embed_chapters)
        form.addRow(self.chapters)
        self.sb_cats = QLineEdit(o.sponsorblock_categories)
        form.addRow("SponsorBlock removes:", self.sb_cats)
        form.addRow(_hint("Categories: sponsor, intro, outro, selfpromo, preview, filler, interaction, "
                          "music_offtopic, poi_highlight, chapter, all."))

        # Network
        form = _form(tabs, "Network")
        self.browser = QComboBox()
        for b in COOKIE_BROWSERS:
            self.browser.addItem(b.capitalize() if b else "Don't use browser cookies", b)
        self.browser.setCurrentIndex(max(0, self.browser.findData(o.cookies_browser)))
        form.addRow("Cookies from browser:", self.browser)
        cookie_row = QHBoxLayout()
        self.cookies = QLineEdit(o.cookies_file)
        self.cookies.setPlaceholderText("cookies.txt (Used when no browser is selected)")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._pick_cookies)
        cookie_row.addWidget(self.cookies, 1)
        cookie_row.addWidget(browse)
        form.addRow("Cookies file:", cookie_row)
        self.rate = QLineEdit(o.rate_limit)
        self.rate.setPlaceholderText("500K or 5M (empty = unlimited)")
        form.addRow("Speed limit:", self.rate)
        self.proxy = QLineEdit(o.proxy)
        self.proxy.setPlaceholderText("socks5://127.0.0.1:1080")
        form.addRow("Proxy:", self.proxy)

        # Advanced
        form = _form(tabs, "Advanced")
        self.extra = QLineEdit(o.extra_args)
        self.extra.setPlaceholderText("--limit-rate 2M --concurrent-fragments 4")
        form.addRow("Extra yt-dlp options:", self.extra)
        form.addRow(_hint("Quote arguments containing spaces."))

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(tabs)
        lay.addWidget(buttons)

    def _update_previews(self) -> None:
        info = {**SAMPLE_INFO, "ext": self._ext}
        restrict = self.restrict.isChecked()
        for edit, label, fallback in ((self.template, self.preview, DEFAULT_TEMPLATE),
                                      (self.pl_template, self.pl_preview, PLAYLIST_TEMPLATE)):
            name = preview_filename(edit.text().strip() or fallback, info, restrict)
            label.setText(name.replace("/", "\\") if system.IS_WINDOWS else name)

    def _pick_cookies(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Cookies file", "", "Cookies (*.txt);;All files (*)")
        if path:
            self.cookies.setText(path)

    def apply(self) -> None:
        s = self.settings
        s.theme = self.theme.currentData()
        s.max_concurrent = self.concurrent.value()
        s.auto_start = self.auto_start.isChecked()
        s.watch_clipboard = self.clipboard.isChecked()
        s.options = replace(
            s.options,
            filename_template=self.template.text().strip() or DEFAULT_TEMPLATE,
            playlist_template=self.pl_template.text().strip() or PLAYLIST_TEMPLATE,
            restrict_filenames=self.restrict.isChecked(),
            use_archive=self.archive.isChecked(),
            playlist_items=self.pl_items.text().strip(),
            subtitle_langs=self.sub_langs.text().strip() or "en.*",
            auto_subtitles=self.auto_subs.isChecked(),
            embed_subtitles=self.embed_subs.isChecked(),
            embed_chapters=self.chapters.isChecked(),
            sponsorblock_categories=self.sb_cats.text().strip(),
            cookies_browser=self.browser.currentData(),
            cookies_file=self.cookies.text().strip(),
            rate_limit=self.rate.text().strip(),
            proxy=self.proxy.text().strip(),
            extra_args=self.extra.text().strip(),
        )
