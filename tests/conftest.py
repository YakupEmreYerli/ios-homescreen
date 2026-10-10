"""Every test gets its own cache directory: nothing writes to the real one."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _own_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("IOS_HOMESCREEN_CACHE_DIR", str(tmp_path / "cache"))
