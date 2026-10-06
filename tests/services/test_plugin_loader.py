"""Plugin registry staging and the trust-gated plugin loader."""

import hashlib
import shutil
import sys
from pathlib import Path

import pytest

from src.core.saves import DEFAULT_SAVE_FORMATS
from src.plugins import BUILTIN_SOURCES
from src.rules import BUILTIN_RULES
from src.services.errors import PluginLoadError
from src.services.plugin_loader import (
    API_VERSION,
    PluginRecord,
    load_builtin,
    load_user_plugins,
    sha256_of,
)
from src.services.plugin_registry import PluginRegistry
from src.services.settings_repo import PluginTrust

REPO = Path(__file__).absolute().parents[2]


def plugin_source(rule_id: str, *, api: int | None = None, extra: str = "") -> str:
    header = f"API_VERSION = {api}\n" if api is not None else ""
    return (
        f"{header}"
        "class PlugRule:\n"
        f"    rule_id = {rule_id!r}\n"
        "    description = 'plugin rule'\n"
        "    def validate(self, ctx):\n"
        "        return []\n\n"
        "def register(registry):\n"
        f"{extra}"
        "    registry.add_rule(PlugRule())\n"
    )


def write(directory: Path, name: str, text: str) -> Path:
    path = directory / name
    path.write_bytes(text.encode("utf-8"))
    return path


def approve(directory: Path, *names: str, disabled: frozenset[str] = frozenset()) -> PluginTrust:
    approved = {n: sha256_of(directory / n) for n in names}
    return PluginTrust(enabled=True, approved=approved, disabled=disabled)


def status_of(records: list[PluginRecord]) -> dict[str, str]:
    return {r.path.name: r.status for r in records if r.path is not None}


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    path = tmp_path / "plugins"
    path.mkdir()
    return path


def rule_ids(registry: PluginRegistry) -> list[str]:
    return [rule.rule_id for rule in registry.rules]


# ------------------------------------------------------------------ registry


def test_registry_rejects_duplicate_ids() -> None:
    registry = PluginRegistry()
    registry.add_mod_source(BUILTIN_SOURCES[0])
    with pytest.raises(PluginLoadError):
        registry.add_mod_source(BUILTIN_SOURCES[0])
    registry.add_rule(BUILTIN_RULES[0])
    with pytest.raises(PluginLoadError):
        registry.add_rule(BUILTIN_RULES[0])
    registry.add_save_format(DEFAULT_SAVE_FORMATS[0])
    with pytest.raises(PluginLoadError):
        registry.add_save_format(DEFAULT_SAVE_FORMATS[0])
    assert len(registry.mod_sources) == len(registry.rules) == len(registry.save_formats) == 1


def test_staging_does_not_touch_the_parent_until_committed() -> None:
    parent = PluginRegistry()
    staged = parent.staging()
    staged.add_rule(BUILTIN_RULES[0])
    staged.add_mod_source(BUILTIN_SOURCES[0])
    assert (parent.rules, parent.mod_sources) == ((), ())
    contributed = staged.commit_into(parent)
    assert parent.rules == (BUILTIN_RULES[0],)
    assert parent.mod_sources == (BUILTIN_SOURCES[0],)
    assert BUILTIN_RULES[0].rule_id in " ".join(contributed)
    assert BUILTIN_SOURCES[0].source_id in " ".join(contributed)


def test_a_conflicting_commit_changes_nothing() -> None:
    parent = PluginRegistry()
    staged = parent.staging()
    staged.add_mod_source(BUILTIN_SOURCES[0])
    staged.add_rule(BUILTIN_RULES[0])
    parent.add_rule(BUILTIN_RULES[0])  # the parent changed after the staging area was cut
    with pytest.raises(PluginLoadError):
        staged.commit_into(parent)
    assert parent.rules == (BUILTIN_RULES[0],)
    assert parent.mod_sources == ()


def test_a_frozen_registry_refuses_additions() -> None:
    registry = PluginRegistry()
    registry.add_rule(BUILTIN_RULES[0])
    registry.freeze()
    with pytest.raises((PluginLoadError, RuntimeError)):
        registry.add_rule(BUILTIN_RULES[1])
    assert registry.rules == (BUILTIN_RULES[0],)


# ------------------------------------------------------------------ builtin


def test_builtin_plugins_register_everything_static() -> None:
    registry = PluginRegistry()
    records = load_builtin(registry)
    assert registry.mod_sources == BUILTIN_SOURCES
    assert registry.rules == BUILTIN_RULES
    assert registry.save_formats == DEFAULT_SAVE_FORMATS
    assert records
    assert {r.origin for r in records} == {"builtin"}
    assert {r.status for r in records} == {"loaded"}
    assert all(r.path is None for r in records)


# ------------------------------------------------------------------ user plugins


def test_a_trusted_plugin_loads_and_contributes(folder: Path) -> None:
    write(folder, "good.py", plugin_source("plug.good"))
    registry = PluginRegistry()
    records, findings = load_user_plugins(folder, registry, approve(folder, "good.py"))
    assert findings == []
    assert rule_ids(registry) == ["plug.good"]
    (record,) = records
    assert (record.origin, record.status, record.error) == ("user", "loaded", None)
    assert record.path == folder / "good.py"
    assert record.sha256 == hashlib.sha256((folder / "good.py").read_bytes()).hexdigest()
    assert any("plug.good" in item for item in record.contributed)
    assert "good" not in sys.modules


def test_trust_disabled_loads_nothing_and_executes_nothing(folder: Path) -> None:
    write(folder, "good.py", "open(__file__ + '.ran', 'w').close()\n" + plugin_source("plug.good"))
    registry = PluginRegistry()
    off = PluginTrust(enabled=False, approved={"good.py": sha256_of(folder / "good.py")})
    records, findings = load_user_plugins(folder, registry, off)
    assert (registry.rules, findings) == ((), [])
    assert all(r.status != "loaded" for r in records)
    assert not (folder / "good.py.ran").exists()


