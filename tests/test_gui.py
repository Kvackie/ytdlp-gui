"""GUI pieces, with a stand-in for yt-dlp so no network is needed."""
import sys
import textwrap
from pathlib import Path

import pytest

from ytdlp_gui.components import Components
from ytdlp_gui.gui import queue as queue_module
from ytdlp_gui.gui.formats_dialog import compose_selector
from ytdlp_gui.gui.main_window import MainWindow, extract_urls
from ytdlp_gui.gui.queue import QueueManager
from ytdlp_gui.jobs import Status
from ytdlp_gui.options import (
    FIELD_SEP,
    MARK_FILE,
    MARK_ITEM,
    MARK_PROGRESS,
    MARK_TARGET,
    DownloadOptions,
    ToolPaths,
)
from ytdlp_gui.settings import Settings

FAKE_YTDLP = textwrap.dedent(f"""
    import os, sys, time
    url = sys.argv[-1]
    S = {FIELD_SEP!r}
    if "fail" in url:
        print("ERROR: [generic] Unsupported URL: " + url, flush=True)
        sys.exit(1)
    target = os.path.join(os.getcwd(), "Fake video [" + url.rsplit("/", 1)[-1] + "].mp4")
    print({MARK_ITEM!r} + "id1" + S + "Fake video" + S + S, flush=True)
    print({MARK_TARGET!r} + target, flush=True)
    for done in (25, 50, 100):
        with open(target + ".part", "a") as part:
            part.write("x" * 25)
        if "breaks" in url and done == 50:
            print("ERROR: ", flush=True)
            print("[download] Got error: connection lost. Giving up after 10 retries", flush=True)
            sys.exit(1)
        print({MARK_PROGRESS!r} + S.join(["downloading", str(done), "100", "NA", "1000", "1", "18"]), flush=True)
        time.sleep(0.05 if "slow" not in url else 2)
    os.replace(target + ".part", target)
    print({MARK_FILE!r} + target, flush=True)
""")


@pytest.fixture
def fake_ytdlp(tmp_path, monkeypatch):
    script = tmp_path / "fake_ytdlp.py"
    script.write_text(FAKE_YTDLP, encoding="utf-8")
    real_build = queue_module.build_args
    monkeypatch.setattr(queue_module, "build_args",
                        lambda o, urls, tools: [sys.executable, str(script)] + real_build(o, urls, tools)[1:])
    return ToolPaths(ytdlp=Path("unused"))


def test_extract_urls():
    text = "see https://a.example/watch?v=1, and (https://b.example/x) https://a.example/watch?v=1"
    assert extract_urls(text) == ["https://a.example/watch?v=1", "https://b.example/x"]


def test_compose_selector():
    video = {"format_id": "137", "vcodec": "avc1", "acodec": "none"}
    audio = {"format_id": "140", "vcodec": "none", "acodec": "mp4a"}
    both = {"format_id": "18", "vcodec": "avc1", "acodec": "mp4a"}
    assert compose_selector([video, audio], True)[0] == "137+140"
    assert compose_selector([video], True)[0] == "137+ba"
    assert compose_selector([video], False)[0] == "137"
    assert compose_selector([both], True)[0] == "18"
    assert compose_selector([video, both], True)[0] == ""


def test_queue_runs_jobs_to_completion(qtbot, fake_ytdlp, tmp_path):
    q = QueueManager(lambda: fake_ytdlp, max_concurrent=2)
    jobs = q.add(["https://ok.example/1", "https://fail.example/2"], DownloadOptions(output_dir=str(tmp_path)))
    qtbot.waitUntil(lambda: all(j.status.finished for j in jobs), timeout=20000)
    ok, bad = jobs
    assert ok.status == Status.DONE, list(ok.log)
    assert ok.title == "Fake video"
    assert ok.files == [str(tmp_path / "Fake video [1].mp4")]
    assert bad.status == Status.FAILED
    assert "Unsupported URL" in bad.error


def test_queue_cancel(qtbot, fake_ytdlp, tmp_path):
    q = QueueManager(lambda: fake_ytdlp, max_concurrent=1)
    running, waiting = q.add(["https://slow.example/1", "https://ok.example/2"],
                             DownloadOptions(output_dir=str(tmp_path)))
    qtbot.waitUntil(lambda: running.progress is not None, timeout=20000)
    q.cancel([waiting.id])
    assert waiting.status == Status.CANCELLED
    q.cancel([running.id])
    qtbot.waitUntil(lambda: running.status.finished, timeout=20000)
    assert running.status == Status.CANCELLED


def test_missing_ytdlp_leaves_queue_state_alone(qtbot):
    q = QueueManager(lambda: None)
    with qtbot.waitSignal(q.tools_missing, timeout=1000):
        q.add(["https://example.com/1"], DownloadOptions())
    assert not q.paused  # only the user pauses the queue
    assert q.jobs[1].status == Status.QUEUED


