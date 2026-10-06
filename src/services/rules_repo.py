"""Community rules (data) and user rule modules (code).

* ``default_rules.json`` ships inside the package and may NOT use ``key:`` refs (folder names are
  not stable across installs); the user's ``<data>/rules/rules.json`` may.  A user entry replaces
  the bundled entry of the same ref wholesale (:func:`~src.core.rules_data.merge_rules`).
* ``<data>/rules/*.py`` modules exporting ``validate(ctx)`` become rules with the id prefix
  ``user.``; they are code, so they pass the same opt-in/hash gate as plugins
  (:func:`~src.services.plugin_loader.import_gated`).
"""

from dataclasses import replace
from importlib import resources
from pathlib import Path
from types import ModuleType
from typing import Final

from src.core.findings import Finding
from src.core.rules_data import EMPTY_RULES, RulesData, merge_rules, parse_rules_data
from src.core.validation import ModuleRule, Rule
from src.services.app_paths import AppPaths
from src.services.plugin_loader import PluginRecord, import_gated, plugin_files
from src.services.settings_repo import PluginTrust

_BUNDLED: Final = ("resources", "default_rules.json")


def load_bundled_rules() -> tuple[RulesData, list[Finding]]:
    """The shipped rules; ``key:`` refs are rejected (``allow_key_refs=False``)."""
    resource = resources.files("src").joinpath(*_BUNDLED)
    try:
        text = resource.read_text(encoding="utf-8")
    except OSError as exc:
        message = f"The bundled rules file could not be read: {exc}"
        return EMPTY_RULES, [Finding.error("rules.bundled_unreadable", message)]
    return parse_rules_data(text, allow_key_refs=False)


def load_user_rules(path: Path) -> tuple[RulesData, list[Finding]]:
    """The user's rules file (``key:`` refs allowed); a missing file is not a problem."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return EMPTY_RULES, []
    except (OSError, UnicodeDecodeError) as exc:
        message = f"The rules file {path.name} could not be read: {exc}"
        return EMPTY_RULES, [Finding.warning("rules.user_unreadable", message)]
    return parse_rules_data(text, allow_key_refs=True)


def load_rules(paths: AppPaths) -> tuple[RulesData, list[Finding]]:
    """Bundled rules merged with the user's rules file."""
    bundled, findings = load_bundled_rules()
    user, user_findings = load_user_rules(paths.user_rules_file)
    return merge_rules(bundled, user), [*findings, *user_findings]


def _rule_from(module: ModuleType, stem: str) -> Rule:
    """Wrap ``module``; an undeclared ``RULE_ID`` becomes ``user.<file stem>`` (the private
    import name of the gated loader must not leak into the id)."""
    rule = ModuleRule.from_module(module, default_prefix="user")
    declared = getattr(module, "RULE_ID", None)
    if isinstance(declared, str) and declared:
        return rule
    return replace(rule, rule_id=f"user.{stem}")


def load_user_rule_modules(
    directory: Path, trust: PluginTrust
) -> tuple[list[Rule], list[PluginRecord], list[Finding]]:
    """Approved ``*.py`` rule modules of ``directory``; nothing unless ``trust.enabled``."""
    rules: list[Rule] = []
    records: list[PluginRecord] = []
    findings: list[Finding] = []
    if not trust.enabled:
        return rules, records, findings
    for path in plugin_files(directory):
        gated = import_gated(path, trust, namespace="rule")
        findings.extend(gated.findings)
        if gated.module is None:
            records.append(gated.record)
            continue
        try:
            rule = _rule_from(gated.module, path.stem)
        except TypeError as exc:
            message = f"{path.name} could not be loaded: {exc}"
            findings.append(Finding.warning("plugin.load_failed", message))
            records.append(replace(gated.record, status="failed", error=str(exc)))
            continue
        rules.append(rule)
        records.append(replace(gated.record, contributed=(rule.rule_id,)))
    return rules, records, findings
