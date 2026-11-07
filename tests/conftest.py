import json
from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures" / "claude_code"


def load(name):
    return json.loads((FIX / f"{name}.json").read_text())


def fixture_bytes(name):
    return (FIX / f"{name}.json").read_bytes()


@pytest.fixture
def short_tmp(tmp_path_factory):
    # AF_UNIX paths must be short on macOS (104 bytes)
    import tempfile
    d = Path(tempfile.mkdtemp(prefix="pw", dir="/tmp"))
    yield d
    import shutil
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path_factory, monkeypatch):
    """Never let a test touch the real ~/.pitwall."""
    import tempfile
    d = Path(tempfile.mkdtemp(prefix="pwh", dir="/tmp"))
    monkeypatch.setenv("PITWALL_HOME", str(d))
    yield d
    import shutil
    shutil.rmtree(d, ignore_errors=True)
