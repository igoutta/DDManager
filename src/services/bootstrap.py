"""The composition root of the services layer (no Qt): wires every service from an ``AppPaths``.

Used by the CLI today and by the GUI composition root later.  Nothing here ever raises for a
damaged user file: settings, rules, plugins and the metadata cache report ``Finding`` s instead
(``Services.startup_findings`` / ``rule_findings``) and fall back to defaults.
"""

from dataclasses import dataclass, field

from src.core.findings import Finding
from src.core.rules_data import RulesData
from src.core.saves import SaveFormatRegistry
from src.services.app_paths import AppPaths
from src.services.backup import BackupService
from src.services.detection import InstallDetector
from src.services.environment import Environment
from src.services.errors import PluginLoadError
from src.services.metadata_cache import MetadataCache
from src.services.platform_actions import detect_default_language
from src.services.plugin_loader import PluginRecord, load_builtin, load_user_plugins
from src.services.plugin_registry import PluginRegistry
from src.services.ports import Clock, ProcessProbe, SystemClock
from src.services.process import default_probe
from src.services.profiles import ProfileRepository
from src.services.rules_repo import load_rules, load_user_rule_modules
from src.services.save_patch import SavePatchService
from src.services.save_slots import SaveSlotService
from src.services.scan import ScanService
from src.services.settings_repo import Settings, SettingsRepository
from src.services.state_repo import StateRepository


@dataclass(frozen=True, slots=True)
class Services:
    paths: AppPaths
    env: Environment
    clock: Clock
    probe: ProcessProbe
    registry: PluginRegistry
    formats: SaveFormatRegistry
    state: StateRepository
    settings: SettingsRepository
    detector: InstallDetector
    scanner: ScanService
    cache: MetadataCache
    backups: BackupService
    patcher: SavePatchService
    slots: SaveSlotService
    profiles: ProfileRepository
    rules: RulesData
    rule_findings: tuple[Finding, ...]
    plugin_records: tuple[PluginRecord, ...]
    initial_settings: Settings = field(default_factory=Settings)
    """The settings value in force at start-up (the repository holds the persisted one)."""
    startup_findings: tuple[Finding, ...] = ()
    """Settings, plugin and cache findings gathered while wiring."""


def _register_rule_modules(
    registry: PluginRegistry, settings: Settings, paths: AppPaths
) -> tuple[list[PluginRecord], list[Finding]]:
    """User rule modules (hash-gated code) join the registry's rules."""
    rules, records, findings = load_user_rule_modules(paths.rules_dir, settings.rules)
    for rule in rules:
        try:
            registry.add_rule(rule)
        except PluginLoadError as exc:
            findings.append(Finding.warning("plugin.load_failed", str(exc)))
    return records, findings


def build_services(
    paths: AppPaths,
    *,
    env: Environment | None = None,
    clock: Clock | None = None,
    probe: ProcessProbe | None = None,
    settings: Settings | None = None,
) -> Services:
    """Create the data directories and wire every service; ``settings`` overrides the file."""
    environment = env if env is not None else Environment.from_host()
    now = clock if clock is not None else SystemClock()
    paths.ensure()
    settings_repo = SettingsRepository(paths.settings_file)
    startup: list[Finding] = []
    if settings is None:
        settings, loaded = settings_repo.load()
        startup.extend(loaded)
    registry = PluginRegistry()
    records = load_builtin(registry)
    user_records, plugin_findings = load_user_plugins(paths.plugins_dir, registry, settings.plugins)
    rule_records, module_findings = _register_rule_modules(registry, settings, paths)
    registry.freeze()
    rules, rules_findings = load_rules(paths)
    cache, cache_findings = MetadataCache.load(paths.mod_info_cache_file)
    startup.extend([*plugin_findings, *cache_findings])
    process = probe if probe is not None else default_probe(environment)
    formats = SaveFormatRegistry(registry.save_formats)
    backups = BackupService(paths, formats, clock=now, probe=process, policy=settings.backups)
    return Services(
        paths=paths,
        env=environment,
        clock=now,
        probe=process,
        registry=registry,
        formats=formats,
        state=StateRepository(
            paths, default_language=detect_default_language(environment), clock=now
        ),
        settings=settings_repo,
        detector=InstallDetector(environment),
        scanner=ScanService(registry.mod_sources, clock=now),
        cache=cache,
        backups=backups,
        patcher=SavePatchService(formats, backups, probe=process),
        slots=SaveSlotService(formats, clock=now),
        profiles=ProfileRepository(paths.profiles_dir),
        rules=rules,
        rule_findings=(*rules_findings, *module_findings),
        plugin_records=(*records, *user_records, *rule_records),
        initial_settings=settings,
        startup_findings=tuple(startup),
    )
