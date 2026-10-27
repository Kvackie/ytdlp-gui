from ytdlp_gui.jobs import Job, Status
from ytdlp_gui.options import FIELD_SEP as S
from ytdlp_gui.options import MARK_FILE, MARK_ITEM, MARK_POSTPROCESS, MARK_PROGRESS, DownloadOptions


def make_job() -> Job:
    job = Job(1, "https://example.com/v", DownloadOptions())
    job.reset_for_run()
    return job


def test_progress_line_updates_numbers():
    job = make_job()
    job.apply_line(f"{MARK_PROGRESS}downloading{S}500{S}1000{S}NA{S}250.5{S}2{S}137")
    assert job.status == Status.RUNNING
    assert job.progress == 0.5
    assert job.speed == 250.5 and job.eta == 2
    assert job.phase == "Downloading"
    assert not any(MARK_PROGRESS in line for line in job.log)


def test_estimated_total_and_second_part():
    job = make_job()
    job.apply_line(f"{MARK_PROGRESS}finished{S}100{S}100{S}NA{S}NA{S}NA{S}137")
    job.apply_line(f"{MARK_PROGRESS}downloading{S}10{S}NA{S}40{S}NA{S}NA{S}140")
    assert job.total == 40
    assert job.progress == 0.25
    assert job.phase == "Downloading (part 2)"


def test_item_postprocess_file_and_success():
    job = make_job()
    job.apply_line(f"{MARK_ITEM}abc{S}A title{S}2{S}5")
    assert (job.title, job.item_index, job.item_count) == ("A title", 2, 5)
    assert job.display_title == "2/5 · A title"
    job.apply_line(f"{MARK_POSTPROCESS}Merger{S}started")
    assert job.status == Status.PROCESSING and job.phase == "Merging"
    job.apply_line(f"{MARK_FILE}/out/A title [abc].mp4")
    assert job.files == ["/out/A title [abc].mp4"]
    job.finish(0, cancelled=False)
    assert job.status == Status.DONE and job.progress == 1.0


def test_error_and_failure():
    job = make_job()
    job.apply_line("ERROR: [generic] Unsupported URL: https://example.com/v")
    job.finish(1, cancelled=False)
    assert job.status == Status.FAILED
    assert job.error.startswith("[generic] Unsupported URL")


def test_partial_when_some_files_were_saved():
    job = make_job()
    job.apply_line(f"{MARK_FILE}/out/one.mp4")
    job.apply_line("ERROR: video two is private")
    job.finish(1, cancelled=False)
    assert job.status == Status.PARTIAL


def test_cancel_wins_over_exit_code():
    job = make_job()
    job.finish(1, cancelled=True)
    assert job.status == Status.CANCELLED


def test_playlist_lines():
    job = make_job()
    job.apply_line("[download] Downloading playlist: My list")
    job.apply_line("[download] Downloading item 3 of 12")
    assert job.playlist_title == "My list"
    assert (job.item_index, job.item_count) == (3, 12)


def test_log_seq_counts_lines():
    job = make_job()
    start = job.log_seq
    job.apply_line("[youtube] Extracting URL")
    job.apply_line("[info] Downloading 1 format(s)")
    assert job.log_seq == start + 2


def test_persistence_requeues_interrupted_jobs():
    job = make_job()
    job.title = "Half done"
    restored = Job.from_dict(7, job.to_dict())
    assert restored.status == Status.QUEUED
    assert restored.title == "Half done"
    job.finish(0, cancelled=False)
    assert Job.from_dict(8, job.to_dict()).status == Status.DONE
