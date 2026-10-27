import io
import tarfile
import zipfile

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
