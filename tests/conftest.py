import pytest


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    """Every test gets its own empty data folder, and no real Claude."""
    monkeypatch.setenv("JOB_SCANNER_DATA", str(tmp_path))
    monkeypatch.setenv("JOB_SCANNER_AI", "off")
    return tmp_path
