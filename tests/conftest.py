import os
import sys

import pytest

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src")
)


@pytest.fixture()
def tmp_settings(tmp_path, monkeypatch):
    """Force mock mode and isolate the data dir per test."""
    monkeypatch.setenv("OPSCOMMANDER_MODE", "mock")
    monkeypatch.setenv("OPSCOMMANDER_DATA_DIR", str(tmp_path))
    from opscommander.config import get_settings

    return get_settings()
