import pytest


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """Keep settings, queue and tools of every test in its own temporary folder."""
    data = tmp_path / "data"
    monkeypatch.setenv("YTDLP_GUI_DATA", str(data))
    return data
