"""The one data-dir resolver: precedence table, writability gate, repo markers, USER fallback."""

from pathlib import Path
from typing import Any

import pytest

from src.services.app_paths import (
    DATA_DIR_NAME,
    ENV_OVERRIDE,
    AppPaths,
    DataDirMode,
    find_repo_root,
    probe_writable,
    resolve_app_paths,
    user_data_dir,
)
from src.services.errors import DataDirNotWritableError


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "checkout"
    (root / "src").mkdir(parents=True)
    (root / "src" / "__init__.py").write_text("", "utf-8")
    (root / "pyproject.toml").write_text("[project]\n", "utf-8")
    return root


@pytest.fixture
def exe_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "install"
    folder.mkdir()
    return folder


def always(_: Path) -> bool:
    return True


def never(_: Path) -> bool:
    return False


def test_constants() -> None:
    assert DATA_DIR_NAME == "DD Manager Data"
    assert ENV_OVERRIDE == "DDMANAGER_DATA_DIR"


def test_argument_override_beats_everything(fake_env, tmp_path: Path, repo: Path) -> None:
    env = fake_env(env={ENV_OVERRIDE: str(tmp_path / "from-env")})
    target = tmp_path / "from-arg"
    paths = resolve_app_paths(
        frozen=False,
        executable=tmp_path / "python.exe",
        package_init=repo / "src" / "__init__.py",
        env=env,
        override=target,
        is_writable=always,
    )
    assert (paths.data_dir, paths.mode) == (target, DataDirMode.OVERRIDE)


def test_env_override_beats_frozen_and_source(
    fake_env, tmp_path: Path, repo: Path, exe_dir: Path
) -> None:
    target = tmp_path / "from-env"
    env = fake_env(env={ENV_OVERRIDE: str(target)})
    for frozen in (True, False):
        paths = resolve_app_paths(
            frozen=frozen,
            executable=exe_dir / "DD Manager.exe",
            package_init=repo / "src" / "__init__.py",
            env=env,
            is_writable=always,
        )
        assert (paths.data_dir, paths.mode) == (target, DataDirMode.OVERRIDE)


def test_frozen_uses_existing_portable_dir_beside_the_exe(
    fake_env, tmp_path: Path, exe_dir: Path
) -> None:
    (exe_dir / DATA_DIR_NAME).mkdir()
    paths = resolve_app_paths(
        frozen=True,
        executable=exe_dir / "DD Manager.exe",
        package_init=tmp_path / "bundle" / "src" / "__init__.py",
        env=fake_env(),
        is_writable=always,
    )
    assert paths.mode is DataDirMode.PORTABLE_FROZEN
    assert paths.data_dir == exe_dir / DATA_DIR_NAME
    assert paths.anchor == exe_dir


def test_frozen_creates_a_portable_location_when_the_anchor_is_writable(
    fake_env, tmp_path: Path, exe_dir: Path
) -> None:
    paths = resolve_app_paths(
        frozen=True,
        executable=exe_dir / "DD Manager.exe",
        package_init=tmp_path / "bundle" / "src" / "__init__.py",
        env=fake_env(),
        is_writable=always,
    )
    assert (paths.mode, paths.data_dir) == (DataDirMode.PORTABLE_FROZEN, exe_dir / DATA_DIR_NAME)


def test_frozen_unwritable_anchor_falls_back_to_the_user_dir(
    fake_env, tmp_path: Path, exe_dir: Path
) -> None:
    local = tmp_path / "Local"
    env = fake_env(env={"LOCALAPPDATA": str(local)})
    paths = resolve_app_paths(
        frozen=True,
        executable=exe_dir / "DD Manager.exe",
        package_init=tmp_path / "bundle" / "src" / "__init__.py",
        env=env,
        is_writable=never,
    )
    assert paths.mode is DataDirMode.USER
    assert paths.data_dir == local / "DD Manager"
    assert not (exe_dir / DATA_DIR_NAME).exists()


def test_existing_unwritable_portable_dir_is_an_error_and_never_forks_state(
    fake_env, tmp_path: Path, exe_dir: Path
) -> None:
    (exe_dir / DATA_DIR_NAME).mkdir()
    local = tmp_path / "Local"
    env = fake_env(env={"LOCALAPPDATA": str(local)})
    with pytest.raises(DataDirNotWritableError):
        resolve_app_paths(
            frozen=True,
            executable=exe_dir / "DD Manager.exe",
            package_init=tmp_path / "bundle" / "src" / "__init__.py",
            env=env,
            is_writable=never,
        )
    assert not local.exists()


def test_source_run_anchors_at_the_repo_root(fake_env, repo: Path, tmp_path: Path) -> None:
    paths = resolve_app_paths(
        frozen=False,
        executable=tmp_path / "python.exe",
        package_init=repo / "src" / "__init__.py",
        env=fake_env(),
        is_writable=always,
    )
    assert paths.mode is DataDirMode.PORTABLE_SOURCE
    assert paths.anchor == repo
    assert paths.data_dir == repo / DATA_DIR_NAME


