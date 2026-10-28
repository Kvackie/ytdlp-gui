"""The external tools the app drives (yt-dlp, ffmpeg, deno): finding, installing and updating them.

Everything is downloaded from the projects' official GitHub releases into the app's data folder and
checked against the published SHA-256 checksums before it replaces the current copy.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import stat
import sys
import tarfile
import threading
import time
import urllib.error
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import APP_NAME, __version__, net, system

APP_REPO = "Kvackie/ytdlp-gui"
YTDLP_CHANNELS = {
    "stable": "yt-dlp/yt-dlp",
    "nightly": "yt-dlp/yt-dlp-nightly-builds",
    "master": "yt-dlp/yt-dlp-master-builds",
}
FFMPEG_REPO = "yt-dlp/FFmpeg-Builds"
DENO_REPO = "denoland/deno"
# ffmpeg master builds are re-published daily; only suggest replacing a build once it is this old.
FFMPEG_UPDATE_AGE_DAYS = 30


@dataclass
class Release:
    ident: str  # what identifies the build: a version tag or, for rolling builds, the archive checksum
    version: str  # human-readable
    asset: str
    url: str
    sha256: str | None


class State:
    """Installed versions, stored next to the binaries in components.json."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        try:
            self._data: dict = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._data = {}

    def get(self, key: str) -> dict:
        with self._lock:
            return dict(self._data.get(key) or {})

    def set(self, key: str, value: dict | None) -> None:
        with self._lock:
            if value is None:
                self._data.pop(key, None)
            else:
                self._data[key] = value
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)


ProgressFn = Callable[[str, int, int], None]  # (phase text, done, total)


class Component:
    key = ""
    title = ""
    description = ""
    required = False
    download_size = ""  # rough, shown before the first install
    version_args: tuple[str, ...] = ("--version",)

    def __init__(self, state: State):
        self.state = state

    # --- where it lives --------------------------------------------------------------------------
    def asset_name(self) -> str | None:
        raise NotImplementedError

    def supported(self) -> bool:
        return self.asset_name() is not None

    def managed_path(self) -> Path:
        raise NotImplementedError

    def system_path(self) -> Path | None:
        found = shutil.which(self.key)
        if found and Path(found).resolve() != self.managed_path().resolve():
            return Path(found)
        return None

    def is_managed(self) -> bool:
        return self.managed_path().is_file()

    def offered(self) -> bool:
        """Whether to offer our own copy. Not when the system provides one, except for yt-dlp: an outdated
        system yt-dlp (e.g. Debian's package) is the usual reason downloads break."""
        return self.supported() and (self.is_managed() or self.required or not self.system_path())

    def path(self) -> Path | None:
        """The binary to use: our own copy if there is one, otherwise one from PATH."""
        if self.is_managed():
            return self.managed_path()
        return self.system_path()

    def installed_version(self) -> str | None:
        if not self.is_managed():
            return None
        return self.state.get(self.key).get("version") or self.probe_version(self.managed_path())

    def probe_version(self, path: Path) -> str | None:
        try:
            out = system.run_quiet([str(path), *self.version_args], timeout=60)
        except Exception:  # noqa: BLE001 - any failure means "unknown"
            return None
        if out.returncode != 0:
            return None
        return self.parse_version(out.stdout.decode("utf-8", "replace"))

    def parse_version(self, output: str) -> str | None:
        line = output.strip().splitlines()[0] if output.strip() else ""
        return line or None

    # --- updates ---------------------------------------------------------------------------------
    def latest(self) -> Release:
        raise NotImplementedError

    def update_available(self, release: Release) -> bool:
        if not self.is_managed():
            return False
        return self.state.get(self.key).get("ident") != release.ident

    def install(self, release: Release, progress: ProgressFn | None = None,
                cancelled: Callable[[], bool] | None = None) -> None:
        work = system.bin_dir() / f".{self.key}.download"
        if work.exists():
            shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True)
        try:
            archive = work / release.asset

            def report(done: int, total: int) -> None:
                if progress:
                    progress(f"Downloading {release.asset}", done, total)

            digest = net.download(release.url, archive, report, cancelled)
            if release.sha256 and digest != release.sha256:
                raise RuntimeError(
                    f"Checksum mismatch for {release.asset}: expected {release.sha256}, got {digest}. "
                    "The download was discarded."
                )
            if progress:
                progress("Installing", 0, 0)
            self._install_from(archive, work)
            version = self.probe_version(self.managed_path())
            if version is None:
                raise RuntimeError(f"{self.title} was downloaded but does not run on this system.")
            self.state.set(self.key, {
                "ident": release.ident,
                "version": version,
                "asset": release.asset,
                "installed_at": time.time(),
            })
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _install_from(self, archive: Path, work: Path) -> None:
        raise NotImplementedError

    def remove(self) -> None:
        target = self.managed_path()
        if target.parent != system.bin_dir():
            shutil.rmtree(target.parent, ignore_errors=False)
        elif target.exists():
            target.unlink()
        self.state.set(self.key, None)


