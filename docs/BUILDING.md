# Building and development

## Run from source

Python 3.11+ (Debian 12's `python3` works).

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt     # Windows: .venv\Scripts\pip ...
./run.sh                                           # Windows: run.bat
```

Run from source, the app keeps its data (settings, queue, tools) in `ytdlp-gui-data/` in the checkout,
which git ignores. Set `YTDLP_GUI_DATA=/some/folder` to use a different data folder.

## Tests and lint

```bash
python -m ruff check .
QT_QPA_PLATFORM=offscreen python -m pytest -q
```

The tests use a stand-in for yt-dlp and need no network.

## Single-file executables

```bash
python packaging/version_info.py     # Windows file properties
pyinstaller packaging/ytdlp-gui.spec --noconfirm --distpath dist --workpath build
dist/ytdlp-gui --self-test result.json --install
```

PyInstaller does not cross-compile: build the Windows file on Windows and the Linux file on Linux. On Linux,
build on the oldest distribution you want to support (its glibc is the minimum), with the Qt xcb libraries
installed so they get bundled; see the workflow for the package list.

`--self-test result.json` checks the frozen build without opening a window (bundled modules, TLS certificates,
the GUI offscreen); `--install` additionally downloads the real yt-dlp into a temporary folder and runs it.

## Releases

`.github/workflows/release.yml` builds and self-tests both executables on every push, then runs the Linux one
on clean Debian 12 and 13 containers. Push a tag to publish a release with both files and a `SHA256SUMS`:

```bash
git tag v0.2.0
git push origin v0.2.0
```

The version comes from the tag; `ytdlp_gui/__init__.py` holds the version for development builds.

## Layout

| Path | What |
| --- | --- |
| `ytdlp_gui/system.py` | data folder, platform/architecture detection, running and stopping child processes |
| `ytdlp_gui/net.py` | HTTP helpers, latest-release lookup, checksum parsing |
| `ytdlp_gui/components.py` | yt-dlp / FFmpeg / Deno: which build fits, install, update, remove |
| `ytdlp_gui/options.py` | download options → yt-dlp command line |
| `ytdlp_gui/jobs.py` | a queued download and how yt-dlp's output updates it |
| `ytdlp_gui/gui/` | Qt windows, the queue runner and the update service |
| `packaging/` | PyInstaller spec, entry point with self-test, icon |

Progress is read from yt-dlp's `--progress-template` and `--print` output (marked `[ytg:…]`), not from its
human-readable log, so it doesn't break when that wording changes.