def test_main_window_adds_links(qtbot, monkeypatch, tmp_path):
    settings = Settings.load()
    settings.setup_done = True
    settings.auto_start = False
    monkeypatch.setattr(MainWindow, "_startup", lambda self: None)
    window = MainWindow(settings, Components())
    qtbot.addWidget(window)
    window.url_box.setPlainText("https://example.com/a\nhttps://example.com/b")
    window.audio_btn.setChecked(True)
    window.add_from_box()
    assert [j.url for j in window.queue.jobs.values()] == ["https://example.com/a", "https://example.com/b"]
    assert all(j.options.mode == "audio" for j in window.queue.jobs.values())
    assert window.model.rowCount() == 2
    assert window.url_box.toPlainText() == ""
    window.close()
    assert Settings.load().options.mode == "audio"


def test_clear_keeps_what_can_be_retried(qtbot):
    q = QueueManager(lambda: None, paused=True)
    jobs = q.add([f"https://example.com/{i}" for i in range(5)], DownloadOptions())
    statuses = (Status.DONE, Status.FAILED, Status.PARTIAL, Status.CANCELLED, Status.QUEUED)
    for job, status in zip(jobs, statuses, strict=True):
        job.status = status
    q.clear_finished()
    assert [q.jobs[i].status for i in q.jobs] == [Status.FAILED, Status.PARTIAL, Status.QUEUED]


def test_adding_links_does_not_resume_a_paused_queue(qtbot, monkeypatch):
    settings = Settings.load()
    settings.setup_done = True
    settings.auto_start = False
    monkeypatch.setattr(MainWindow, "_startup", lambda self: None)
    window = MainWindow(settings, Components())
    qtbot.addWidget(window)
    assert window.queue.paused and window.run_btn.text() == "Resume queue"
    window.add_urls(["https://example.com/a"])
    assert window.queue.paused
    window._set_paused(True)
    assert window.run_btn.text() == "Resume queue"
    window.close()


def test_failed_download_keeps_its_parts_until_removed(qtbot, fake_ytdlp, tmp_path):
    q = QueueManager(lambda: fake_ytdlp)
    (job,) = q.add(["https://breaks.example/v1"], DownloadOptions(output_dir=str(tmp_path)))
    qtbot.waitUntil(lambda: job.status.finished, timeout=20000)
    assert job.status == Status.FAILED
    assert job.error == "[download] Got error: connection lost. Giving up after 10 retries"
    part = tmp_path / "Fake video [v1].mp4.part"
    assert part.exists()  # a retry continues from here
    q.remove([job.id])
    qtbot.waitUntil(lambda: not part.exists(), timeout=5000)


def test_cancelled_download_is_deleted(qtbot, fake_ytdlp, tmp_path):
    q = QueueManager(lambda: fake_ytdlp)
    out = tmp_path / "downloads"
    (job,) = q.add(["https://slow.example/v2"], DownloadOptions(output_dir=str(out)))
    part = out / "Fake video [v2].mp4.part"
    qtbot.waitUntil(part.exists, timeout=20000)
    q.cancel([job.id])
    qtbot.waitUntil(lambda: job.status == Status.CANCELLED, timeout=20000)
    qtbot.waitUntil(lambda: not part.exists(), timeout=5000)
    assert list(out.iterdir()) == []


def test_retry_from_scratch_deletes_parts_first(qtbot, fake_ytdlp, tmp_path):
    q = QueueManager(lambda: fake_ytdlp)
    (job,) = q.add(["https://breaks.example/v3"], DownloadOptions(output_dir=str(tmp_path)))
    qtbot.waitUntil(lambda: job.status.finished, timeout=20000)
    q.paused = True
    q.retry([job.id], fresh=True)
    assert not (tmp_path / "Fake video [v3].mp4.part").exists()
    assert job.fresh and job.status == Status.QUEUED


def test_no_widget_flashes_up_as_its_own_window(qtbot, monkeypatch):
    """A widget shown before it has a parent briefly opens as a separate window."""
    from PySide6.QtCore import QEvent, QObject
    from PySide6.QtWidgets import QApplication

    from ytdlp_gui.gui.components_dialog import ComponentsDialog
    from ytdlp_gui.gui.preferences import PreferencesDialog

    expected = {"MainWindow", "ComponentsDialog", "PreferencesDialog"}
    stray = []

    class Spy(QObject):
        def eventFilter(self, obj, event):
            if (event.type() == QEvent.Type.Show and obj.isWidgetType() and obj.isWindow()
                    and obj.metaObject().className() not in expected):
                stray.append(obj.metaObject().className())
            return False

    spy = Spy()
    QApplication.instance().installEventFilter(spy)
    try:
        settings = Settings.load()
        settings.setup_done = True
        monkeypatch.setattr(MainWindow, "_startup", lambda self: None)
        window = MainWindow(settings, Components())
        qtbot.addWidget(window)
        window.show()
        window.updates.check = lambda auto=False: None
        dialogs = [ComponentsDialog(window.updates, settings, parent=window),
                   ComponentsDialog(window.updates, settings, setup=True, parent=window),
                   PreferencesDialog(settings, window)]
        for dialog in dialogs:
            dialog.show()
            dialog.close()
        window.close()
    finally:
        QApplication.instance().removeEventFilter(spy)
    assert stray == []
