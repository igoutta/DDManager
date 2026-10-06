"""rules_repo: bundled + user rules documents, and trust-gated user rule modules."""

import hashlib
import json
import sys
from pathlib import Path
from typing import cast

import pytest

from src.core.findings import Finding, Severity
from src.core.rules_data import merge_rules, parse_rules_data
from src.core.validation import ValidationContext
from src.services.plugin_loader import sha256_of
from src.services.rules_repo import load_bundled_rules, load_rules, load_user_rule_modules
from src.services.settings_repo import PluginTrust

USER_RULES = {
    "format": "ddmanager.rules",
    "format_version": 1,
    "overlap": {"ignore": ["*.psd"], "merge": ["*.merge"]},
    "mods": {
        "steam:1234567": {"tier": "patch", "load_after": ["title:The Chorus"]},
        "key:my_folder": {"tier": "class"},
    },
}

RULE_MODULE = """
from src.core.findings import Finding, Severity

DESCRIPTION = "flags everything"
RAN = True


def validate(ctx):
    return [Finding.at(Severity.WARNING, "user.flag", "flagged")]
"""

MARKER_MODULE = """
from pathlib import Path

Path(__file__).with_name("ran.marker").write_text("ran", "utf-8")


def validate(ctx):
    return []
"""


def trust_for(directory: Path, *names: str, disabled: frozenset[str] = frozenset()) -> PluginTrust:
    approved = {n: sha256_of(directory / n) for n in names}
    return PluginTrust(enabled=True, approved=approved, disabled=disabled)


def ids(findings: list[Finding]) -> list[str]:
    return [f.rule_id for f in findings]


# ------------------------------------------------------------------ documents


def test_bundled_rules_are_the_shipped_default_document() -> None:
    data, findings = load_bundled_rules()
    assert findings == []
    assert data.mods == ()
    assert data.overlap_ignore == ("project.xml", "modfiles.txt", "preview_icon.*", "*.bak")
    assert data.overlap_merge == ("localization/*.string_table.xml",)


def test_bundled_rules_reject_key_refs(monkeypatch: pytest.MonkeyPatch) -> None:
    text = json.dumps({**USER_RULES, "mods": {"key:my_folder": {"tier": "class"}}})

    class Entry:
        def __truediv__(self, _name: str) -> Entry:
            return self

        def joinpath(self, *_names: str) -> Entry:
            return self

        def read_text(self, *_args: object, **_kwargs: object) -> str:
            return text

        def read_bytes(self) -> bytes:
            return text.encode("utf-8")

    monkeypatch.setattr("importlib.resources.files", lambda *_a, **_k: Entry())
    monkeypatch.setattr("src.services.rules_repo.files", lambda *_a, **_k: Entry(), raising=False)
    data, findings = load_bundled_rules()
    assert data.mods == ()
    assert "rules.bad_ref" in ids(findings)


def test_load_rules_without_a_user_file_is_the_bundled_set(app_paths) -> None:
    assert load_rules(app_paths) == load_bundled_rules()


def test_user_rules_merge_over_the_bundled_ones_and_may_use_key_refs(app_paths) -> None:
    app_paths.user_rules_file.write_text(json.dumps(USER_RULES), "utf-8")
    data, findings = load_rules(app_paths)
    assert findings == []
    user, user_findings = parse_rules_data(json.dumps(USER_RULES), allow_key_refs=True)
    assert user_findings == []
    bundled, _ = load_bundled_rules()
    assert data == merge_rules(bundled, user)
    assert {rule.ref for rule in data.mods} == {"steam:1234567", "key:my_folder"}
    assert data.overlap_ignore == (*bundled.overlap_ignore, "*.psd")
    assert data.overlap_merge == (*bundled.overlap_merge, "*.merge")


def test_a_broken_user_file_never_raises_and_is_left_alone(app_paths) -> None:
    app_paths.user_rules_file.write_text("{not json", "utf-8")
    data, findings = load_rules(app_paths)
    assert data == load_bundled_rules()[0]
    assert findings
    assert app_paths.user_rules_file.read_text("utf-8") == "{not json"


def test_user_rule_problems_are_reported(app_paths) -> None:
    doc = {**USER_RULES, "mods": {"nonsense": {}, "steam:77": {"tier": "patch"}}}
    app_paths.user_rules_file.write_text(json.dumps(doc), "utf-8")
    data, findings = load_rules(app_paths)
    assert "rules.bad_ref" in ids(findings)
    assert [rule.ref for rule in data.mods] == ["steam:77"]


