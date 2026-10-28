# yt-dlp GUI

A desktop app for downloading video and audio with [yt-dlp](https://github.com/yt-dlp/yt-dlp), from
YouTube and [the thousands of other sites](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md) it supports.

It is a **single, portable file** for Windows and Linux (Debian 12 and newer). There is nothing to install:
on first start it downloads yt-dlp, FFmpeg and Deno, keeps them up to date, and updates itself too.

![Main window](docs/screenshot.png)

## Download

Get the file for your system from the [latest release](../../releases/latest):

| System | File |
| --- | --- |
| Windows 10/11 (64-bit) | `ytdlp-gui-windows-x64.exe` |
| Linux x86-64 (Debian 12+, Ubuntu 22.04+, …) | `ytdlp-gui-linux-x86_64` |

Put it in a folder of its own (it keeps its data next to itself, see [below](#where-things-are-kept)),
then:

- **Windows:** double-click the `.exe`. SmartScreen may warn about an unrecognized app the first time:
  choose *More info → Run anyway*.
- **Linux:** make it executable once, then start it:
  ```bash
  chmod +x ytdlp-gui-linux-x86_64
  ```

On first start a short setup offers to download the tools it needs (about 150–250 MB in total).

## What it does

- **Paste and go:** paste one or many links (or drag them onto the window) and they download in the
  background, a few at a time.
- **Video or audio:** best quality or capped at 2160p / 1440p / 1080p / 720p / …, as MP4, MKV or WebM;
  or audio only as MP3, M4A, Opus, FLAC or WAV.
- **Choose the exact format:** *Choose format…* lists every stream a video offers so you can pick one
  (or a video plus an audio stream).
- **Playlists and channels** go into their own folder, numbered; pick items such as `1-10,15`.
- **Extras:** subtitles (embedded or as files), thumbnails and metadata in the file, chapters,
  SponsorBlock cutting, browser cookies for age-restricted or members-only videos, speed limit, proxy,
  "skip what I already downloaded", any other yt-dlp option you want to add, and custom file names with
  a live preview under *Tools → Preferences → Files*.
- **A queue you control:** *Pause queue* lets running downloads finish but starts no new ones until you
  click *Resume queue*; adding links never resumes it. The queue survives restarts, and unfinished
  downloads continue where they left off.
- **No broken files left behind:**
  - A failed download keeps what it got so far, and *Retry* continues from there.
    Right-click → *Retry from scratch* starts over.
  - Cancelling a download deletes its files. Removing a failed download deletes its downloaded parts.
  - *Clear* removes finished and cancelled downloads and keeps failed ones for retrying.
- Light and dark theme (or follow the system).

## Updates

Everything is downloaded from the official GitHub releases and checked against the checksums published
with them before it is used.

| What | Why | Where it comes from |
| --- | --- | --- |
| yt-dlp GUI | this app | [its releases](../../releases) |
| yt-dlp | the downloader itself | [yt-dlp releases](https://github.com/yt-dlp/yt-dlp/releases) (stable, nightly or master channel) |
| FFmpeg | merging video and audio, converting, embedding | [BtbN's builds](https://github.com/BtbN/FFmpeg-Builds) of the stable FFmpeg releases |
| Deno | JavaScript runtime yt-dlp needs for full YouTube support | [Deno releases](https://github.com/denoland/deno/releases) |

By default the app looks for updates when it starts:

- **yt-dlp and Deno** update by themselves, once running downloads have finished.
- **FFmpeg** updates are offered under *Tools → Tools & updates*. That's also where you switch yt-dlp
  to the nightly channel when a site breaks.
- **The app itself:** a new release is offered there too. It replaces the executable in place (same
  file name) and is used after a restart; downloads keep running meanwhile.

If FFmpeg or Deno are already installed on your system (e.g. `apt install ffmpeg`), those copies are
used and not downloaded. yt-dlp is the exception: the app still offers its own copy, because an outdated
system yt-dlp is the most common reason downloads break.

Version 0.1.0 can't update itself: download a newer version by hand once and replace the old file.

## Where things are kept

The app is fully portable. Settings, the queue and the tools live in a `ytdlp-gui-data` folder that it
creates next to the executable; nothing is written to your user profile or the registry. Move or copy the
executable and that folder together, e.g. to a USB stick. Deleting both removes every trace.

The executable has to be somewhere you can write to; it tells you if it can't create its folder (e.g. in
`C:\Program Files` or `/usr/bin`).

## Troubleshooting

- **A download fails with "Sign in to confirm you're not a bot" or "This video is age-restricted":**
  choose your browser under *Preferences → Network → Cookies from browser*.
- **A site that used to work fails:** check for updates under *Tools → Tools & updates*, or switch the
  yt-dlp channel to *Nightly*.
- **A download keeps failing at the same point:** right-click it → *Retry from scratch*.
- **Details:** select a download to see yt-dlp's complete output in the log below the queue.

## Building from source

See [docs/BUILDING.md](docs/BUILDING.md), which also covers a local test server with downloads that fail
on purpose.
