import hashlib
import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from ytdlp_gui import components, net, system
from ytdlp_gui.components import Components, Release


@pytest.fixture
def comps():
    return Components()


def as_platform(monkeypatch, os_name: str, arch: str, musl: bool = False):
    monkeypatch.setattr(system, "IS_WINDOWS", os_name == "windows")
    monkeypatch.setattr(system, "IS_LINUX", os_name == "linux")
    monkeypatch.setattr(system, "machine", lambda: arch)
    monkeypatch.setattr(system, "is_musl", lambda: musl)


@pytest.mark.parametrize("os_name, arch, musl, ytdlp, ffmpeg, deno", [
    ("windows", "x86_64", False, "yt-dlp.exe", "ffmpeg-master-latest-win64-gpl-shared.zip",
     "deno-x86_64-pc-windows-msvc.zip"),
    ("windows", "aarch64", False, "yt-dlp_arm64.exe", "ffmpeg-master-latest-winarm64-gpl-shared.zip",
     "deno-aarch64-pc-windows-msvc.zip"),
    ("linux", "x86_64", False, "yt-dlp_linux", "ffmpeg-master-latest-linux64-gpl.tar.xz",
     "deno-x86_64-unknown-linux-gnu.zip"),
    ("linux", "aarch64", False, "yt-dlp_linux_aarch64", "ffmpeg-master-latest-linuxarm64-gpl.tar.xz",
     "deno-aarch64-unknown-linux-gnu.zip"),
    ("linux", "x86_64", True, "yt-dlp_musllinux", None, None),
])
def test_asset_names(monkeypatch, comps, os_name, arch, musl, ytdlp, ffmpeg, deno):
    as_platform(monkeypatch, os_name, arch, musl)
    assert comps.ytdlp.asset_name() == ytdlp
    assert comps.ffmpeg.asset_name() == ffmpeg
    assert comps.deno.asset_name() == deno


def test_find_sha256_formats():
    a, b = "a" * 64, "B" * 64
    sums = f"{a}  yt-dlp.exe\n{b} *yt-dlp_linux\n"
    assert net.find_sha256(sums, "yt-dlp.exe") == a
    assert net.find_sha256(sums, "yt-dlp_linux") == b.lower()
    assert net.find_sha256(sums, "missing") is None
    powershell = f"\r\nAlgorithm : SHA256\r\nHash      : {b}\r\nPath      : C:\\a\\deno.zip\r\n"
    assert net.find_sha256(powershell) == b.lower()


def test_ffmpeg_version_parsing(comps):
    out = "ffmpeg version N-121690-g1a2b3c4d-20261026 Copyright (c) 2000-2026 the FFmpeg developers\n"
    assert comps.ffmpeg.parse_version(out) == "N-121690-g1a2b3c4d (2026-10-26)"
    assert comps.deno.parse_version("deno 2.9.8 (stable, release, x86_64-pc-windows-msvc)\n") == "2.9.8"


def test_extract_only_writes_plain_names(tmp_path):
    archive = tmp_path / "a.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("pkg/bin/ffmpeg.exe", b"x")
        zf.writestr("pkg/bin/ffplay.exe", b"x")
        zf.writestr("../../evil/bin/ffprobe.exe", b"x")
        zf.writestr("pkg/doc/readme.txt", b"x")
    out = tmp_path / "out"

    def pick(m):
        parts = m.split("/")
        return parts[-1] if parts[-2] == "bin" and not parts[-1].startswith("ffplay") else None

    written = components._extract(archive, out, pick)
    assert sorted(p.name for p in written) == ["ffmpeg.exe", "ffprobe.exe"]
    assert all(p.parent == out for p in written)


def _fake_download(payload: bytes):
    def download(url, dest, progress=None, cancelled=None):
        dest.write_bytes(payload)
        import hashlib

        return hashlib.sha256(payload).hexdigest()

    return download


def test_install_and_update_ytdlp(monkeypatch, comps):
    payload = b"binary"
    monkeypatch.setattr(net, "download", _fake_download(payload))
    monkeypatch.setattr(type(comps.ytdlp), "probe_version", lambda self, path: "2026.10.26")
    import hashlib

    good = Release("stable:2026.10.26", "2026.10.26", "yt-dlp.exe", "u", hashlib.sha256(payload).hexdigest())
    comps.ytdlp.install(good)
    assert comps.ytdlp.is_managed()
    assert comps.ytdlp.managed_path().read_bytes() == payload
    assert comps.ytdlp.installed_version() == "2026.10.26"
    assert not comps.ytdlp.update_available(good)
    newer = Release("stable:2026.11.01", "2026.11.01", "yt-dlp.exe", "u", None)
    assert comps.ytdlp.update_available(newer)
    comps.ytdlp.channel = "nightly"
    assert comps.ytdlp.update_available(Release("nightly:2026.10.26", "2026.10.26", "x", "u", None))

    comps.ytdlp.remove()
    assert not comps.ytdlp.is_managed()