def _make_executable(path: Path) -> None:
    if not system.IS_WINDOWS:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _replace_file(src: Path, dest: Path) -> None:
    try:
        os.replace(src, dest)
    except PermissionError as err:
        raise RuntimeError(f"Could not replace {dest.name}; it is probably still running. "
                           "Wait for downloads to finish and try again.") from err


def _replace_dir(src: Path, dest: Path) -> None:
    old = dest.with_name(dest.name + ".old")
    shutil.rmtree(old, ignore_errors=True)
    try:
        if dest.exists():
            os.replace(dest, old)
        os.replace(src, dest)
    except PermissionError as err:
        if old.exists() and not dest.exists():
            os.replace(old, dest)
        raise RuntimeError(f"Could not replace {dest.name}; it is probably still running. "
                           "Wait for downloads to finish and try again.") from err
    shutil.rmtree(old, ignore_errors=True)


def _extract(archive: Path, dest: Path, pick: Callable[[str], str | None]) -> list[Path]:
    """Copy the archive members for which `pick(member_path)` returns a file name into `dest`.

    Only plain file names are written, so a hostile archive cannot escape `dest`.
    """
    dest.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    def write(name: str, stream) -> None:
        out = dest / Path(name).name
        with open(out, "wb") as fh:
            shutil.copyfileobj(stream, fh, 1024 * 1024)
        _make_executable(out)
        written.append(out)

    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                name = pick(info.filename)
                if name:
                    with zf.open(info) as stream:
                        write(name, stream)
    else:
        with tarfile.open(archive) as tf:
            for member in tf:
                if not member.isfile():
                    continue
                name = pick(member.name)
                if name:
                    stream = tf.extractfile(member)
                    if stream is not None:
                        with stream:
                            write(name, stream)
    return written


# ---------------------------------------------------------------------------------------------------
class YtDlp(Component):
    key = "yt-dlp"
    title = "yt-dlp"
    description = "The downloader itself. Required."
    required = True
    download_size = "~25-40 MB"

    channel = "stable"  # key of YTDLP_CHANNELS, set from the settings

    def asset_name(self) -> str | None:
        arch = system.machine()
        if system.IS_WINDOWS:
            return {"x86_64": "yt-dlp.exe", "aarch64": "yt-dlp_arm64.exe", "x86": "yt-dlp_x86.exe"}.get(arch)
        if system.IS_LINUX:
            musl = "musl" if system.is_musl() else ""
            if arch == "x86_64":
                return f"yt-dlp_{musl}linux"
            if arch == "aarch64":
                return f"yt-dlp_{musl}linux_aarch64"
            # Other CPUs: the zipapp build, which runs on the system's python3.
            return "yt-dlp" if shutil.which("python3") else None
        return None

    def managed_path(self) -> Path:
        return system.bin_dir() / system.exe("yt-dlp")

    def repo(self) -> str:
        return YTDLP_CHANNELS.get(self.channel, YTDLP_CHANNELS["stable"])

    def latest(self) -> Release:
        asset = self.asset_name()
        if not asset:
            raise RuntimeError("yt-dlp has no build for this platform.")
        repo = self.repo()
        tag = net.latest_release_tag(repo)
        sums = net.get_text(net.release_asset_url(repo, tag, "SHA2-256SUMS"))
        sha = net.find_sha256(sums, asset)
        if not sha:
            raise RuntimeError(f"{asset} is missing from the checksums of yt-dlp {tag}.")
        return Release(f"{self.channel}:{tag}", tag, asset, net.release_asset_url(repo, tag, asset), sha)

    def update_available(self, release: Release) -> bool:
        if not self.is_managed():
            return False
        state = self.state.get(self.key)
        if state.get("ident"):
            return state["ident"] != release.ident
        return self.installed_version() != release.version

    def _install_from(self, archive: Path, work: Path) -> None:
        _make_executable(archive)
        _replace_file(archive, self.managed_path())


