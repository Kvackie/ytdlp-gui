"""Runs queued jobs as yt-dlp processes, a few at a time."""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import threading
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal

from .. import system
from ..jobs import Job, Status
from ..options import FIELD_SEP, DownloadOptions, ToolPaths, build_args


class QueueManager(QObject):
    job_added = Signal(object)
    job_changed = Signal(int)
    job_removed = Signal(int)
    job_finished = Signal(object)
    activity_changed = Signal()  # number of running jobs or the paused state changed
    tools_missing = Signal()

    _line = Signal(int, str)
    _exited = Signal(int, object)

    def __init__(self, tools: Callable[[], ToolPaths | None], max_concurrent: int = 2, paused: bool = False):
        super().__init__()
        self.jobs: dict[int, Job] = {}
        self._tools = tools
        self._procs: dict[int, subprocess.Popen] = {}
        self._cancelling: set[int] = set()
        self._next_id = 1
        self.max_concurrent = max_concurrent
        self.paused = paused
        self.blocked = False  # set while yt-dlp or its helpers are being replaced
        self._line.connect(self._on_line, Qt.ConnectionType.QueuedConnection)
        self._exited.connect(self._on_exit, Qt.ConnectionType.QueuedConnection)

    # --- queries ---------------------------------------------------------------------------------
    @property
    def running(self) -> int:
        return len(self._procs)

    def count(self, *statuses: Status) -> int:
        return sum(1 for j in self.jobs.values() if j.status in statuses)

    def has_url(self, url: str) -> bool:
        return any(j.url == url and not j.status.finished for j in self.jobs.values())

    # --- changes ---------------------------------------------------------------------------------
    def add(self, urls: list[str], options: DownloadOptions) -> list[Job]:
        added = []
        for url in urls:
            job = Job(self._next_id, url, replace(options))
            self._next_id += 1
            self.jobs[job.id] = job
            added.append(job)
            self.job_added.emit(job)
        self.schedule()
        return added

    def set_paused(self, paused: bool) -> None:
        self.paused = paused
        self.activity_changed.emit()
        self.schedule()

    def set_blocked(self, blocked: bool) -> None:
        self.blocked = blocked
        self.schedule()

    def set_max_concurrent(self, value: int) -> None:
        self.max_concurrent = max(1, value)
        self.schedule()

    def cancel(self, ids: list[int]) -> None:
        for job_id in ids:
            job = self.jobs.get(job_id)
            if not job:
                continue
            proc = self._procs.get(job_id)
            if proc is not None:
                if job_id not in self._cancelling:
                    self._cancelling.add(job_id)
                    job.phase = "Cancelling"
                    self.job_changed.emit(job_id)
                    threading.Thread(target=system.kill_tree, args=(proc,), daemon=True).start()
            elif job.status == Status.QUEUED:
                job.status = Status.CANCELLED
                self.job_changed.emit(job_id)

    def retry(self, ids: list[int]) -> None:
        for job_id in ids:
            job = self.jobs.get(job_id)
            if job and job.status.finished:
                job.status = Status.QUEUED
                job.error = ""
                job.progress = None
                job.phase = ""
                self.job_changed.emit(job_id)
        self.schedule()

    def remove(self, ids: list[int]) -> None:
        self.cancel([i for i in ids if i in self._procs])
        for job_id in ids:
            if job_id in self.jobs:
                del self.jobs[job_id]
                self.job_removed.emit(job_id)

    def clear_finished(self) -> None:
        """Drop every job that is neither queued nor running: done, failed, partial and cancelled ones."""
        self.remove([j.id for j in self.jobs.values() if j.status.finished])

    def shutdown(self) -> None:
        """Stop every running download (on quit)."""
        for proc in list(self._procs.values()):
            system.kill_tree(proc)

    # --- scheduling ------------------------------------------------------------------------------
    def schedule(self) -> None:
        if self.paused or self.blocked:
            return
        while self.running < self.max_concurrent:
            job = next((j for j in self.jobs.values() if j.status == Status.QUEUED), None)
            if job is None:
                return
            if not self._start(job):
                return

    def _start(self, job: Job) -> bool:
        tools = self._tools()
        if tools is None:
            # Only the user pauses the queue; jobs simply wait until yt-dlp is installed.
            self.tools_missing.emit()
            return False

        args = build_args(job.options, [job.url], tools)
        job.reset_for_run()
        shown = subprocess.list2cmdline(args) if system.IS_WINDOWS else shlex.join(args)
        job.add_log_line("$ " + shown.replace(FIELD_SEP, "|"))
        out_dir = Path(job.options.output_dir or system.default_download_dir())
        extra_path = [p for p in (tools.ffmpeg_dir, tools.deno.parent if tools.deno else None) if p]
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            proc = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                cwd=str(out_dir),
                env=system.child_env(extra_path),
                **system.popen_kwargs(),
            )
        except OSError as exc:
            job.error = f"Could not start yt-dlp: {exc}"
            job.finish(None, cancelled=False)
            self.job_changed.emit(job.id)
            self.job_finished.emit(job)
            return True  # keep going with the next job

        self._procs[job.id] = proc
        threading.Thread(target=self._pump, args=(job.id, proc), daemon=True).start()
        self.job_changed.emit(job.id)
        self.activity_changed.emit()
        return True

    def _pump(self, job_id: int, proc: subprocess.Popen) -> None:
        """Worker thread: forward yt-dlp's output line by line, then its exit code."""
        assert proc.stdout is not None
        for raw in proc.stdout:
            self._line.emit(job_id, raw.decode("utf-8", "replace").rstrip("\r\n"))
        self._exited.emit(job_id, proc.wait())

    def _on_line(self, job_id: int, line: str) -> None:
        job = self.jobs.get(job_id)
        if job and line:
            job.apply_line(line)
            self.job_changed.emit(job_id)

    def _on_exit(self, job_id: int, returncode: int) -> None:
        self._procs.pop(job_id, None)
        cancelled = job_id in self._cancelling
        self._cancelling.discard(job_id)
        job = self.jobs.get(job_id)
        if job:
            job.finish(returncode, cancelled)
            self.job_changed.emit(job_id)
            self.job_finished.emit(job)
        self.activity_changed.emit()
        self.schedule()

    # --- persistence -----------------------------------------------------------------------------
    def save(self, path: Path) -> None:
        data = [j.to_dict() for j in self.jobs.values()]
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        os.replace(tmp, path)

    def load(self, path: Path) -> None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for item in data if isinstance(data, list) else []:
            try:
                job = Job.from_dict(self._next_id, item)
            except (KeyError, TypeError):
                continue
            self._next_id += 1
            self.jobs[job.id] = job
            self.job_added.emit(job)
