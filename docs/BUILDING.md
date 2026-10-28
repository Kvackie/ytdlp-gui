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

## Trying failed and partial downloads

`devtools/test_server.py` serves downloads that fail on purpose, to try Retry, Cancel, Remove and
*Retry from scratch* with the real yt-dlp:

```bash
python devtools/test_server.py      # needs FFmpeg once, to make the test video
```

Open http://127.0.0.1:8765/ for links to paste into the app (reload the page for fresh names):

| Link | What happens |
| --- | --- |
| `/ok/NAME.mp4` | downloads normally |
| `/flaky/NAME.mp4` | breaks off halfway and the server refuses connections for 20 s: **Failed**, with a `.part` file. Retry after the 20 s and the log shows *Resuming download at byte …* |
| `/broken/NAME.mp4` | breaks off halfway and never recovers: always **Failed**. Remove (or *Retry from scratch*) deletes the `.part` file |
| `/missing/NAME.mp4` | 404: **Failed** at once, nothing written |
| `/playlist/NAME.html` | three videos, the middle one flaky: **Done with errors** at first, **Done** after a Retry (tick *Whole playlist*) |
| `/partial/NAME.html` | three videos, the middle one missing: always **Done with errors** (tick *Whole playlist*) |

Cancel any download midway to see its files deleted.

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
| `ytdlp_gui/components.py` | the app itself, yt-dlp / FFmpeg / Deno: which build fits, install, update, remove |
| `ytdlp_gui/options.py` | download options → yt-dlp command line |
| `ytdlp_gui/jobs.py` | a queued download and how yt-dlp's output updates it |
| `ytdlp_gui/cleanup.py` | which files an unfinished download left behind, and deleting them |
| `ytdlp_gui/gui/` | Qt windows, the queue runner and the update service |
| `packaging/` | PyInstaller spec, entry point with self-test, icon |
| `devtools/` | local server with downloads that fail on purpose |

Progress is read from yt-dlp's `--progress-template` and `--print` output (marked `[ytg:…]`), not from its
human-readable log, so it doesn't break when that wording changes.