def test_source_run_without_repo_markers_uses_the_user_dir(fake_env, tmp_path: Path) -> None:
    site = tmp_path / "site-packages"
    (site / "src").mkdir(parents=True)
    (site / "src" / "__init__.py").write_text("", "utf-8")
    local = tmp_path / "Local"
    paths = resolve_app_paths(
        frozen=False,
        executable=tmp_path / "python.exe",
        package_init=site / "src" / "__init__.py",
        env=fake_env(env={"LOCALAPPDATA": str(local)}),
        is_writable=always,
    )
    assert (paths.mode, paths.data_dir, paths.anchor) == (
        DataDirMode.USER,
        local / "DD Manager",
        None,
    )


def test_cwd_has_no_effect(
    fake_env, tmp_path: Path, repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    decoy = tmp_path / "elsewhere"
    (decoy / DATA_DIR_NAME).mkdir(parents=True)
    kwargs: dict[str, Any] = {
        "frozen": False,
        "executable": tmp_path / "python.exe",
        "package_init": repo / "src" / "__init__.py",
        "env": fake_env(),
        "is_writable": always,
    }
    before = resolve_app_paths(**kwargs)
    monkeypatch.chdir(decoy)
    assert resolve_app_paths(**kwargs) == before
    assert before.data_dir == repo / DATA_DIR_NAME


def test_resolving_creates_nothing(fake_env, tmp_path: Path) -> None:
    local = tmp_path / "Local"
    resolve_app_paths(
        frozen=False,
        executable=tmp_path / "python.exe",
        package_init=tmp_path / "nowhere" / "src" / "__init__.py",
        env=fake_env(env={"LOCALAPPDATA": str(local)}),
        is_writable=always,
    )
    assert not local.exists()


def test_find_repo_root_needs_both_markers(repo: Path, tmp_path: Path) -> None:
    assert find_repo_root(repo / "src" / "__init__.py") == repo
    (repo / "pyproject.toml").unlink()
    assert find_repo_root(repo / "src" / "__init__.py") is None
    other = tmp_path / "other"
    other.mkdir()
    (other / "pyproject.toml").write_text("", "utf-8")
    assert find_repo_root(other / "src" / "__init__.py") is None


def test_user_data_dir_per_platform(fake_env, tmp_path: Path) -> None:
    home = tmp_path / "home"
    win = fake_env("windows", {"LOCALAPPDATA": str(tmp_path / "L")}, home=home)
    assert user_data_dir(win) == tmp_path / "L" / "DD Manager"
    linux = fake_env("linux", {}, home=home)
    assert user_data_dir(linux) == home / ".local" / "share" / "dd-manager"
    xdg = fake_env("linux", {"XDG_DATA_HOME": str(tmp_path / "xdg")}, home=home)
    assert user_data_dir(xdg) == tmp_path / "xdg" / "dd-manager"
    mac = fake_env("darwin", {}, home=home)
    assert user_data_dir(mac) == home / "Library" / "Application Support" / "DD Manager"


def test_probe_writable_is_a_real_write_and_leaves_nothing(tmp_path: Path) -> None:
    folder = tmp_path / "probe"
    folder.mkdir()
    assert probe_writable(folder) is True
    assert list(folder.iterdir()) == []
    assert probe_writable(tmp_path / "missing") is False


def test_derived_paths_and_ensure(tmp_path: Path) -> None:
    paths = AppPaths(tmp_path / "data", DataDirMode.OVERRIDE, None, "test")
    data = tmp_path / "data"
    assert paths.state_file == data / "mod_state.json"
    assert paths.state_backup_file == data / "mod_state.backup.json"
    assert paths.pre_upgrade_state_file == data / "mod_state.pre-0.3.0.json"
    assert paths.corrupt_state_file("20250101-000000") == (
        data / "mod_state.corrupt.20250101-000000.json"
    )
    assert paths.settings_file == data / "settings.json"
    assert paths.ui_settings_file == data / "ui.ini"
    assert paths.lock_file == data / "ddmanager.lock"
    assert paths.logs_dir == data / "logs"
    assert paths.backups_dir == data / "backups"
    assert paths.profiles_dir == data / "profiles"
    assert paths.rules_dir == data / "rules"
    assert paths.user_rules_file == data / "rules" / "rules.json"
    assert paths.plugins_dir == data / "plugins"
    assert paths.cache_dir == data / "cache"
    assert paths.mod_info_cache_file == data / "cache" / "mod_info.v1.json"
    assert paths.icon_cache_dir == data / "icon_cache"
    assert paths.crash_log == data / "startup_crash.log"
    assert not data.exists()
    paths.ensure()
    for name in ("logs", "backups", "profiles", "rules", "plugins", "cache"):
        assert (data / name).is_dir()
