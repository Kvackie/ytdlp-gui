from ytdlp_gui import system


def test_data_dir_is_next_to_the_app(monkeypatch, tmp_path):
    monkeypatch.delenv("YTDLP_GUI_DATA")
    monkeypatch.setattr(system, "app_dir", lambda: tmp_path)
    assert system.data_dir() == tmp_path / "ytdlp-gui-data"
    assert (tmp_path / "ytdlp-gui-data").is_dir()
    assert system.data_dir_problem() is None


def test_unwritable_data_dir_is_reported(monkeypatch, tmp_path):
    monkeypatch.delenv("YTDLP_GUI_DATA")
    blocker = tmp_path / "file"
    blocker.write_text("")
    # A file where the app folder should be: creating the data folder inside it fails on every OS.
    monkeypatch.setattr(system, "app_dir", lambda: blocker)
    assert system.data_dir_problem()
