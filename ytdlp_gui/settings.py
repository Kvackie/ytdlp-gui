"""User preferences, kept as JSON in the data folder."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from . import system
from .options import DownloadOptions


@dataclass
class Settings:
    options: DownloadOptions = field(default_factory=DownloadOptions)
    max_concurrent: int = 2
    auto_start: bool = True
    ytdlp_channel: str = "stable"
    check_updates: bool = True
    auto_update: bool = True  # install yt-dlp and Deno updates without asking (FFmpeg is only offered)
    last_update_check: float = 0.0
    theme: str = "system"  # system | light | dark
    watch_clipboard: bool = False
    setup_done: bool = False
    window_geometry: str = ""
    window_state: str = ""

    @staticmethod
    def path() -> Path:
        return system.data_dir() / "settings.json"

    @classmethod
    def load(cls) -> Settings:
        try:
            data = json.loads(cls.path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        names = {f.name for f in fields(cls)} - {"options"}
        settings = cls(**{k: v for k, v in data.items() if k in names})
        settings.options = DownloadOptions.from_dict(data.get("options"))
        if not settings.options.output_dir:
            settings.options.output_dir = str(system.default_download_dir())
        settings.max_concurrent = max(1, min(8, int(settings.max_concurrent)))
        return settings

    def save(self) -> None:
        path = self.path()
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        os.replace(tmp, path)
