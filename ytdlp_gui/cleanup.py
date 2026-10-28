"""Finding and deleting what an unfinished download leaves behind.

yt-dlp names everything after the final file X.mp4: X.f137.mp4.part while a stream downloads,
X.f140.m4a while it waits to be merged, X.mp4.ytdl and X.mp4.part-Frag3 for fragmented downloads,
X.temp.mp4 while converting, X.webp and X.en.vtt while they wait to be embedded.

Two levels:
- leftovers of a failed download are only those temporary files. A retry resumes from them, and a
  complete file (perhaps from an earlier download) is never touched.
- a cancelled download also loses every other file of that item written since it started.
"""
from __future__ import annotations

import os
import re
import time
from collections.abc import Iterable
from pathlib import Path

# What follows "X." in a temporary file's name. Format ids contain a digit ("f137", "fhls-1080p"),
# which keeps subtitles such as "X.fr.vtt" out.
TEMP_RE = re.compile(r"f[\w-]*\d[\w-]*\.\w+(?:\.part)?|temp\.\w+|.+\.part(?:-Frag\d+(?:\.part)?)?|.+\.ytdl",
                     re.IGNORECASE)
MTIME_SLACK = 2.0  # seconds; some file systems store modification times coarsely


def leftovers(target: Path, since: float | None = None) -> list[Path]:
    """Files belonging to the unfinished download of `target` (the final path yt-dlp announced).

    With `since`, every file of that item modified since then counts, not just the temporary ones.
    """
    stem = target.stem
    try:
        entries = list(target.parent.iterdir())
    except OSError:
        return []
    found = []
    for path in entries:
        if not path.name.startswith(stem + ".") or not path.is_file():
            continue
        if TEMP_RE.fullmatch(path.name[len(stem) + 1:]):
            found.append(path)
        elif since is not None:
            try:
                if path.stat().st_mtime >= since - MTIME_SLACK:
                    found.append(path)
            except OSError:
                pass
    return found


def remove_leftovers(targets: Iterable[str], completed: Iterable[str], root: Path | None = None,
                     since: float | None = None, attempts: int = 5) -> list[Path]:
    """Delete the leftovers of every target that didn't complete; returns what was deleted.

    `completed` are the final files yt-dlp reported, so finished items of a playlist are kept.
    Folders emptied this way (e.g. a playlist's) are removed too, up to `root`.
    Deleting is retried briefly: on Windows a just-killed ffmpeg can hold its files for a moment.
    """
    done = {(str(Path(f).parent), Path(f).stem) for f in completed}
    deleted: list[Path] = []
    folders: set[Path] = set()
    for target in dict.fromkeys(targets):
        path = Path(target)
        if (str(path.parent), path.stem) in done:
            continue
        for leftover in leftovers(path, since):
            for attempt in range(attempts):
                try:
                    leftover.unlink(missing_ok=True)
                    deleted.append(leftover)
                    break
                except PermissionError:
                    if attempt + 1 < attempts:
                        time.sleep(0.4)
                except OSError:
                    break
        folders.add(path.parent)
    root = root.resolve() if root else None
    for folder in folders:
        _remove_empty(folder, root)
    return deleted


def _remove_empty(folder: Path, root: Path | None) -> None:
    folder = folder.resolve()
    while root is not None and folder != root and root in folder.parents:
        try:
            os.rmdir(folder)  # fails unless empty
        except OSError:
            return
        folder = folder.parent
