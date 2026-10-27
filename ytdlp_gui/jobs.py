"""A queued download and how yt-dlp's output updates it. No Qt here, so it is easy to test."""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum

from .options import FIELD_SEP, MARK_FILE, MARK_ITEM, MARK_POSTPROCESS, MARK_PROGRESS, DownloadOptions


class Status(Enum):
    QUEUED = "Queued"
    RUNNING = "Downloading"
    PROCESSING = "Processing"
    DONE = "Done"
    PARTIAL = "Done with errors"
    FAILED = "Failed"
    CANCELLED = "Cancelled"

    @property
    def active(self) -> bool:
        return self in (Status.RUNNING, Status.PROCESSING)

    @property
    def finished(self) -> bool:
        return self in (Status.DONE, Status.PARTIAL, Status.FAILED, Status.CANCELLED)


POSTPROCESSOR_LABELS = {
    "Merger": "Merging",
    "ExtractAudio": "Extracting audio",
    "EmbedThumbnail": "Embedding thumbnail",
    "Metadata": "Writing metadata",
    "EmbedSubtitle": "Embedding subtitles",
    "SponsorBlock": "Finding sponsor segments",
    "ModifyChapters": "Removing segments",
    "VideoRemuxer": "Remuxing",
    "VideoConvertor": "Converting",
    "ThumbnailsConvertor": "Converting thumbnail",
    "SubtitlesConvertor": "Converting subtitles",
    "FixupM3u8": "Fixing container",
    "FixupM4a": "Fixing container",
    "FixupStretched": "Fixing aspect ratio",
    "FixupDuplicateMoov": "Fixing container",
    "FixupTimestamp": "Fixing timestamps",
    "MoveFiles": "Moving files",
    "MoveFilesAfterDownload": "Moving files",
}  # keys are yt-dlp's PostProcessor.pp_key(): class name minus "FFmpeg" prefix and "PP" suffix


def _num(text: str) -> float | None:
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


