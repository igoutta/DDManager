"""Shared fixtures. Qt-specific fixtures live in tests/ui/conftest.py."""

import shutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).absolute().parent.parent
MODDING_DIR = REPO_ROOT / "modding"


@pytest.fixture(scope="session")
def sample_mods_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A private copy of the repo's sample mods (modding/), so tests may mutate it."""
    dest = tmp_path_factory.mktemp("modding")
    for child in MODDING_DIR.iterdir():
        if child.is_dir():
            shutil.copytree(child, dest / child.name)
    return dest


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