# ------------------------------------------------------------------ rule modules


def test_rule_modules_load_only_when_trusted_and_unchanged(tmp_path: Path) -> None:
    (tmp_path / "flag_all.py").write_text(RULE_MODULE, "utf-8")
    rules, records, findings = load_user_rule_modules(tmp_path, trust_for(tmp_path, "flag_all.py"))
    assert findings == []
    (rule,) = rules
    assert rule.rule_id == "user.flag_all"
    assert rule.description == "flags everything"
    (finding,) = rule.validate(cast("ValidationContext", None))  # the rule ignores ctx
    assert (finding.rule_id, finding.severity) == ("user.flag", Severity.WARNING)
    (record,) = records
    assert (record.origin, record.status, record.error) == ("user", "loaded", None)
    assert record.path == tmp_path / "flag_all.py"
    assert record.sha256 == hashlib.sha256((tmp_path / "flag_all.py").read_bytes()).hexdigest()
    assert "user.flag_all" in record.contributed


def test_rule_module_uses_its_own_rule_id(tmp_path: Path) -> None:
    (tmp_path / "named.py").write_text('RULE_ID = "mine.check"\n' + RULE_MODULE, "utf-8")
    (rule,), _, _ = load_user_rule_modules(tmp_path, trust_for(tmp_path, "named.py"))
    assert rule.rule_id == "mine.check"


def test_untrusted_modules_are_never_executed(tmp_path: Path) -> None:
    (tmp_path / "marker.py").write_text(MARKER_MODULE, "utf-8")
    off = PluginTrust(enabled=False, approved={"marker.py": sha256_of(tmp_path / "marker.py")})
    assert load_user_rule_modules(tmp_path, off)[0] == []
    rules, records, _ = load_user_rule_modules(tmp_path, PluginTrust(enabled=True))
    assert rules == []
    assert [r.status for r in records] == ["not_approved"]
    (tmp_path / "marker.py").write_text(MARKER_MODULE + "\n# edited\n", "utf-8")
    stale = PluginTrust(enabled=True, approved={"marker.py": "0" * 64})
    rules, records, _ = load_user_rule_modules(tmp_path, stale)
    assert rules == []
    assert [r.status for r in records] == ["changed"]
    disabled = trust_for(tmp_path, "marker.py", disabled=frozenset({"marker.py"}))
    rules, records, _ = load_user_rule_modules(tmp_path, disabled)
    assert rules == []
    assert [r.status for r in records] == ["disabled"]
    assert not (tmp_path / "ran.marker").exists()


def test_broken_rule_modules_fail_without_stopping_the_others(tmp_path: Path) -> None:
    (tmp_path / "a_bad_syntax.py").write_text("def validate(:\n", "utf-8")
    (tmp_path / "b_no_validate.py").write_text("X = 1\n", "utf-8")
    (tmp_path / "c_raises.py").write_text("raise RuntimeError('boom')\n", "utf-8")
    (tmp_path / "d_exits.py").write_text("import sys\nsys.exit(3)\n", "utf-8")
    (tmp_path / "e_good.py").write_text(RULE_MODULE, "utf-8")
    (tmp_path / "_private.py").write_text(RULE_MODULE, "utf-8")
    names = [p.name for p in sorted(tmp_path.glob("*.py")) if not p.name.startswith("_")]
    rules, records, findings = load_user_rule_modules(tmp_path, trust_for(tmp_path, *names))
    assert [r.rule_id for r in rules] == ["user.e_good"]
    status = {r.path.name: r.status for r in records if r.path}
    assert status == {
        "a_bad_syntax.py": "failed",
        "b_no_validate.py": "failed",
        "c_raises.py": "failed",
        "d_exits.py": "failed",
        "e_good.py": "loaded",
    }
    assert ids(findings).count("plugin.load_failed") == 4
    assert all(r.error for r in records if r.status == "failed")


def test_rule_modules_do_not_pollute_sys_modules(tmp_path: Path) -> None:
    (tmp_path / "isolated_rule_mod.py").write_text(RULE_MODULE, "utf-8")
    load_user_rule_modules(tmp_path, trust_for(tmp_path, "isolated_rule_mod.py"))
    assert "isolated_rule_mod" not in sys.modules


def test_missing_directory_is_empty(tmp_path: Path) -> None:
    assert load_user_rule_modules(tmp_path / "nope", PluginTrust(enabled=True)) == ([], [], [])