@dataclass
class Job:
    id: int
    url: str
    options: DownloadOptions
    status: Status = Status.QUEUED
    title: str = ""
    playlist_title: str = ""
    item_index: int = 0
    item_count: int = 0
    phase: str = ""
    progress: float | None = None  # 0..1 for the current file; None while unknown
    downloaded: float | None = None
    total: float | None = None
    speed: float | None = None
    eta: float | None = None
    files: list[str] = field(default_factory=list)
    error: str = ""
    warnings: list[str] = field(default_factory=list)
    log: deque[str] = field(default_factory=lambda: deque(maxlen=3000))
    log_seq: int = 0  # lines ever added to log (which drops old ones), so viewers can append only new lines
    started_at: float = 0.0
    finished_at: float = 0.0
    _formats_seen: list[str] = field(default_factory=list)

    @property
    def display_title(self) -> str:
        title = self.title or self.url
        if self.item_count > 1:
            prefix = f"{self.playlist_title} · " if self.playlist_title else ""
            return f"{prefix}{self.item_index}/{self.item_count} · {title}"
        return title

    def reset_for_run(self) -> None:
        self.status = Status.RUNNING
        self.phase = "Starting"
        self.progress = None
        self.downloaded = self.total = self.speed = self.eta = None
        self.error = ""
        self.warnings.clear()
        self.files.clear()
        self.item_index = self.item_count = 0
        self._formats_seen.clear()
        self.started_at = time.time()
        self.finished_at = 0.0
        self.add_log_line("")  # keeps log_seq moving so viewers notice the reset
        self.log.clear()

    def add_log_line(self, line: str) -> None:
        self.log.append(line)
        self.log_seq += 1

    # --- yt-dlp output ---------------------------------------------------------------------------
    def apply_line(self, line: str) -> None:
        if line.startswith(MARK_PROGRESS):
            self._on_progress(line[len(MARK_PROGRESS):].split(FIELD_SEP))
            return  # progress lines would drown the log
        self.add_log_line(line)
        if line.startswith(MARK_ITEM):
            self._on_item(line[len(MARK_ITEM):].split(FIELD_SEP))
        elif line.startswith(MARK_POSTPROCESS):
            parts = line[len(MARK_POSTPROCESS):].split(FIELD_SEP)
            if parts and parts[0] and (len(parts) < 2 or parts[1] != "finished"):
                self.status = Status.PROCESSING
                self.phase = POSTPROCESSOR_LABELS.get(parts[0], parts[0])
                self.speed = self.eta = None
        elif line.startswith(MARK_FILE):
            path = line[len(MARK_FILE):].strip()
            if path and path != "NA" and path not in self.files:
                self.files.append(path)
        elif line.startswith("ERROR:"):
            self.error = line[len("ERROR:"):].strip()
        elif line.startswith("WARNING:"):
            self.warnings.append(line[len("WARNING:"):].strip())
        elif line.startswith("[download] Downloading playlist:"):
            self.playlist_title = line.split(":", 1)[1].strip()
        elif line.startswith("[download] Downloading item ") or line.startswith("[download] Downloading video "):
            words = line.split()
            # "[download] Downloading item 3 of 12"
            if len(words) >= 6 and words[-2] == "of" and words[-1].isdigit() and words[-3].isdigit():
                self.item_index, self.item_count = int(words[-3]), int(words[-1])
        elif "has already been downloaded" in line:
            self.phase = "Already downloaded"
            self.progress = 1.0

    def _on_item(self, parts: list[str]) -> None:
        parts += [""] * (4 - len(parts))
        _id, title, index, count = parts[:4]
        self.title = title
        if index.isdigit():
            self.item_index = int(index)
        if count.isdigit():
            self.item_count = int(count)
        self._formats_seen.clear()
        self.status = Status.RUNNING
        self.phase = "Starting"
        self.progress = None
        self.downloaded = self.total = self.speed = self.eta = None

    def _on_progress(self, parts: list[str]) -> None:
        parts += [""] * (7 - len(parts))
        state, done, total, estimate, speed, eta, format_id = parts[:7]
        if format_id and format_id != "NA" and format_id not in self._formats_seen:
            self._formats_seen.append(format_id)
        self.status = Status.RUNNING
        self.downloaded = _num(done)
        self.total = _num(total) or _num(estimate)
        self.speed = _num(speed)
        self.eta = _num(eta)
        if state == "finished":
            self.progress = 1.0
            self.speed = self.eta = None
        elif self.downloaded is not None and self.total:
            self.progress = max(0.0, min(1.0, self.downloaded / self.total))
        part = len(self._formats_seen)
        self.phase = "Downloading" + (f" (part {part})" if part > 1 else "")

    def finish(self, returncode: int | None, cancelled: bool) -> None:
        self.finished_at = time.time()
        self.speed = self.eta = None
        if cancelled:
            self.status = Status.CANCELLED
            self.phase = ""
        elif returncode == 0:
            self.status = Status.DONE
            self.progress = 1.0
            self.phase = ""
            self.error = ""
        else:
            self.status = Status.PARTIAL if self.files else Status.FAILED
            self.phase = ""
            if not self.error:
                self.error = f"yt-dlp exited with code {returncode}"

    # --- persistence -----------------------------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "options": self.options.to_dict(),
            "status": self.status.name,
            "title": self.title,
            "playlist_title": self.playlist_title,
            "files": self.files,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, job_id: int, data: dict) -> Job:
        job = cls(job_id, data["url"], DownloadOptions.from_dict(data.get("options")))
        status = Status.__members__.get(data.get("status", ""), Status.QUEUED)
        # Anything that was mid-download when the app closed starts over (yt-dlp resumes .part files).
        job.status = Status.QUEUED if status.active else status
        job.title = data.get("title", "")
        job.playlist_title = data.get("playlist_title", "")
        job.files = list(data.get("files") or [])
        job.error = data.get("error", "")
        if job.status in (Status.DONE, Status.PARTIAL):
            job.progress = 1.0
        return job
