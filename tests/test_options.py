from pathlib import Path

from ytdlp_gui import options
from ytdlp_gui.options import DownloadOptions, ToolPaths, build_args, format_args, split_args

TOOLS = ToolPaths(ytdlp=Path("yt-dlp"), ffmpeg_dir=Path("ff"), deno=Path("deno/deno"), archive_file=Path("a.txt"))


def value_after(args: list[str], flag: str) -> str:
    return args[args.index(flag) + 1]


def test_default_video_is_best_merged():
    assert format_args(DownloadOptions()) == ["-f", "bv*+ba/b"]


def test_video_quality_and_mp4_container():
    args = format_args(DownloadOptions(quality="1080", container="mp4"))
    assert value_after(args, "-S") == "res:1080,ext:mp4:m4a"
    assert value_after(args, "--merge-output-format") == "mp4"
    assert value_after(args, "--remux-video") == "mp4"


def test_audio_conversion():
    args = format_args(DownloadOptions(mode="audio", audio_format="mp3", audio_quality="192 kbps"))
    assert args[:3] == ["-f", "ba/b", "-x"]
    assert value_after(args, "--audio-format") == "mp3"
    assert value_after(args, "--audio-quality") == "192K"


def test_audio_original_format_skips_conversion():
    args = format_args(DownloadOptions(mode="audio"))
    assert "--audio-format" not in args


def test_custom_format_overrides_presets():
    args = format_args(DownloadOptions(mode="video", quality="720", custom_format="137+140", container="mkv"))
    assert args == ["-f", "137+140", "--merge-output-format", "mkv"]


def test_full_command_line():
    o = DownloadOptions(output_dir="/out", subtitles=True, sponsorblock=True, cookies_browser="firefox",
                        rate_limit="2M", use_archive=True, extra_args="--concurrent-fragments 4")
    args = build_args(o, ["https://example.com/v"], TOOLS)
    assert args[0] == "yt-dlp"
    assert args[-2:] == ["--", "https://example.com/v"]
    assert value_after(args, "-P") == "/out"
    assert value_after(args, "-o") == options.DEFAULT_TEMPLATE
    assert value_after(args, "--ffmpeg-location") == "ff"
    assert value_after(args, "--js-runtimes") == f"deno:{Path('deno/deno')}"
    assert value_after(args, "--cookies-from-browser") == "firefox"
    assert value_after(args, "--download-archive") == "a.txt"
    assert value_after(args, "-r") == "2M"
    assert value_after(args, "--sponsorblock-remove") == o.sponsorblock_categories
    assert "--no-playlist" in args and "--embed-subs" in args and "--ignore-config" in args
    assert value_after(args, "--concurrent-fragments") == "4"


def test_playlist_uses_playlist_template_and_items():
    args = build_args(DownloadOptions(playlist=True, playlist_items="1-3"), ["u"], TOOLS)
    assert "--yes-playlist" in args
    assert value_after(args, "-o") == options.PLAYLIST_TEMPLATE
    assert value_after(args, "-I") == "1-3"


def test_audio_mode_never_embeds_subtitles():
    args = build_args(DownloadOptions(mode="audio", subtitles=True), ["u"], TOOLS)
    assert "--write-subs" not in args


def test_wav_skips_thumbnail():
    args = build_args(DownloadOptions(mode="audio", audio_format="wav"), ["u"], TOOLS)
    assert "--embed-thumbnail" not in args


def test_split_args_keeps_quoted_values():
    assert split_args('--proxy "socks5://h:1" -x') == ["--proxy", "socks5://h:1", "-x"]
    assert split_args("   ") == []


def test_options_roundtrip_ignores_unknown_keys():
    o = DownloadOptions(mode="audio", audio_format="flac")
    data = o.to_dict() | {"removed_in_a_later_version": 1}
    assert DownloadOptions.from_dict(data) == o
