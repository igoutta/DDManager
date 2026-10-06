"""Shared fixtures. Qt-specific fixtures live in tests/ui/conftest.py."""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).absolute().parent.parent
MODDING_DIR = REPO_ROOT / "modding"


@pytest.fixture(scope="session")
def sample_mods_dir() -> Path:
    """The repo's sample mods (modding/), read IN PLACE: tests must never write under it.

    Copying the folder (hundreds of MB of art) used to cost half a minute per session; a test
    that needs a mods root it may touch builds one with ``mod_dir`` or ``modding_copy``.
    """
    return MODDING_DIR


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """An empty 'DD Manager Data' directory."""
    d = tmp_path / "DD Manager Data"
    d.mkdir()
    return d


@pytest.fixture(scope="session")
def legacy():
    """The pinned legacy oracle (git show 31e85d6:<file>). Skips when unavailable."""
    pytest.importorskip("tkinter", reason="legacy dd2.py imports tkinter at module level")
    from tools.legacy_oracle import LegacyOracle, extract

    try:
        directory = extract()
    except Exception as exc:  # noqa: BLE001 - shallow clone or no git: skip, don't fail
        pytest.skip(f"legacy oracle unavailable: {exc}")
    return LegacyOracle(directory)