def test_checksum_mismatch_keeps_old_copy(monkeypatch, comps):
    monkeypatch.setattr(net, "download", _fake_download(b"tampered"))
    target = comps.ytdlp.managed_path()
    target.write_bytes(b"old")
    with pytest.raises(RuntimeError, match="Checksum mismatch"):
        comps.ytdlp.install(Release("stable:x", "x", "yt-dlp.exe", "u", "0" * 64))
    assert target.read_bytes() == b"old"


def test_ffmpeg_install_from_tar(monkeypatch, comps, tmp_path):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:xz") as tf:
        for name in ("ffmpeg-x/bin/ffmpeg", "ffmpeg-x/bin/ffprobe", "ffmpeg-x/bin/ffplay", "ffmpeg-x/LICENSE"):
            info = tarfile.TarInfo(name)
            info.size = 1
            tf.addfile(info, io.BytesIO(b"x"))
    monkeypatch.setattr(system, "IS_WINDOWS", False)
    monkeypatch.setattr(net, "download", _fake_download(buf.getvalue()))
    monkeypatch.setattr(type(comps.ffmpeg), "probe_version", lambda self, path: "N-1 (2026-10-26)")
    comps.ffmpeg.install(Release("sha", "latest build", "ffmpeg.tar.xz", "u", None))
    folder = comps.ffmpeg.managed_path().parent
    assert sorted(p.name for p in folder.iterdir()) == ["ffmpeg", "ffprobe"]
    assert comps.ffmpeg.location() == folder
    # A fresh build of the rolling release is only offered once the installed one is old.
    assert not comps.ffmpeg.update_available(Release("other", "latest build", "a", "u", None))


def test_version_key():
    assert components.version_key("0.2.0") > components.version_key("0.1.9")
    assert components.version_key("v0.10.0") > components.version_key("0.9.0")
    assert components.version_key("0.2.0") > components.version_key("0.2.0-dev.7")
    assert components.version_key("0.2") == components.version_key("0.2.0")


@pytest.mark.parametrize("os_name", ["windows", "linux"])
def test_app_updates_its_own_executable(monkeypatch, tmp_path, comps, os_name):
    as_platform(monkeypatch, os_name, "x86_64")
    folder = tmp_path / "app"
    folder.mkdir()
    exe = folder / "my-renamed-copy.exe"
    exe.write_bytes(b"old build")
    monkeypatch.setattr(system, "FROZEN", True)
    monkeypatch.setattr(components.sys, "executable", str(exe))
    monkeypatch.setattr(components, "__version__", "0.1.0")
    new = b"new build"

    def fake_download(url, dest, progress=None, cancelled=None):
        dest.write_bytes(new)
        return hashlib.sha256(new).hexdigest()

    monkeypatch.setattr(net, "download", fake_download)
    app = comps.app
    asset = app.asset_name()
    assert asset == ("ytdlp-gui-windows-x64.exe" if os_name == "windows" else "ytdlp-gui-linux-x86_64")
    release = Release("v0.2.0", "0.2.0", asset, "https://example/x", hashlib.sha256(new).hexdigest())
    assert app.update_available(release)
    assert not app.update_available(Release("v0.1.0", "0.1.0", asset, "", None))

    app.install(release)
    assert exe.read_bytes() == new
    assert app.restart_pending == "0.2.0"
    assert not app.update_available(release)
    leftovers = sorted(p.name for p in folder.iterdir())
    assert leftovers == (["my-renamed-copy.exe", "my-renamed-copy.exe.old"] if os_name == "windows"
                         else ["my-renamed-copy.exe"])


def test_app_rejects_a_bad_checksum(monkeypatch, tmp_path, comps):
    as_platform(monkeypatch, "linux", "x86_64")
    folder = tmp_path / "app"
    folder.mkdir()
    exe = folder / "ytdlp-gui"
    exe.write_bytes(b"old build")
    monkeypatch.setattr(system, "FROZEN", True)
    monkeypatch.setattr(components.sys, "executable", str(exe))
    monkeypatch.setattr(net, "download", lambda url, dest, *a: dest.write_bytes(b"evil") and "0" * 64)
    with pytest.raises(RuntimeError, match="Checksum"):
        comps.app.install(Release("v9", "9", "ytdlp-gui-linux-x86_64", "https://example/x", "1" * 64))
    assert exe.read_bytes() == b"old build"
    assert [p.name for p in folder.iterdir()] == ["ytdlp-gui"]


def test_system_ffmpeg_is_not_offered(monkeypatch, comps):
    monkeypatch.setattr(components.Ffmpeg, "system_path", lambda self: Path("/usr/bin/ffmpeg"))
    monkeypatch.setattr(components.YtDlp, "system_path", lambda self: Path("/usr/bin/yt-dlp"))
    monkeypatch.setattr(components.Ffmpeg, "asset_name", lambda self: "ffmpeg.zip")
    monkeypatch.setattr(components.YtDlp, "asset_name", lambda self: "yt-dlp")
    assert not comps.ffmpeg.offered()
    assert comps.ytdlp.offered()  # an outdated system yt-dlp is worth replacing