class Ffmpeg(Component):
    key = "ffmpeg"
    title = "FFmpeg"
    description = "Merges video and audio, converts audio, embeds thumbnails and subtitles. Recommended."
    download_size = "~90-160 MB"
    version_args = ("-version",)

    def asset_name(self) -> str | None:
        arch = system.machine()
        if system.IS_WINDOWS:
            # The "shared" builds are about half the size of the static ones.
            name = {"x86_64": "win64", "aarch64": "winarm64", "x86": "win32"}.get(arch)
            return f"ffmpeg-master-latest-{name}-gpl-shared.zip" if name else None
        if system.IS_LINUX and not system.is_musl():
            name = {"x86_64": "linux64", "aarch64": "linuxarm64"}.get(arch)
            return f"ffmpeg-master-latest-{name}-gpl.tar.xz" if name else None
        return None

    def managed_path(self) -> Path:
        return system.bin_dir() / "ffmpeg" / system.exe("ffmpeg")

    def location(self) -> Path | None:
        """What to hand to yt-dlp's --ffmpeg-location (it finds ffprobe next to ffmpeg)."""
        path = self.path()
        return path.parent if path else None

    def parse_version(self, output: str) -> str | None:
        match = re.search(r"ffmpeg version (\S+)", output)
        if not match:
            return None
        version = match.group(1)
        date = re.search(r"-(20\d\d)(\d\d)(\d\d)$", version)
        if date:
            version = f"{version[:date.start()]} ({date.group(1)}-{date.group(2)}-{date.group(3)})"
        return version

    def latest(self) -> Release:
        asset = self.asset_name()
        if not asset:
            raise RuntimeError("There is no FFmpeg build for this platform; install it with your package manager.")
        sums = net.get_text(net.release_asset_url(FFMPEG_REPO, "latest", "checksums.sha256"))
        sha = net.find_sha256(sums, asset)
        if not sha:
            raise RuntimeError(f"{asset} is missing from the FFmpeg build checksums.")
        return Release(sha, "latest build", asset, net.release_asset_url(FFMPEG_REPO, "latest", asset), sha)

    def update_available(self, release: Release) -> bool:
        if not super().update_available(release):
            return False
        installed_at = self.state.get(self.key).get("installed_at") or 0
        return time.time() - installed_at > FFMPEG_UPDATE_AGE_DAYS * 86400

    def _install_from(self, archive: Path, work: Path) -> None:
        def pick(member: str) -> str | None:
            parts = member.replace("\\", "/").split("/")
            if len(parts) >= 2 and parts[-2] == "bin" and not parts[-1].startswith("ffplay"):
                return parts[-1]
            return None

        staged = work / "ffmpeg"
        files = _extract(archive, staged, pick)
        if not any(f.name == system.exe("ffmpeg") for f in files):
            raise RuntimeError("The FFmpeg archive did not contain ffmpeg.")
        _replace_dir(staged, self.managed_path().parent)


class Deno(Component):
    key = "deno"
    title = "Deno"
    description = "JavaScript runtime yt-dlp needs for full YouTube support. Recommended."
    download_size = "~40 MB"

    def asset_name(self) -> str | None:
        arch = system.machine()
        if arch not in ("x86_64", "aarch64"):
            return None
        if system.IS_WINDOWS:
            return f"deno-{arch}-pc-windows-msvc.zip"
        if system.IS_LINUX and not system.is_musl():
            return f"deno-{arch}-unknown-linux-gnu.zip"
        return None

    def managed_path(self) -> Path:
        return system.bin_dir() / "deno" / system.exe("deno")

    def parse_version(self, output: str) -> str | None:
        match = re.search(r"deno (\S+)", output)
        return match.group(1) if match else None

    def latest(self) -> Release:
        asset = self.asset_name()
        if not asset:
            raise RuntimeError("Deno has no build for this platform.")
        tag = net.latest_release_tag(DENO_REPO)
        sums = net.get_text(net.release_asset_url(DENO_REPO, tag, asset + ".sha256sum"))
        sha = net.find_sha256(sums, asset) or net.find_sha256(sums)
        return Release(tag, tag.lstrip("v"), asset, net.release_asset_url(DENO_REPO, tag, asset), sha)

    def _install_from(self, archive: Path, work: Path) -> None:
        exe_name = system.exe("deno")
        staged = work / "deno"
        files = _extract(archive, staged, lambda m: exe_name if Path(m).name == exe_name else None)
        if not files:
            raise RuntimeError("The Deno archive did not contain the deno executable.")
        _replace_dir(staged, self.managed_path().parent)


