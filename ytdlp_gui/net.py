"""Small HTTP helpers on top of urllib (no third-party dependencies)."""
from __future__ import annotations

import hashlib
import re
import ssl
import urllib.error
import urllib.request
from collections.abc import Callable
from functools import cache
from pathlib import Path

from . import __version__

USER_AGENT = f"ytdlp-gui/{__version__} (+https://github.com/Kvackie/ytdlp-gui)"
TIMEOUT = 30

# CA bundles of the common Linux distributions, used when the bundled OpenSSL looks in the wrong place.
_CA_BUNDLES = (
    "/etc/ssl/certs/ca-certificates.crt",  # Debian, Ubuntu, Arch
    "/etc/pki/tls/certs/ca-bundle.crt",  # Fedora, RHEL
    "/etc/ssl/ca-bundle.pem",  # openSUSE
    "/etc/ssl/cert.pem",  # Alpine
)


class Cancelled(Exception):
    pass


@cache
def ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if not ctx.get_ca_certs():
        for bundle in _CA_BUNDLES:
            if Path(bundle).is_file():
                ctx.load_verify_locations(cafile=bundle)
                break
    return ctx


def _request(url: str, method: str = "GET") -> urllib.request.Request:
    return urllib.request.Request(url, method=method, headers={"User-Agent": USER_AGENT})


def get_text(url: str) -> str:
    with urllib.request.urlopen(_request(url), timeout=TIMEOUT, context=ssl_context()) as resp:
        return resp.read().decode("utf-8", "replace")


def get_bytes(url: str, limit: int = 5_000_000) -> bytes:
    with urllib.request.urlopen(_request(url), timeout=TIMEOUT, context=ssl_context()) as resp:
        return resp.read(limit)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def latest_release_tag(repo: str) -> str:
    """Tag of a GitHub repo's latest release, read from the /releases/latest redirect.

    Unlike the REST API this has no 60-requests-per-hour limit for anonymous clients.
    """
    opener = urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=ssl_context()))
    url = f"https://github.com/{repo}/releases/latest"
    try:
        with opener.open(_request(url, "HEAD"), timeout=TIMEOUT) as resp:
            location = resp.headers.get("Location", "")
    except urllib.error.HTTPError as err:
        if err.code not in (301, 302, 303, 307, 308):
            raise
        location = err.headers.get("Location", "")
    match = re.search(r"/releases/tag/([^/?#]+)", location)
    if not match:
        raise RuntimeError(f"Could not determine the latest release of {repo}")
    return urllib.request.unquote(match.group(1))


def release_asset_url(repo: str, tag: str, asset: str) -> str:
    return f"https://github.com/{repo}/releases/download/{tag}/{asset}"


def find_sha256(checksums: str, filename: str | None = None) -> str | None:
    """Pick the SHA-256 for `filename` out of a checksum listing.

    Handles `<hash>  <name>` lines (sha256sum, optionally with `*` for binary mode) and, when no file name
    is given, the first 64-hex-digit token (e.g. PowerShell's Get-FileHash output).
    """
    for line in checksums.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            name = parts[-1].lstrip("*")
            if filename is None or name == filename or name.endswith("/" + filename):
                return parts[0].lower()
    if filename is None:
        match = re.search(r"\b[0-9a-fA-F]{64}\b", checksums)
        return match.group(0).lower() if match else None
    return None


ProgressFn = Callable[[int, int], None]  # (bytes done, total bytes or 0 when unknown)


def download(url: str, dest: Path, progress: ProgressFn | None = None,
             cancelled: Callable[[], bool] | None = None) -> str:
    """Stream `url` into `dest` and return the file's SHA-256 hex digest."""
    digest = hashlib.sha256()
    with urllib.request.urlopen(_request(url), timeout=TIMEOUT, context=ssl_context()) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        with open(dest, "wb") as out:
            while True:
                if cancelled and cancelled():
                    raise Cancelled()
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    return digest.hexdigest()
