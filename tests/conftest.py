from __future__ import annotations

import pytest

from jobboard.board import JobBoard


@pytest.fixture
def board() -> JobBoard:
    """每個測試一個全新的求職平台（記憶體裡的 SQLite）。"""
    return JobBoard()
