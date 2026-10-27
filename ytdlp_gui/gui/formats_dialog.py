"""Lists every format a video offers and lets the user pick exactly what to download."""
from __future__ import annotations

import json
import subprocess

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from .. import net, system
from ..options import VIDEO_CONTAINERS, DownloadOptions, ToolPaths, info_args
from .queue_model import human_bytes, human_eta
from .tasks import run_task

FILTERS = ["All formats", "Video with audio", "Video only", "Audio only"]
HEADERS = ["ID", "Ext", "Resolution", "FPS", "Video codec", "Audio codec", "Bitrate", "Size", "Note"]


def has_video(f: dict) -> bool:
    return (f.get("vcodec") or "none") != "none"


def has_audio(f: dict) -> bool:
    return (f.get("acodec") or "none") != "none"


def compose_selector(formats: list[dict], add_audio: bool) -> tuple[str, str]:
    """Format selector for the picked formats, or ("", reason) when the combination makes no sense."""
    if not formats:
        return "", "Select a format."
    if len(formats) == 1:
        f = formats[0]
        if has_video(f) and not has_audio(f) and add_audio:
            return f"{f['format_id']}+ba", ""
        return f["format_id"], ""
    if len(formats) == 2:
        video = [f for f in formats if has_video(f)]
        audio = [f for f in formats if has_audio(f) and not has_video(f)]
        if len(video) == 1 and len(audio) == 1:
            return f"{video[0]['format_id']}+{audio[0]['format_id']}", ""
    return "", "Pick one format, or one video format plus one audio-only format."


class _Item(QTableWidgetItem):
    """Sorts by a numeric key when one is given."""

    def __init__(self, text: str, key: float | None = None):
        super().__init__(text)
        self.key = key

    def __lt__(self, other):
        if isinstance(other, _Item) and self.key is not None and other.key is not None:
            return self.key < other.key
        # Not super().__lt__: PySide routes that back into this override and recurses.
        return self.text().lower() < other.text().lower()


