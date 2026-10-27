"""Download options and their translation into a yt-dlp command line."""
from __future__ import annotations

import shlex
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from . import system

VIDEO_QUALITIES = ["best", "2160", "1440", "1080", "720", "480", "360"]
VIDEO_CONTAINERS = ["auto", "mp4", "mkv", "webm"]
AUDIO_FORMATS = ["best", "mp3", "m4a", "opus", "flac", "wav"]
AUDIO_QUALITIES = {"best": "0", "320 kbps": "320K", "256 kbps": "256K", "192 kbps": "192K", "128 kbps": "128K"}
COOKIE_BROWSERS = ["", "firefox", "chrome", "chromium", "edge", "brave", "opera", "vivaldi", "librewolf", "safari"]
DEFAULT_TEMPLATE = "%(title)s [%(id)s].%(ext)s"
# "&{} - " prefixes the index only when there is one; links that aren't playlists land in "Single videos".
PLAYLIST_TEMPLATE = "%(playlist_title|Single videos)s/%(playlist_index&{} - |)s" + DEFAULT_TEMPLATE

# Markers in our own --print/--progress-template output, so it can be told apart from yt-dlp's log.
MARK_ITEM = "[ytg:item]"
MARK_PROGRESS = "[ytg:progress]"
MARK_POSTPROCESS = "[ytg:pp]"
MARK_FILE = "[ytg:file]"
FIELD_SEP = "\x1f"  # unit separator: never part of a title or path


@dataclass
class DownloadOptions:
    mode: str = "video"  # "video" | "audio"
    quality: str = "best"  # VIDEO_QUALITIES
    container: str = "auto"  # VIDEO_CONTAINERS
    audio_format: str = "best"  # AUDIO_FORMATS
    audio_quality: str = "best"  # key of AUDIO_QUALITIES
    custom_format: str = ""  # a yt-dlp -f selector; overrides mode/quality when set

    output_dir: str = ""
    filename_template: str = DEFAULT_TEMPLATE
    playlist: bool = False
    playlist_template: str = PLAYLIST_TEMPLATE
    playlist_items: str = ""

    subtitles: bool = False
    subtitle_langs: str = "en.*,en"
    auto_subtitles: bool = False
    embed_subtitles: bool = True
    embed_thumbnail: bool = True
    embed_metadata: bool = True
    embed_chapters: bool = True
    sponsorblock: bool = False
    sponsorblock_categories: str = "sponsor,selfpromo,interaction"

    cookies_browser: str = ""
    cookies_file: str = ""
    rate_limit: str = ""
    proxy: str = ""
    restrict_filenames: bool = False
    use_archive: bool = False
    extra_args: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> DownloadOptions:
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (data or {}).items() if k in names})

    def summary(self) -> str:
        """Short label for the queue's "Format" column."""
        if self.custom_format:
            return f"Custom ({self.custom_format})"
        if self.mode == "audio":
            fmt = "best" if self.audio_format == "best" else self.audio_format.upper()
            return f"Audio · {fmt}"
        quality = "best" if self.quality == "best" else f"≤{self.quality}p"
        container = "" if self.container == "auto" else f" · {self.container.upper()}"
        return f"Video · {quality}{container}"


@dataclass
class ToolPaths:
    ytdlp: Path
    ffmpeg_dir: Path | None = None
    deno: Path | None = None
    archive_file: Path | None = None


def split_args(text: str) -> list[str]:
    """Split user-supplied extra arguments the way the platform's shell would."""
    if not text.strip():
        return []
    if system.IS_WINDOWS:
        # posix=False keeps backslashes in Windows paths; strip the quotes it leaves around tokens.
        return [t[1:-1] if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'" else t
                for t in shlex.split(text, posix=False)]
    return shlex.split(text)


def format_args(o: DownloadOptions) -> list[str]:
    args: list[str] = []
    if o.custom_format:
        args += ["-f", o.custom_format]
        if o.container != "auto" and o.mode == "video":
            args += ["--merge-output-format", o.container]
        return args

    if o.mode == "audio":
        args += ["-f", "ba/b", "-x"]
        if o.audio_format != "best":
            args += ["--audio-format", o.audio_format]
            args += ["--audio-quality", AUDIO_QUALITIES.get(o.audio_quality, "0")]
        return args

    args += ["-f", "bv*+ba/b"]
    sort = []
    if o.quality != "best":
        sort.append(f"res:{o.quality}")
    if o.container == "mp4":
        sort.append("ext:mp4:m4a")  # streams that fit mp4 without re-encoding
    elif o.container == "webm":
        sort.append("ext:webm:webm")
    if sort:
        args += ["-S", ",".join(sort)]
    if o.container != "auto":
        args += ["--merge-output-format", o.container, "--remux-video", o.container]
    return args