def test_unapproved_changed_and_disabled_plugins_are_not_run(folder: Path) -> None:
    marker = "open(__file__ + '.ran', 'w').close()\n"
    for name in ("new.py", "edited.py", "off.py"):
        write(folder, name, marker + plugin_source(f"plug.{name[:-3]}"))
    trust = PluginTrust(
        enabled=True,
        approved={"edited.py": "0" * 64, "off.py": sha256_of(folder / "off.py")},
        disabled=frozenset({"off.py"}),
    )
    registry = PluginRegistry()
    records, _ = load_user_plugins(folder, registry, trust)
    assert status_of(records) == {
        "edited.py": "changed",
        "new.py": "not_approved",
        "off.py": "disabled",
    }
    assert registry.rules == ()
    assert not list(folder.glob("*.ran"))
    assert next(r for r in records if r.status == "changed").sha256 == sha256_of(
        folder / "edited.py"
    )


def test_failures_are_isolated_and_leave_the_registry_untouched(folder: Path) -> None:
    write(folder, "a_syntax.py", "def register(:\n")
    write(folder, "b_raises.py", plugin_source("plug.b", extra="    raise RuntimeError('boom')\n"))
    write(folder, "c_exits.py", "import sys\nsys.exit(3)\n")
    write(folder, "d_no_register.py", "X = 1\n")
    write(folder, "e_good.py", plugin_source("plug.e"))
    write(folder, "_helper.py", plugin_source("plug.helper"))
    names = ("a_syntax.py", "b_raises.py", "c_exits.py", "d_no_register.py", "e_good.py")
    registry = PluginRegistry()
    records, findings = load_user_plugins(folder, registry, approve(folder, *names))
    assert status_of(records) == {
        "a_syntax.py": "failed",
        "b_raises.py": "failed",
        "c_exits.py": "failed",
        "d_no_register.py": "failed",
        "e_good.py": "loaded",
    }
    assert rule_ids(registry) == ["plug.e"]
    assert [f.rule_id for f in findings].count("plugin.load_failed") == 4
    assert all(r.error for r in records if r.status == "failed")


def test_a_plugin_that_fails_halfway_leaves_nothing_behind(folder: Path) -> None:
    source = plugin_source(
        "plug.half",
        extra="    registry.add_rule(PlugRule.__new__(PlugRule))\n    raise RuntimeError('late')\n",
    ).replace("class PlugRule:", "class PlugRule:\n    pass_marker = True")
    write(folder, "half.py", source)
    registry = PluginRegistry()
    records, findings = load_user_plugins(folder, registry, approve(folder, "half.py"))
    assert status_of(records) == {"half.py": "failed"}
    assert registry.rules == ()
    assert [f.rule_id for f in findings] == ["plugin.load_failed"]


def test_future_api_versions_are_incompatible(folder: Path) -> None:
    write(folder, "future.py", plugin_source("plug.future", api=API_VERSION + 1))
    write(folder, "current.py", plugin_source("plug.current", api=API_VERSION))
    registry = PluginRegistry()
    records, _ = load_user_plugins(folder, registry, approve(folder, "future.py", "current.py"))
    assert status_of(records) == {"current.py": "loaded", "future.py": "incompatible"}
    assert rule_ids(registry) == ["plug.current"]


def test_duplicate_ids_fail_the_later_plugin(folder: Path) -> None:
    write(folder, "a_first.py", plugin_source("plug.same"))
    write(folder, "b_second.py", plugin_source("plug.same"))
    write(folder, "c_builtin_clash.py", plugin_source(BUILTIN_RULES[0].rule_id))
    registry = PluginRegistry()
    load_builtin(registry)
    builtin_count = len(registry.rules)
    records, findings = load_user_plugins(
        folder, registry, approve(folder, "a_first.py", "b_second.py", "c_builtin_clash.py")
    )
    assert status_of(records) == {
        "a_first.py": "loaded",
        "b_second.py": "failed",
        "c_builtin_clash.py": "failed",
    }
    assert rule_ids(registry).count("plug.same") == 1
    assert len(registry.rules) == builtin_count + 1
    assert [f.rule_id for f in findings] == ["plugin.load_failed"] * 2


def test_plugins_load_in_file_name_order(folder: Path) -> None:
    for name in ("m_mid.py", "z_last.py", "a_first.py"):
        write(folder, name, plugin_source(f"plug.{name[:-3]}"))
    registry = PluginRegistry()
    load_user_plugins(folder, registry, approve(folder, "m_mid.py", "z_last.py", "a_first.py"))
    assert rule_ids(registry) == ["plug.a_first", "plug.m_mid", "plug.z_last"]


def test_missing_directory_is_empty(tmp_path: Path) -> None:
    registry = PluginRegistry()
    assert load_user_plugins(tmp_path / "nope", registry, PluginTrust(enabled=True)) == ([], [])


def test_sha256_of_hashes_the_file_bytes(folder: Path) -> None:
    path = write(folder, "x.py", "print('x')\n")
    assert sha256_of(path) == hashlib.sha256(b"print('x')\n").hexdigest()


def test_the_nexus_example_is_a_valid_user_plugin(folder: Path) -> None:
    shutil.copy(REPO / "src" / "plugins" / "nexus_example.py", folder / "nexus_example.py")
    registry = PluginRegistry()
    records, findings = load_user_plugins(folder, registry, approve(folder, "nexus_example.py"))
    assert findings == []
    assert status_of(records) == {"nexus_example.py": "loaded"}
    assert [s.source_id for s in registry.mod_sources] == ["nexus"]