class FormatsDialog(QDialog):
    def __init__(self, url: str, tools: ToolPaths, options: DownloadOptions, parent=None):
        super().__init__(parent)
        self.url = url
        self.formats: list[dict] = []
        self.selector = ""
        self.setWindowTitle("Choose formats")
        self.resize(900, 560)

        self.thumb = QLabel()
        self.thumb.setFixedSize(192, 108)
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb.setObjectName("card")
        self.title = QLabel("Loading…")
        self.title.setObjectName("heading")
        self.title.setWordWrap(True)
        self.meta = QLabel(url)
        self.meta.setObjectName("muted")
        self.meta.setWordWrap(True)
        head_text = QVBoxLayout()
        head_text.addWidget(self.title)
        head_text.addWidget(self.meta)
        head_text.addStretch(1)
        head = QHBoxLayout()
        head.addWidget(self.thumb)
        head.addLayout(head_text, 1)

        self.filter = QComboBox()
        self.filter.addItems(FILTERS)
        self.filter.currentIndexChanged.connect(self._populate)
        self.add_audio = QCheckBox("Add the best audio to video-only formats")
        self.add_audio.setChecked(True)
        self.add_audio.toggled.connect(self._on_selection)
        self.container = QComboBox()
        for c in VIDEO_CONTAINERS:
            self.container.addItem("Keep original" if c == "auto" else c.upper(), c)
        self.container.setCurrentIndex(max(0, self.container.findData(options.container)))
        tools_row = QHBoxLayout()
        tools_row.addWidget(QLabel("Show:"))
        tools_row.addWidget(self.filter)
        tools_row.addSpacing(12)
        tools_row.addWidget(self.add_audio)
        tools_row.addStretch(1)
        tools_row.addWidget(QLabel("Container:"))
        tools_row.addWidget(self.container)

        self.table = QTableWidget(0, len(HEADERS))
        self.table.setHorizontalHeaderLabels(HEADERS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        # Unsorted until the user clicks a column, so yt-dlp's best-first order shows.
        self.table.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self._on_selection)
        self.table.doubleClicked.connect(lambda _: self.ok.isEnabled() and self.accept())

        self.choice = QLabel("Select a format. Ctrl+click to combine a video and an audio format.")
        self.choice.setObjectName("muted")
        self.ok = QPushButton("Add to queue")
        self.ok.setObjectName("primary")
        self.ok.setEnabled(False)
        self.ok.clicked.connect(self.accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addWidget(self.choice, 1)
        buttons.addWidget(cancel)
        buttons.addWidget(self.ok)

        lay = QVBoxLayout(self)
        lay.addLayout(head)
        lay.addLayout(tools_row)
        lay.addWidget(self.table, 1)
        lay.addLayout(buttons)

        self._task = run_task(lambda *_: self._fetch(tools, options), self._on_info, self._on_error)

    @property
    def chosen_container(self) -> str:
        return self.container.currentData()

    # --- loading ---------------------------------------------------------------------------------
    def _fetch(self, tools: ToolPaths, options: DownloadOptions):
        args = info_args(self.url, tools, options)
        out = subprocess.run(
            args, capture_output=True, stdin=subprocess.DEVNULL, timeout=180,
            env=system.child_env([tools.deno.parent] if tools.deno else None),
            **({"creationflags": subprocess.CREATE_NO_WINDOW} if system.IS_WINDOWS else {}),
        )
        if out.returncode != 0:
            err = out.stderr.decode("utf-8", "replace").strip().splitlines()
            raise RuntimeError(err[-1] if err else f"yt-dlp exited with code {out.returncode}")
        info = json.loads(out.stdout.decode("utf-8", "replace"))
        return info, self._fetch_thumbnail(info)

    @staticmethod
    def _fetch_thumbnail(info: dict) -> QImage | None:
        # The listed thumbnails are guesses (the biggest often doesn't exist), so try a few, best first.
        urls = [info.get("thumbnail")] + [t.get("url") for t in reversed(info.get("thumbnails") or [])]
        tried = []
        for url in urls:
            if not url or url in tried or len(tried) >= 4:
                continue
            tried.append(url)
            try:
                image = QImage.fromData(net.get_bytes(url))
            except Exception:  # noqa: BLE001 - the thumbnail is decoration
                continue
            if not image.isNull():
                return image
        return None

    def _on_error(self, error: str) -> None:
        self.title.setText("Could not read this link")
        self.meta.setText(error)

    def _on_info(self, result) -> None:
        info, thumb = result
        if info.get("_type") == "playlist":
            self.title.setText(info.get("title") or "Playlist")
            self.meta.setText("This is a playlist. Format selection works on a single video; "
                              "add the playlist from the main window instead.")
            return
        self.title.setText(info.get("title") or self.url)
        bits = [info.get("uploader") or info.get("channel") or "", human_eta(info.get("duration")),
                info.get("extractor_key") or ""]
        self.meta.setText("  ·  ".join(b for b in bits if b))
        if thumb is not None:
            self.thumb.setPixmap(QPixmap.fromImage(thumb).scaled(
                self.thumb.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        self.formats = [f for f in info.get("formats") or [] if f.get("format_id")
                        and (f.get("protocol") or "") != "mhtml"]  # storyboards
        self._populate()

    # --- table -----------------------------------------------------------------------------------
    def _visible(self, f: dict) -> bool:
        kind = self.filter.currentIndex()
        if kind == 1:
            return has_video(f) and has_audio(f)
        if kind == 2:
            return has_video(f) and not has_audio(f)
        if kind == 3:
            return has_audio(f) and not has_video(f)
        return True

    def _populate(self) -> None:
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        rows = [f for f in reversed(self.formats) if self._visible(f)]  # yt-dlp lists worst first
        self.table.setRowCount(len(rows))
        for r, f in enumerate(rows):
            size = f.get("filesize") or f.get("filesize_approx")
            height = f.get("height") or 0
            tbr = f.get("tbr")
            cells = [
                _Item(f["format_id"]),
                _Item(f.get("ext") or ""),
                _Item(f.get("resolution") or ("audio only" if not has_video(f) else ""), float(height)),
                _Item(f"{f['fps']:g}" if f.get("fps") else "", float(f.get("fps") or 0)),
                _Item("" if not has_video(f) else (f.get("vcodec") or "")),
                _Item("" if not has_audio(f) else (f.get("acodec") or "")),
                _Item(f"{tbr:.0f}k" if tbr else "", float(tbr or 0)),
                _Item(("~" if not f.get("filesize") and size else "") + human_bytes(size), float(size or 0)),
                _Item(f.get("format_note") or ""),
            ]
            cells[0].setData(Qt.ItemDataRole.UserRole, f)
            for c, item in enumerate(cells):
                self.table.setItem(r, c, item)
        self.table.setSortingEnabled(True)

        self._on_selection()

    def _selected_formats(self) -> list[dict]:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return [self.table.item(r, 0).data(Qt.ItemDataRole.UserRole) for r in rows]

    def _on_selection(self) -> None:
        selector, problem = compose_selector(self._selected_formats(), self.add_audio.isChecked())
        self.selector = selector
        self.ok.setEnabled(bool(selector))
        self.choice.setText(f"Format: <b>{selector}</b>" if selector else problem)

    def done(self, result: int) -> None:
        self._task.cancel()
        super().done(result)
