import os
import time

from ytdlp_gui.cleanup import leftovers, remove_leftovers
from ytdlp_gui.jobs import Job
from ytdlp_gui.options import MARK_TARGET, DownloadOptions

TEMPORARY = [
    "Clip [id1].f137.mp4.part", "Clip [id1].f140.m4a", "Clip [id1].mp4.part", "Clip [id1].mp4.ytdl",
    "Clip [id1].mp4.part-Frag12.part", "Clip [id1].temp.mp4", "Clip [id1].fhls-1080p.mp4",
]
KEPT = ["Clip [id1].mp4", "Clip [id1].webp", "Clip [id1].fr.vtt", "Clip [id2].mp4.part", "Other.mp4.part"]


def make(folder, names, age=0.0):
    for name in names:
        path = folder / name
        path.write_bytes(b"x")
        if age:
            past = time.time() - age
            os.utime(path, (past, past))


def test_failed_leftovers_are_only_temporary_files(tmp_path):
    make(tmp_path, TEMPORARY + KEPT)
    found = leftovers(tmp_path / "Clip [id1].mp4")
    assert sorted(p.name for p in found) == sorted(TEMPORARY)


def test_cancelled_leftovers_include_files_written_since_the_start(tmp_path):
    make(tmp_path, ["Clip [id1].webp"], age=600)  # from an earlier download: kept
    make(tmp_path, ["Clip [id1].mp4.part", "Clip [id1].en.vtt", "Clip [id1].mp4"])
    found = leftovers(tmp_path / "Clip [id1].mp4", since=time.time() - 60)
    assert sorted(p.name for p in found) == ["Clip [id1].en.vtt", "Clip [id1].mp4", "Clip [id1].mp4.part"]


def test_remove_leftovers_keeps_completed_items_and_drops_empty_folders(tmp_path):
    playlist = tmp_path / "List"
    playlist.mkdir()
    make(playlist, ["1 - A [a].mp4", "1 - A [a].mp4.part", "2 - B [b].f137.mp4.part"])
    deleted = remove_leftovers(
        targets=[str(playlist / "1 - A [a].mp4"), str(playlist / "2 - B [b].mp4")],
        completed=[str(playlist / "1 - A [a].mp4")], root=tmp_path)
    assert [p.name for p in deleted] == ["2 - B [b].f137.mp4.part"]
    assert sorted(p.name for p in playlist.iterdir()) == ["1 - A [a].mp4", "1 - A [a].mp4.part"]

    deleted = remove_leftovers([str(playlist / "1 - A [a].mp4")], [], root=tmp_path, since=time.time() - 60)
    assert not playlist.exists()  # emptied, so removed; the download folder itself stays
    assert tmp_path.exists()


def test_job_remembers_targets_across_retries():
    job = Job(1, "https://example.com", DownloadOptions())
    job.reset_for_run()
    job.apply_line(MARK_TARGET + "/downloads/Clip [id1].mp4")
    job.finish(1, cancelled=False)
    job.reset_for_run()
    assert job.targets == ["/downloads/Clip [id1].mp4"]
    restored = Job.from_dict(2, job.to_dict())
    assert restored.targets == job.targets


def test_error_message_on_the_next_line():
    job = Job(1, "https://example.com", DownloadOptions())
    job.reset_for_run()
    job.apply_line("ERROR: ")
    job.apply_line("[download] Got error: HTTP Error 503. Giving up after 10 retries")
    job.finish(1, cancelled=False)
    assert job.error == "[download] Got error: HTTP Error 503. Giving up after 10 retries"