def build_args(o: DownloadOptions, urls: list[str], tools: ToolPaths) -> list[str]:
    """The complete yt-dlp command line for a job."""
    sep = FIELD_SEP
    args = [
        str(tools.ytdlp),
        "--newline",
        "--no-colors",
        "--encoding", "utf-8",
        "--no-quiet",
        "--no-simulate",
        "--ignore-config",  # a user's yt-dlp.conf must not break our output parsing
        "--progress-template",
        f"download:{MARK_PROGRESS}%(progress.status)s{sep}%(progress.downloaded_bytes)s{sep}"
        f"%(progress.total_bytes)s{sep}%(progress.total_bytes_estimate)s{sep}%(progress.speed)s{sep}"
        f"%(progress.eta)s{sep}%(info.format_id)s",
        "--progress-template", f"postprocess:{MARK_POSTPROCESS}%(progress.postprocessor)s{sep}%(progress.status)s",
        "-O", f"video:{MARK_ITEM}%(id)s{sep}%(title)s{sep}%(playlist_index|)s{sep}%(n_entries|)s",
        "-O", f"after_move:{MARK_FILE}%(filepath)s",
    ]
    if tools.ffmpeg_dir:
        args += ["--ffmpeg-location", str(tools.ffmpeg_dir)]
    if tools.deno:
        args += ["--js-runtimes", f"deno:{tools.deno}"]

    args += format_args(o)

    if o.output_dir:
        args += ["-P", o.output_dir]
    template = o.playlist_template if o.playlist and o.playlist_template else o.filename_template
    if template:
        args += ["-o", template]
    args.append("--yes-playlist" if o.playlist else "--no-playlist")
    if o.playlist and o.playlist_items.strip():
        args += ["-I", o.playlist_items.strip()]

    if o.subtitles and o.mode == "video":
        args += ["--write-subs", "--sub-langs", o.subtitle_langs or "en.*"]
        if o.auto_subtitles:
            args.append("--write-auto-subs")
        if o.embed_subtitles:
            args.append("--embed-subs")
    if o.embed_thumbnail and not (o.mode == "audio" and o.audio_format == "wav"):
        args.append("--embed-thumbnail")
    if o.embed_metadata:
        args.append("--embed-metadata")
    if o.embed_chapters:
        args.append("--embed-chapters")
    if o.sponsorblock and o.sponsorblock_categories.strip():
        args += ["--sponsorblock-remove", o.sponsorblock_categories.strip()]

    if o.cookies_browser:
        args += ["--cookies-from-browser", o.cookies_browser]
    elif o.cookies_file:
        args += ["--cookies", o.cookies_file]
    if o.rate_limit.strip():
        args += ["-r", o.rate_limit.strip()]
    if o.proxy.strip():
        args += ["--proxy", o.proxy.strip()]
    if o.restrict_filenames:
        args.append("--restrict-filenames")
    if o.use_archive and tools.archive_file:
        args += ["--download-archive", str(tools.archive_file)]

    args += split_args(o.extra_args)
    args.append("--")
    args += urls
    return args


def info_args(url: str, tools: ToolPaths, o: DownloadOptions | None = None) -> list[str]:
    """Command line that prints a single video's metadata (with its format list) as JSON."""
    args = [str(tools.ytdlp), "-J", "--no-playlist", "--flat-playlist", "--no-warnings", "--encoding", "utf-8",
            "--ignore-config"]
    if tools.deno:
        args += ["--js-runtimes", f"deno:{tools.deno}"]
    if o is not None:
        if o.cookies_browser:
            args += ["--cookies-from-browser", o.cookies_browser]
        elif o.cookies_file:
            args += ["--cookies", o.cookies_file]
        if o.proxy.strip():
            args += ["--proxy", o.proxy.strip()]
    return [*args, "--", url]
