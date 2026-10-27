"""Table model and progress-bar delegate for the download queue."""
from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPalette
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from ..jobs import Job, Status
from . import theme
from .queue import QueueManager

COLUMNS = ["Title", "Status", "Progress", "Size", "Speed", "ETA", "Format"]
COL_TITLE, COL_STATUS, COL_PROGRESS, COL_SIZE, COL_SPEED, COL_ETA, COL_FORMAT = range(len(COLUMNS))
JOB_ROLE = Qt.ItemDataRole.UserRole + 1


def human_bytes(n: float | None) -> str:
    if n is None:
        return ""
    for unit in ("B", "KiB", "MiB", "GiB"):
        if abs(n) < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.2f} TiB"


def human_eta(seconds: float | None) -> str:
    if seconds is None:
        return ""
    seconds = int(seconds)
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def status_text(job: Job) -> str:
    if job.status.active and job.phase:
        return job.phase
    return job.status.value


class QueueModel(QAbstractTableModel):
    def __init__(self, queue: QueueManager):
        super().__init__()
        self.queue = queue
        self._order: list[int] = []
        self._dirty: set[int] = set()
        # yt-dlp reports progress many times a second; repaint changed rows at most 5 times a second.
        self._timer = QTimer(self, interval=200)
        self._timer.timeout.connect(self._flush)
        self._timer.start()
        queue.job_added.connect(self._on_added)
        queue.job_removed.connect(self._on_removed)
        queue.job_changed.connect(self._dirty.add)

    def job(self, row: int) -> Job | None:
        if 0 <= row < len(self._order):
            return self.queue.jobs.get(self._order[row])
        return None

    def row_of(self, job_id: int) -> int:
        try:
            return self._order.index(job_id)
        except ValueError:
            return -1

    # --- Qt model API ----------------------------------------------------------------------------
    def rowCount(self, parent=QModelIndex()):  # noqa: B008 - Qt's signature
        return 0 if parent.isValid() else len(self._order)

    def columnCount(self, parent=QModelIndex()):  # noqa: B008
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return COLUMNS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        job = self.job(index.row())
        if job is None:
            return None
        col = index.column()
        if role == JOB_ROLE:
            return job
        if role == Qt.ItemDataRole.DisplayRole:
            return self._display(job, col)
        if role == Qt.ItemDataRole.ToolTipRole:
            return self._tooltip(job, col)
        if role == Qt.ItemDataRole.ForegroundRole and col == COL_STATUS:
            c = theme.colors()
            color = {
                Status.DONE: c["ok"], Status.PARTIAL: c["warn"], Status.FAILED: c["error"],
                Status.CANCELLED: c["muted"], Status.QUEUED: c["muted"],
            }.get(job.status, c["info"])
            return QColor(color)
        if role == Qt.ItemDataRole.TextAlignmentRole and col in (COL_SIZE, COL_SPEED, COL_ETA):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None

    def _display(self, job: Job, col: int):
        if col == COL_TITLE:
            return job.display_title
        if col == COL_STATUS:
            return status_text(job)
        if col == COL_PROGRESS:
            return job.progress
        if col == COL_SIZE:
            return human_bytes(job.total)
        if col == COL_SPEED:
            return f"{human_bytes(job.speed)}/s" if job.speed else ""
        if col == COL_ETA:
            return human_eta(job.eta) if job.status == Status.RUNNING else ""
        if col == COL_FORMAT:
            return job.options.summary()
        return None

    def _tooltip(self, job: Job, col: int) -> str:
        lines = [job.url]
        if job.title:
            lines.insert(0, job.title)
        if job.error:
            lines.append(f"Error: {job.error}")
        if job.warnings:
            lines.append(f"{len(job.warnings)} warning(s); see the log")
        if job.files:
            lines.append("Saved: " + "\n".join(job.files[-5:]))
        return "\n".join(lines)

    # --- updates ---------------------------------------------------------------------------------
    def _on_added(self, job: Job) -> None:
        row = len(self._order)
        self.beginInsertRows(QModelIndex(), row, row)
        self._order.append(job.id)
        self.endInsertRows()

    def _on_removed(self, job_id: int) -> None:
        row = self.row_of(job_id)
        if row >= 0:
            self.beginRemoveRows(QModelIndex(), row, row)
            self._order.pop(row)
            self.endRemoveRows()
        self._dirty.discard(job_id)

    def _flush(self) -> None:
        if not self._dirty:
            return
        rows = sorted(r for r in (self.row_of(i) for i in self._dirty) if r >= 0)
        self._dirty.clear()
        if rows:
            self.dataChanged.emit(self.index(rows[0], 0), self.index(rows[-1], len(COLUMNS) - 1))

    def refresh_all(self) -> None:
        if self._order:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self._order) - 1, len(COLUMNS) - 1))


class ProgressDelegate(QStyledItemDelegate):
    """A slim rounded bar with the percentage next to it."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        style = opt.widget.style() if opt.widget else None
        if style:
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)

        job: Job | None = index.data(JOB_ROLE)
        if job is None:
            return
        value = job.progress
        c = theme.colors()
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        rect = option.rect.adjusted(6, 0, -6, 0)
        text_w = 44
        bar = QRect(rect.left(), rect.center().y() - 3, max(10, rect.width() - text_w - 6), 6)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        track = QColor(c["border"]) if not selected else QColor(255, 255, 255, 80)
        painter.setBrush(track)
        painter.drawRoundedRect(bar, 3, 3)
        if value is not None:
            fill = QColor(c["ok"]) if job.status == Status.DONE else QColor(theme.ACCENT)
            if job.status in (Status.FAILED, Status.CANCELLED):
                fill = QColor(c["muted"])
            if selected:
                fill = QColor("#ffffff")
            done = QRect(bar)
            done.setWidth(max(6, int(bar.width() * value)) if value > 0 else 0)
            if done.width():
                painter.setBrush(fill)
                painter.drawRoundedRect(done, 3, 3)
            label = f"{value * 100:.0f}%"
        elif job.status.active:
            label = "…"
        else:
            label = ""
        role = QPalette.ColorRole.HighlightedText if selected else QPalette.ColorRole.Text
        painter.setPen(option.palette.color(role))
        text_rect = QRect(bar.right() + 6, rect.top(), text_w, rect.height())
        painter.drawText(text_rect, int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), label)
        painter.restore()
