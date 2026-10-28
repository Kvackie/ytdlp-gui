"""A local web server with downloads that fail on purpose, for trying out retry, resume and cleanup.

    python devtools/test_server.py            (then open http://127.0.0.1:8765/ for the links)

Every link serves the same generated test video (FFmpeg is needed once to make it), slowly enough to
watch. The part of the path after the scenario is just a name: use a new name for a fresh scenario.

    /ok/NAME.mp4          always works
    /flaky/NAME.mp4       breaks off halfway and refuses connections for 20 s, so the download fails;
                          a Retry after that resumes from the halfway point
    /broken/NAME.mp4      breaks off halfway every time and never recovers: always fails, leaving a
                          .part file behind (for Remove, Cancel and "Retry from scratch")
    /missing/NAME.mp4     404: fails at once, nothing is written
    /playlist/NAME.html   a page with three videos (ok, flaky, ok): "Done with errors" (partial) at first,
                          complete after a Retry once the flaky one recovers
    /partial/NAME.html    a page with three videos (ok, missing, ok): always "Done with errors"

Pages with several videos are playlists to yt-dlp, so tick "Whole playlist" for those.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CUT_AT = 0.5  # fraction of the file served before a flaky/broken download breaks off
FLAKY_DOWNTIME = 20  # seconds a flaky download refuses connections after breaking off
CHUNK = 64 * 1024


def find_ffmpeg(explicit: str | None) -> str:
    candidates = [explicit, shutil.which("ffmpeg")]
    root = Path(__file__).resolve().parent.parent
    exe = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    candidates.append(str(root / "ytdlp-gui-data" / "bin" / "ffmpeg" / exe))  # the app's own copy
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    sys.exit("FFmpeg not found. Install it, let the app download it (run it from source once), "
             "or pass --ffmpeg PATH.")


def make_video(ffmpeg: str, seconds: int) -> bytes:
    out = Path(tempfile.mkdtemp(prefix="ytdlp-gui-test-")) / "test.mp4"
    subprocess.run([
        ffmpeg, "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", f"testsrc2=duration={seconds}:size=1280x720:rate=30",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
        "-c:v", "libx264", "-b:v", "3M", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(out),
    ], check=True)
    data = out.read_bytes()
    shutil.rmtree(out.parent, ignore_errors=True)
    return data


class Scenarios:
    """Per-name state of the flaky and broken downloads."""

    def __init__(self):
        self.lock = threading.Lock()
        self.down_until: dict[str, float] = {}  # name -> refuse connections until this time
        self.recovered: set[str] = set()  # flaky names that already broke once

    def refusing(self, key: str) -> bool:
        with self.lock:
            return time.time() < self.down_until.get(key, 0)

    def should_cut(self, kind: str, key: str) -> bool:
        with self.lock:
            return kind == "broken" or (kind == "flaky" and key not in self.recovered)

    def cut(self, kind: str, key: str) -> None:
        with self.lock:
            if kind == "flaky":
                self.recovered.add(key)
                self.down_until[key] = time.time() + FLAKY_DOWNTIME
            else:
                self.down_until[key] = float("inf")


def page(title: str, sources: list[str]) -> bytes:
    videos = "\n".join(f'<video controls src="{src}"></video>' for src in sources)
    return f"<!doctype html><html><head><title>{title}</title></head><body>{videos}</body></html>".encode()


def make_handler(video: bytes, rate: int, scenarios: Scenarios, port: int):
    base = f"http://127.0.0.1:{port}"

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            print(f"{self.address_string()} {fmt % args}")

        def do_HEAD(self):
            self.do_GET(head=True)

        def do_GET(self, head: bool = False):
            parts = self.path.split("?")[0].strip("/").split("/")
            if parts == [""]:
                return self.send_body(index(base), "text/html; charset=utf-8", head)
            if len(parts) != 2:
                return self.send_error(404)
            kind, file = parts
            name = file.rsplit(".", 1)[0]
            if kind in ("playlist", "partial") and file.endswith(".html"):
                middle = "flaky" if kind == "playlist" else "missing"
                sources = [f"/ok/{name}-1.mp4", f"/{middle}/{name}-2.mp4", f"/ok/{name}-3.mp4"]
                return self.send_body(page(name, sources), "text/html; charset=utf-8", head)
            if not file.endswith(".mp4") or kind not in ("ok", "flaky", "broken"):
                return self.send_error(404)
            key = f"{kind}/{name}"
            if scenarios.refusing(key):
                return self.send_error(503, "Temporarily unavailable (on purpose)")
            self.send_video(kind, key, head)

        def send_body(self, body: bytes, content_type: str, head: bool):
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if not head:
                self.wfile.write(body)

        def send_video(self, kind: str, key: str, head: bool):
            size = len(video)
            start = 0
            ranged = self.headers.get("Range", "")
            if ranged.startswith("bytes="):
                first = ranged[len("bytes="):].split("-")[0]
                start = int(first) if first.isdigit() else 0
            if start >= size:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(206 if start else 200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(size - start))
            if start:
                self.send_header("Content-Range", f"bytes {start}-{size - 1}/{size}")
            self.end_headers()
            if head:
                return
            cut_at = int(size * CUT_AT) if scenarios.should_cut(kind, key) else size
            pos = start
            try:
                while pos < size:
                    if pos >= cut_at:
                        scenarios.cut(kind, key)
                        print(f"  {key}: broke off at byte {pos} of {size} (on purpose)")
                        self.close_connection = True
                        return
                    end = min(pos + CHUNK, size, cut_at if pos < cut_at else size)
                    self.wfile.write(video[pos:end])
                    pos = end
                    time.sleep(CHUNK / rate)
            except (ConnectionError, OSError):
                self.close_connection = True  # the client stopped reading (e.g. yt-dlp only sniffed)

    return Handler


def index(base: str) -> bytes:
    stamp = time.strftime("%H%M%S")
    rows = [
        ("Always works", f"{base}/ok/works-{stamp}.mp4"),
        (f"Fails halfway, Retry after {FLAKY_DOWNTIME} s resumes it", f"{base}/flaky/flaky-{stamp}.mp4"),
        ("Always fails halfway (leaves a .part file)", f"{base}/broken/broken-{stamp}.mp4"),
        ("Fails at once (404)", f"{base}/missing/missing-{stamp}.mp4"),
        ("Playlist, partial at first; Retry completes it (tick Whole playlist)",
         f"{base}/playlist/playlist-{stamp}.html"),
        ("Playlist, always partial (tick Whole playlist)", f"{base}/partial/partial-{stamp}.html"),
    ]
    items = "\n".join(f"<li>{label}<br><code>{url}</code></li>" for label, url in rows)
    all_urls = "\n".join(url for _, url in rows)
    return (
        "<!doctype html><html><head><title>yt-dlp GUI test downloads</title></head>"
        "<body style='font-family:sans-serif;max-width:60em;margin:2em auto;line-height:1.5'>"
        "<h1>Test downloads</h1><p>Reload the page for fresh names. Paste the links into the app.</p>"
        f"<ul>{items}</ul><h2>All at once</h2><pre>{all_urls}</pre></body></html>"
    ).encode()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--ffmpeg", help="path to ffmpeg, if it is not on PATH")
    parser.add_argument("--seconds", type=int, default=30, help="length of the test video")
    parser.add_argument("--rate", type=float, default=1.0, help="download speed in MB/s per connection")
    args = parser.parse_args()

    print("Making the test video…")
    video = make_video(find_ffmpeg(args.ffmpeg), args.seconds)
    print(f"Test video: {len(video) / 1e6:.1f} MB, served at {args.rate:g} MB/s")
    handler = make_handler(video, int(args.rate * 1_000_000), Scenarios(), args.port)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    print(f"Open http://127.0.0.1:{args.port}/ for the links. Ctrl+C stops the server.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
