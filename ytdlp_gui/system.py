"""Platform details: where things live, which binaries fit this machine, and how to run child processes."""
from __future__ import annotations

import os
import platform
import shutil
import signal
import subprocess
import sys
from functools import cache
from pathlib import Path

from . import APP_ID

IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")
FROZEN = bool(getattr(sys, "frozen", False))

# A folder with this name next to the executable switches the app to portable mode:
# settings, queue and the downloaded tools are then kept there instead of the user profile.
PORTABLE_DIR_NAME = f"{APP_ID}-data"


def app_dir() -> Path:
    """Folder holding the executable (frozen) or the repository checkout (from source)."""
    if FROZEN:
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    override = os.environ.get("YTDLP_GUI_DATA")
    if override:
        path = Path(override)
    elif (app_dir() / PORTABLE_DIR_NAME).is_dir():
        path = app_dir() / PORTABLE_DIR_NAME
    elif IS_WINDOWS:
        path = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / APP_ID
    else:
        path = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / APP_ID
    path.mkdir(parents=True, exist_ok=True)
    return path


def is_portable() -> bool:
    return data_dir() == app_dir() / PORTABLE_DIR_NAME


def bin_dir() -> Path:
    path = data_dir() / "bin"
    path.mkdir(parents=True, exist_ok=True)
    return path


@cache
def default_download_dir() -> Path:
    if IS_LINUX:
        # xdg-user-dir knows the localized name ("Téléchargements", ...); fall back to ~/Downloads.
        try:
            out = subprocess.run(["xdg-user-dir", "DOWNLOAD"], capture_output=True, text=True, timeout=2,
                                 env=child_env())
            candidate = Path(out.stdout.strip())
            if out.returncode == 0 and candidate.is_dir() and candidate != Path.home():
                return candidate
        except (OSError, subprocess.SubprocessError):
            pass
    downloads = Path.home() / "Downloads"
    return downloads if downloads.is_dir() else Path.home()


def exe(name: str) -> str:
    return f"{name}.exe" if IS_WINDOWS else name


def machine() -> str:
    """Normalized CPU architecture: x86_64, x86, aarch64, armv7l or whatever the OS reports."""
    m = platform.machine().lower()
    if m in ("amd64", "x86_64", "x64"):
        # 32-bit Python on 64-bit Windows still reports AMD64; the tools we run are separate processes,
        # so the OS architecture is what matters here.
        return "x86_64"
    if m in ("arm64", "aarch64", "armv8l"):
        return "aarch64"
    if m in ("i386", "i486", "i586", "i686", "x86"):
        return "x86"
    if m.startswith("armv7"):
        return "armv7l"
    return m


def is_musl() -> bool:
    if not IS_LINUX:
        return False
    libc, _ = platform.libc_ver()
    if libc == "glibc":
        return False
    return any(Path("/lib").glob("ld-musl-*")) or any(Path("/usr/lib").glob("ld-musl-*"))


def child_env(extra_path: list[Path] | None = None) -> dict[str, str]:
    """Environment for the tools we launch.

    A PyInstaller build alters the environment of its own process (library paths, bootloader variables);
    yt-dlp is itself a PyInstaller program and ffmpeg/deno need the system libraries, so undo that.
    """
    env = dict(os.environ)
    if FROZEN:
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        if IS_LINUX:
            orig = env.pop("LD_LIBRARY_PATH_ORIG", None)
            if orig is not None:
                env["LD_LIBRARY_PATH"] = orig
            else:
                env.pop("LD_LIBRARY_PATH", None)
    env["PYTHONIOENCODING"] = "utf-8"  # only matters for the plain zipimport yt-dlp on exotic Linux CPUs
    env["PYTHONUTF8"] = "1"
    if extra_path:
        env["PATH"] = os.pathsep.join([str(p) for p in extra_path] + [env.get("PATH", "")])
    return env


def reset_dll_search_path() -> None:
    """The Windows bootloader points the DLL search path at its own folder; child processes inherit it."""
    if IS_WINDOWS and FROZEN:
        import ctypes

        ctypes.windll.kernel32.SetDllDirectoryW(None)


def popen_kwargs() -> dict:
    """Run tools without a console window and in their own process group, so cancelling can stop the
    whole tree (yt-dlp starts ffmpeg)."""
    if IS_WINDOWS:
        return {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def kill_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        if IS_WINDOWS:
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=10,
            )
        else:
            os.killpg(proc.pid, signal.SIGTERM)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def run_quiet(args: list[str], timeout: float = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        capture_output=True,
        stdin=subprocess.DEVNULL,
        timeout=timeout,
        env=child_env(),
        **({"creationflags": subprocess.CREATE_NO_WINDOW} if IS_WINDOWS else {}),
    )


def reveal_in_file_manager(path: Path) -> None:
    if IS_WINDOWS and path.exists():
        subprocess.Popen(["explorer", "/select,", str(path)], creationflags=subprocess.CREATE_NO_WINDOW)
        return
    open_path(path.parent if path.is_file() else path)


def open_path(path: Path) -> None:
    if IS_WINDOWS:
        os.startfile(str(path))  # noqa: S606 - opening the user's own file/folder
        return
    opener = shutil.which("xdg-open") or shutil.which("gio")
    if opener:
        args = [opener, "open", str(path)] if opener.endswith("gio") else [opener, str(path)]
        subprocess.Popen(args, env=child_env(), start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