def version_key(version: str) -> tuple:
    """Sortable form of "1.2.3"; a suffixed build such as "1.2.3-dev.4" sorts before "1.2.3"."""
    match = re.match(r"v?(\d+(?:\.\d+)*)(.*)", version.strip())
    if not match:
        return ((0, 0, 0, 0), 0)
    numbers = tuple(int(n) for n in match.group(1).split("."))[:4]
    return (numbers + (0,) * (4 - len(numbers)), 0 if match.group(2) else 1)


class App(Component):
    """This program. An update swaps the executable in place; it takes effect on the next start."""

    key = "app"
    title = APP_NAME
    description = "This program, updated from its GitHub releases."
    download_size = "~40 MB"

    def __init__(self, state: State):
        super().__init__(state)
        self.restart_pending = ""  # version installed by this run, used after a restart

    def asset_name(self) -> str | None:
        if not system.FROZEN or system.machine() != "x86_64":
            return None
        if system.IS_WINDOWS:
            return "ytdlp-gui-windows-x64.exe"
        if system.IS_LINUX and not system.is_musl():
            return "ytdlp-gui-linux-x86_64"
        return None

    def managed_path(self) -> Path:
        return Path(sys.executable).resolve()

    def system_path(self) -> Path | None:
        return None

    def is_managed(self) -> bool:
        return system.FROZEN

    def installed_version(self) -> str | None:
        return __version__

    def latest(self) -> Release:
        asset = self.asset_name()
        if not asset:
            raise RuntimeError(f"There is no {APP_NAME} build for this system.")
        try:
            tag = net.latest_release_tag(APP_REPO)
        except urllib.error.HTTPError as err:
            if err.code == 404:
                raise RuntimeError(f"No public releases found at github.com/{APP_REPO}.") from err
            raise
        url = net.release_asset_url(APP_REPO, tag, asset)
        if version_key(tag) <= version_key(__version__):
            return Release(tag, tag.lstrip("v"), asset, url, None)  # nothing newer: no need for its files
        sums = net.get_text(net.release_asset_url(APP_REPO, tag, "SHA256SUMS"))
        sha = net.find_sha256(sums, asset)
        if not sha:
            raise RuntimeError(f"{asset} is not part of release {tag}.")
        return Release(tag, tag.lstrip("v"), asset, url, sha)

    def update_available(self, release: Release) -> bool:
        return (self.is_managed() and not self.restart_pending
                and version_key(release.version) > version_key(__version__))

    def install(self, release: Release, progress: ProgressFn | None = None,
                cancelled: Callable[[], bool] | None = None) -> None:
        exe = self.managed_path()
        new = exe.with_name(exe.name + ".new")
        try:
            def report(done: int, total: int) -> None:
                if progress:
                    progress(f"Downloading {release.asset}", done, total)

            digest = net.download(release.url, new, report, cancelled)
            if release.sha256 and digest != release.sha256:
                raise RuntimeError(f"Checksum mismatch for {release.asset}. The download was discarded.")
            _make_executable(new)
            if system.IS_WINDOWS:
                # A running .exe can't be overwritten, but it can be renamed out of the way.
                old = old_executable()
                old.unlink(missing_ok=True)
                os.replace(exe, old)
                try:
                    os.replace(new, exe)
                except OSError:
                    os.replace(old, exe)
                    raise
            else:
                os.replace(new, exe)  # the running program keeps its (now unlinked) file
        except PermissionError as err:
            raise RuntimeError(f"Could not replace {exe.name}: {err.strerror}") from err
        finally:
            new.unlink(missing_ok=True)
        self.restart_pending = release.version

    def remove(self) -> None:
        raise RuntimeError(f"{APP_NAME} can't remove itself.")


def old_executable() -> Path:
    """Where a Windows update parks the previous executable until it is no longer running."""
    exe = Path(sys.executable).resolve()
    return exe.with_name(exe.name + ".old")


class Components:
    def __init__(self):
        self.state = State(system.bin_dir() / "components.json")
        self.ytdlp = YtDlp(self.state)
        self.ffmpeg = Ffmpeg(self.state)
        self.deno = Deno(self.state)
        self.app = App(self.state)

    def tools(self) -> list[Component]:
        return [self.ytdlp, self.ffmpeg, self.deno]

    def all(self) -> list[Component]:
        return [self.app, *self.tools()]

    def get(self, key: str) -> Component:
        return next(c for c in self.all() if c.key == key)
