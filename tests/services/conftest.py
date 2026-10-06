"""Fixtures of the services/plugins tests (kept out of the root conftest on purpose)."""

import shutil
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import pytest

from src.core.saves import SaveFormatRegistry
from tests.services.helpers import (
    NOW,
    FakeFormat,
    FakeProbe,
    SteamTree,
    acf_text,
    vdf_text,
)


@pytest.fixture
def fake_env(tmp_path: Path):
    """``fake_env(platform="windows", env=None, registry=None, home=None) -> Environment``."""
    from src.services.environment import DictRegistry, Environment

    def build(platform="windows", env=None, registry=None, home=None, known_documents_dir=None):
        return Environment(
            platform=platform,
            home=home if home is not None else tmp_path / "home",
            env=dict(env or {}),
            registry=registry if registry is not None else DictRegistry(),
            known_documents_dir=known_documents_dir,
        )

    return build


@pytest.fixture
def make_steam_root() -> Callable[..., SteamTree]:
    """``make_steam_root(tmp, libraries, workshop_ids, acf, userdata) -> SteamTree``."""

    def build(
        tmp: Path,
        libraries: Sequence[str] = (),
        workshop_ids: Sequence[str] = (),
        acf: Mapping[str, str] | None = None,
        userdata: Sequence[str] = (),
    ) -> SteamTree:
        root = tmp / "Steam"
        extra = tuple(tmp / name for name in libraries)
        (root / "steamapps").mkdir(parents=True)
        (root / "steamapps" / "libraryfolders.vdf").write_text(vdf_text(extra), "utf-8")
        for lib in extra:
            (lib / "steamapps").mkdir(parents=True)
        game_dir = root / "steamapps" / "common" / "DarkestDungeon"
        (game_dir / "mods").mkdir(parents=True)
        workshop = root / "steamapps" / "workshop" / "content" / "262060"
        workshop.mkdir(parents=True)
        for wid in workshop_ids:
            (workshop / wid).mkdir()
        acf_file = root / "steamapps" / "workshop" / "appworkshop_262060.acf"
        acf_file.write_text(acf_text(acf or {}), "utf-8")
        saves, decoys = [], []
        for uid in userdata:
            remote = root / "userdata" / uid / "262060" / "remote"
            remote.mkdir(parents=True)
            save = remote / "persist.game.json"
            save.write_bytes(b"x")
            saves.append(save)
            for decoy_name in ("persist.game.backup.20240101-000000.json", "persist.game.json.bak"):
                decoy = remote / decoy_name
                decoy.write_bytes(b"x")
                decoys.append(decoy)
        return SteamTree(root, extra, workshop, acf_file, game_dir, tuple(saves), tuple(decoys))

    return build


@pytest.fixture
def mod_dir() -> Callable[..., Path]:
    """``mod_dir(root, name, title=None, published_id=None, tags=(), files=(), modfiles=None,
    encoding="utf-8")`` writes ``root/name`` with a project.xml and returns the folder."""

    def build(
        root: Path,
        name: str,
        title: str | None = None,
        published_id: str | None = None,
        tags: Sequence[str] = (),
        files: Sequence[str] = (),
        modfiles: str | None = None,
        encoding: str = "utf-8",
    ) -> Path:
        folder = root / name
        folder.mkdir(parents=True, exist_ok=True)
        lines = ['<?xml version="1.0" encoding="' + encoding + '"?>', "<project>"]
        if title is not None:
            lines.append(f"<Title>{title}</Title>")
        if published_id is not None:
            lines.append(f"<PublishedFileId>{published_id}</PublishedFileId>")
        lines.extend(f"<Tags>{tag}</Tags>" for tag in tags)
        lines.append("</project>")
        (folder / "project.xml").write_bytes("\n".join(lines).encode(encoding))
        for rel in files:
            target = folder / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"x")
        if modfiles is not None:
            (folder / "modfiles.txt").write_text(modfiles, "utf-8")
        return folder

    return build


@pytest.fixture
def fixed_clock():
    from src.services.ports import FixedClock

    return FixedClock(NOW)


@pytest.fixture
def fake_probe() -> Callable[..., FakeProbe]:
    """``fake_probe(state)`` -> a probe that always answers ``state`` (default NOT_RUNNING)."""
    from src.services.ports import RunState

    def build(state: object = None) -> FakeProbe:
        return FakeProbe(RunState.NOT_RUNNING if state is None else state)

    return build


@pytest.fixture
def fake_save_format() -> FakeFormat:
    return FakeFormat()


@pytest.fixture
def fake_registry(fake_save_format: FakeFormat) -> SaveFormatRegistry:
    return SaveFormatRegistry([fake_save_format])


@pytest.fixture
def app_paths(tmp_path: Path):
    """A real AppPaths for ``tmp_path/DD Manager Data`` (directories created)."""
    from src.services.app_paths import AppPaths, DataDirMode

    paths = AppPaths(tmp_path / "DD Manager Data", DataDirMode.OVERRIDE, None, "test")
    paths.ensure()
    return paths


@pytest.fixture
def modding_copy(sample_mods_dir: Path, tmp_path: Path) -> Path:
    """A throwaway second mods root with the same mod folders as the samples, each holding
    only its ``project.xml`` and ``modfiles.txt`` (enough to be discovered and identified)."""
    dest = tmp_path / "modding"
    for folder in sample_mods_dir.iterdir():
        if not folder.is_dir():
            continue
        (dest / folder.name).mkdir(parents=True)
        for name in ("project.xml", "modfiles.txt"):
            if (folder / name).is_file():
                shutil.copy2(folder / name, dest / folder.name / name)
    return dest
