# Architecture

DD Manager is a layered Python 3.14 application. The one package folder is literally `src/`, so
the import name is `src` (`from src.core.load_order import LoadOrder`); the distribution and the
console script are called `ddmanager`. Every rule below is enforced by a test, not by convention.

## Layers

```text
   app.py  composition root: arguments, data folder, logging, QApplication, theme, services,
      |    plugins, controller, window.   (src/cli*.py is its headless twin: services, no Qt)
      v
   ui.widgets, ui.dialogs, ui.theme       render view models, emit intents; never import services
      |
      v
   ui.controller*, ui.presenters          session, workers, view models; the only UI code that
      |                                   uses services; they own ui.models (Qt item models)
      v
   services   <----   plugins             all I/O; plugins are mod sources built on services
      |
      v
   core       <----   rules               pure domain; rules are pure checks built on core
```

In words: **ui -> controller/presenters -> services -> core**, **plugins -> services -> core**,
**rules -> core**, and only `app.py` (and `app_selftest.py`) sees all of them. The one apparent
loop is deliberate and static: `services/plugin_loader.py` imports the built-in `src.plugins` and
`src.rules` so a frozen build finds them without scanning the file system, while the plugins import
the service contracts (`services/sources.py`, `mod_reader.py`). No module-level cycle results.

The real edges between layers, computed from the imports (a PySide6 import is not shown):

| Layer | Imports |
| --- | --- |
| `core` | nothing from `src` outside `core` |
| `rules` | `core` |
| `services` | `core`; `plugin_loader` also imports `plugins` and `rules` to register the built-ins |
| `plugins` | `core`, `services` |
| `ui.models` | `core`, `ui` support modules |
| `ui.controller*`, `ui.presenters` | `core`, `rules`, `services`, `ui.*` |
| `ui.widgets`, `ui.dialogs` | `core`, `ui.*` (not `services`) |
| `cli*.py` | `core`, `services`; `cli.py` starts `src.app` when no subcommand is given |

## Repository layout

```text
DDManager/
|- pyproject.toml  uv.lock  .python-version  justfile   hatchling, ruff, ty, pytest config; Python 3.14
|- run.py                       source launcher, pinned to <repo>/DD Manager Data
|- README.md BUILD.md CHANGELOG.md LICENSE.md
|- docs/                        architecture.md  migration.md  load-order-semantics.md
|- packaging/                   ddmanager.spec  entry.py  build.ps1  version_info.tmpl  ddmanager.ico  (frozen build)
|- tools/                       regen_goldens.py  make_corpus.py  corpus_env.py  probe_kit.py  clean.py  make_icon.py
|- research/                    historical DSON scripts, not maintained (README inside)
|- modding/                     sample mods, used read-only as test fixtures
|- tests/                       see "Test strategy"
|- src/
|  |- __about__.py              the version (single source)
|  |- __main__.py               python -m src
|  |- app.py                    GUI composition root;  app_selftest.py  --self-test
|  |- cli.py cli_context.py cli_save.py cli_scan.py cli_profile.py    headless commands
|  |- core/                     PURE domain (stdlib only)
|  |  |- ids.py model.py identity.py identity_text.py display.py text.py project_xml.py
|  |  |                         ModId, SaveIdentity, ModSnapshot/ModInfo, the one identity decision
|  |  |- load_order.py reorder.py diff.py sorting.py     LoadOrder value type, selection moves, Auto-Sort
|  |  |- categories.py tiers.py classify.py              categories, tiers, category suggestion
|  |  |- findings.py validation.py                       Finding/Fix, Rule protocol, run_rules, apply_fix
|  |  |- rules_format.py rules_resolve.py rules_data.py  the rules.json format and its resolution
|  |  |- loadorder_document.py loadorder_resolve.py loadout_v02.py loadorder_file.py
|  |  |                         ddmanager.loadorder v1 JSON, matching onto installed mods, 0.2 loadout import
|  |  |- state_migrate.py state_sanitize.py state_file.py   mod_state.json schema (22 keys)
|  |  |- folder_order.py diagnostics.py errors.py json_values.py
|  |  `- saves/                 the save codec (see "The save format")
|  |     |- format.py           SaveFormat protocol, SaveFormatRegistry, validation report
|  |     |- dson_v1.py          DsonV1Format: sniff / validate / read_applied / write_applied
|  |     |- applied_text.py     "Generate Save Code" text
|  |     `- dson/               layout, fields, walk, validate, document, splice, edits, readers
|  |- rules/                    one module per health rule + BUILTIN_RULES
|  |- services/                 I/O: app_paths environment fsutil detection steam_locations save_discovery
|  |                            sources scan mod_reader metadata_cache state_repo settings_repo backup
|  |                            backup_index save_patch save_slots profiles rules_repo plugin_loader
|  |                            plugin_registry folder_renamer process platform_actions ports errors bootstrap
|  |- plugins/                  built-in mod sources: local_folder.py steam_workshop.py; nexus_example.py (not registered)
|  |- resources/                default_rules.json  i18n/{en,zh_CN,pt_PT,es_ES}.json  icons/*.svg
|  `- ui/                       PySide6
|     |- controller.py controller_*.py   MainController and its flows (scan, edits, findings, save, state sync ...)
|     |- presenters/            categories paths profiles settings tools trust backups labels (+ plain DTO modules)
|     |- models/                available_model available_proxy load_order_model findings_model roles
|     |- widgets/               main_window panes, mod views, delegates, health dock, status bar, actions, menus
|     |- dialogs/               patch preview, order diff, profile manager, categories, paths, settings, ...
|     |- theme/                 tokens.py (palette) theme.py dark.qss style.py
|     `- catalog.py i18n.py viewmodels.py session.py workers.py thumbnails.py undo.py errors.py ports.py qt_compat.py
```

## The enforced import matrix

`tests/test_layering.py` walks every module under `src/` with the stdlib `ast` module (no extra
dependency). A layer must not import the prefixes listed for it:

```python
FORBIDDEN: dict[str, tuple[str, ...]] = {
    "src.core": (
        "PySide6",
        "shiboken6",
        "src.services",
        "src.ui",
        "src.plugins",
        "src.rules",
        "tkinter",
    ),
    "src.rules": ("PySide6", "shiboken6", "src.services", "src.ui", "src.plugins", "tkinter"),
    "src.services": ("PySide6", "shiboken6", "src.ui", "tkinter"),
    "src.plugins": ("PySide6", "shiboken6", "src.ui", "tkinter"),
    "src.ui.models": ("src.services", "PySide6.QtWidgets"),
    "src.ui.widgets": ("src.services",),
    "src.ui.dialogs": ("src.services",),
    "src.ui.theme": ("src.services",),
    "src": ("dd2", "categories", "localization", "paths", "state", "legacy_loadout", "research"),
}
```

The last row keeps the deleted v0.2.x module names (and the `research/` folder) from ever being
imported again. `ui.controller*`, `ui.presenters` and `ui/session.py` (the controller's working
state) have no ban: they are the only UI code that touches services.

`tests/test_purity.py` is stricter for `src/core` and `src/rules`: only an allowlist of stdlib
modules (`struct`, `dataclasses`, `enum`, `re`, `json`, `hashlib`, `datetime`, `xml.etree`, ...) and
`src.core`/`src.rules` may be imported; `open`, `print`, `input`, `exec` and `eval` are forbidden;
no `.exists()`, `.read_text()`, `.stat()`, `.iterdir()`, `.mkdir()`, `.now()`, `.time()` and the
like; only `PurePath` types may be imported from `pathlib`, never a concrete `Path`. That is what
makes `just test-core` (the domain tests with `pytest-qt` disabled) prove that nothing below
`ui` needs Qt.

## Data flow

Everything the window does is a pipeline of small steps; the controller runs the I/O ones in a
worker (`ui/workers.py`) and applies the result on the GUI thread.

```text
scan -> reconcile -> classify-new -> validate -> plan -> backup -> patch
```

1. **scan** (`ui/controller_scan.run_scan`, worker). `InstallDetector.detect` reads the registry,
   Steam library VDFs and ACF manifests once and returns an `InstallSnapshot` (game roots, mod
   roots, saves). `ScanService.scan` asks every `ModSource` (built-ins: Steam Workshop, local
   folders) to `discover` folders and `snapshot` them (`mod_reader`: one `project.xml` parse, one
   directory walk, one localization pass), then calls `derive_mod_info`, the single identity
   decision point. The first mod root wins a duplicated folder name; shadowed copies become
   `scan.shadowed` findings. A source or folder that raises becomes a finding, never an aborted scan.
   Before reading a folder the scan takes its stat-only signature (`mod_reader.signature_of`:
   `project.xml` mtime, localization signature, Workshop `timeupdated`, newest top-level folder
   mtime) and asks the `MetadataCache`; a hit reuses the cached `ModInfo` (file manifest included),
   a miss is read, derived and returned in `ScanResult.cache_updates`. `scan_with_cache` commits
   those, sweeps the entries of folders that are gone and saves `cache/mod_info.v1.json`; a cache
   that cannot be written is a `cache.not_saved` finding, never a failed scan.
2. **reconcile** (`LoadOrder.reconcile`). The folders found on disk are merged into the saved order:
   known entries keep order and flags, unknown folders are appended, disabled, in casefolded name
   order. Absent mods stay in the order and are reported (`core.missing_from_disk`). Nothing is
   pruned and nothing is re-sorted.
3. **classify-new** (`controller_scan.classify_new`). A mod with no category that was never
   attempted gets one from its remembered category (`category_memory`) or from the heuristic
   `suggest_category`; the attempt is recorded in `auto_category_attempted`. This assigns
   categories only and never touches the order. Each mod's tier is then resolved: rules file tier,
   else its category's tier, else `unassigned` (`resolve_tier`).
4. **validate** (`FindingsFlow.validate`, worker, 250 ms after each change). A `ValidationContext`
   (order, mods, tiers, resolved rules, priority setting, precedence) is handed to `run_rules`
   with every registered rule (built-in plus approved user rules). A rule that raises becomes one
   `internal.rule_failed` finding. Fixes are values (`MakeWin`, `DisableMods`, `EnableMods`,
   `SetTier`) that `apply_fix` turns into a new `LoadOrder`.
5. **plan** (`SavePatchService.plan`, worker). The enabled mods that are on disk map to
   `SaveIdentity` values (`applied_entries` with the session's missing set: an enabled mod whose
   folder is gone is never written, not even from v0.2.1's `metadata`); the save is read, its
   format detected, validated and rewritten **in memory**. The plan carries the before/after
   entries, a diff, the risks (`required_acks`) and the sha256 of the bytes it was made from.
   Writing nothing yet. The preview (`PatchPreviewVM`) adds the ERROR findings of the current
   `ValidationReport`: with any of them, or an ERROR in the plan, it is `blocking` and the dialog's
   primary button stays disabled until "Patch despite N errors" is ticked; a cancelled dialog never
   applies.
6. **backup** (`BackupService.create`). `apply` refuses while the game runs, requires every
   acknowledgement, re-reads the save and refuses if its sha256 changed, then backs up those exact
   bytes into `DD Manager Data/backups/` (and prunes by the retention policy).
7. **patch** (`atomic_write_bytes`). The patched bytes go to a temp file in the save's folder, are
   fsynced, read back from disk and verified (`check` plus: the entries read back equal the plan),
   and only then replace the save. On any failure the original stays byte-identical and the temp
   file is removed.

The same services serve the CLI: `ddmanager save plan|patch` run steps 1 and 5-7 without Qt.

## The save format

A save (`persist.game.json`) is not JSON: it is Darkest Dungeon's binary **DSON** container. The
codec (`src/core/saves`, `DsonV1Format`, format id `dson.v1`) understands four regions:

| Region | Layout |
| --- | --- |
| **header** (64 bytes) | magic `[0:4]`, revision `[4:8]`, then little-endian `i32` fields: `header_length`@8 (64), `meta1_size`@16, `meta1_count`@20, `meta1_offset`@24 (64), `meta2_count`@44, `meta2_offset`@48, `data_length`@56, `data_offset`@60. Other bytes are passed through verbatim. |
| **meta1** | one 16-byte record per **object**: parent object index (-1 for the root), its meta2 index, `direct_children`, `all_children` (every descendant field) |
| **meta2** | one 12-byte record per **field**, in data order: name hash (`h = h * 53 + byte`, 32-bit, signed), data-relative offset, info (bit 0 = is object, bits 2-10 = name length including NUL, bits 11-30 = meta1 index, bit 31 = unknown game flag: never interpreted, preserved per entry, cleared for new entries) |
| **data** | every field starts with its NUL-terminated name; objects have no payload; a 1-byte payload (bool) is unaligned, anything longer starts at the next 4-byte boundary of the data block; a string is an `i32` length (including NUL), UTF-8 bytes, NUL |

The block DD Manager owns is `applied_ugcs_1_0`, a direct child of the root object. Its children
are objects named `"0"`, `"1"`, ... `"N-1"`, each with two string fields, `name` and `source`:

```text
applied_ugcs_1_0
  "0": { name: "1234567890",      source: "Steam" }              Workshop mod: PublishedFileId
  "1": { name: "Example Tweaks",  source: "mod_local_source" }    local mod: title (or folder name)
```

**Identity rules** (`core/identity.resolve_save_identity`, identical to v0.2.1, so the game sees the
same entries): a mod under `steamapps/workshop/content/262060` is written as
`(PublishedFileId, "Steam")`, where the project's `PublishedFileId` wins over the folder name. A
local mod is written as `(Title, "mod_local_source")` when the `project.xml` `<Title>` passes the
display gate (colour markup, `%`, angle brackets, tooltip words and "N combats" are rejected; a
title without Latin letters is accepted only when the folder name has none either or is a plain
number); otherwise as the folder name with leading numeric `NNNN_` prefixes removed. Names are
UTF-8 end to end.

**Reading and writing.** `read_applied` returns the identities (an absent block reads as empty).
`write_applied` replaces the block, or inserts it before `persistent_ugcs` when the save has none;
it refuses (`DsonUnsupportedError`) a block that is a scalar or not a direct child of the root, and
a save with no `persistent_ugcs` anchor. Every edit goes through one `splice` primitive that
rebuilds meta1/meta2/header and re-pads moved fields; `assert_shift_safe` refuses a move that would
corrupt data it does not understand. `write_applied` is deterministic and frozen: the goldens under `tests/golden/dson` pin its bytes
for a matrix of save shapes, and the corpus check proves that a save the game wrote survives its
own identity rewrite byte for byte. **Bit 31 of `info`** is a flag the game sets sporadically
(inside the applied block on child objects, `name` and `source` words alike, and on scalars
elsewhere) and loads either way. Fields outside the block keep it verbatim; inside the block each
entry whose `(name, source)` already existed keeps the original state of its three words
(positional among duplicates), a new entry gets it clear (`dson/flags.py`). DD Manager 0.2.x
cleared it on every rewrite; since 0.3.1 it is preserved.

**Validation has two levels** (`ddmanager save inspect` prints both):

- **structural**: what parsing requires: file size equals `data_offset + data_length`;
  `meta1_size == meta1_count * 16`; `meta2_offset` follows meta1; `data_offset` follows meta2;
  meta2 offsets are sorted; the stack walk over fields is consistent; the object count matches the
  header. Only structurally valid saves are ever patched.
- **strict**: additionally the magic `01 b1 00 00` (unverified against real saves, so only reported,
  never a gate), `header_length` and `meta1_offset` equal 64, strictly increasing offsets, each
  object's meta1 index equal to its running number, exact `all_children`, and exactly one root.
  Neither level reports bit 31 of `info`: it is not part of the format the validator checks.

`write_applied` gates: the input must be structurally valid; the output must be structurally valid, must not be
strict-worse than the input, and must read back exactly the requested entries. Format detection
(`sniff`) needs 64 bytes with `header_length == 64` and `meta1_offset == 64`; a file starting with
`{` is reported as "is this a decoded text save?". New formats plug in through the `SaveFormat`
protocol and `SaveFormatRegistry` (detection requires exactly one match).

## The load-order model

- `LoadOrder(entries, enabled)` (`core/load_order.py`) mirrors `mod_state.json`: `entries` is the
  `order` list (disabled and missing mods keep their slots), `enabled` the set of enabled ids.
- `active()` is the enabled entries in order: the list written to the save. **Rank N is
  `active()[N-1]` and is applied entry N-1.** `rank(mod)` is 1-based and `None` when disabled.
- Edits are pure and act on `active()`, then splice back over the active slots so inactive entries
  never move: `move(ids, TOP|UP|DOWN|BOTTOM)`, `move_to(ids, gap)` (a drop at insertion point `gap`),
  `enable(ids, at=None)` (append after the last active entry, or at a gap), `disable(ids)`,
  `forget(ids)`, `reconcile(present)`.
- **First entry wins.** `PrioritySetting(direction=FIRST_WINS, verified=True)` is a setting, not a
  constant. `precedence(direction)` maps each active mod to a strength: `0` loses every conflict;
  with first-wins rank 1 has the highest value, with last-wins it has `0`. Rules compare
  precedence, never ranks, so flipping the direction changes verdicts and labels but not bytes.
  While `verified` is false, direction-dependent findings are capped at INFO
  (`ValidationContext.capped`). Details and the probe protocol: `docs/load-order-semantics.md`.
- **Tiers live in precedence space.** `TierTable.from_categories(category_order, custom_categories)`
  gives `overhaul` weight 0, each category in editor order `(i + 1) * 100`, then `unassigned`, then
  `patch` (highest). `auto_sort` orders active mods by `(tier weight, current precedence)` and honours
  declared precedence edges with a heap-based Kahn sort; cycles become one `core.sort_cycle` error
  and their edges are dropped. With first-wins the highest precedence is placed at index 0.

## Where state lives

All user data is in one folder, **`DD Manager Data`**, resolved only by
`services/app_paths.resolve_app_paths` (never from the working directory or `sys.argv`):
`--data-dir`, then `DDMANAGER_DATA_DIR`, then `DD Manager Data` next to the executable (frozen) or
at the repository root (source), and only when that folder does not exist yet and its parent is not
writable, the per-user folder (`%LOCALAPPDATA%\DD Manager`). An existing but unwritable portable
folder raises `DataDirNotWritableError` instead of silently starting a second copy of your state.

| Path under `DD Manager Data` | Owner | Contents |
| --- | --- | --- |
| `mod_state.json` | `state_repo` | the 22-key state document plus `schema_version: 1` (below) |
| `mod_state.backup.json` | `state_repo` | previous main file; rotated only from a parseable main |
| `mod_state.pre-0.3.0.json` | `state_repo` | one-time copy made on the first 0.3.0 GUI launch |
| `mod_state.corrupt.<ts>.json` | `state_repo` | an unreadable main, preserved before it is replaced |
| `settings.json` | `settings_repo` | `ddmanager.settings` v1: priority direction and verified flag, active profile, selected save, backup retention, plugin and rule-module trust (approved SHA-256 per file), language; unknown keys kept |
| `ui.ini` | `ui/widgets/main_window` | window geometry, splitter and dock state (`QSettings`) |
| `profiles/<slug>.loadorder.json` | `profiles` | named load orders (`ddmanager.loadorder` v1) |
| `backups/<save folder>-<hash8>/` | `backup`, `backup_index` | `persist.game.backup.<YYYYMMDD-HHMMSS>[-N].json` plus `index.json` (reason, time, size, sha256) |
| `rules/rules.json`, `rules/*.py` | `rules_repo` | user rules file; user rule modules (opt-in, SHA-256 approved) |
| `plugins/*.py` | `plugin_loader` | user plugins (opt-in, SHA-256 approved) |
| `logs/ddmanager.log`, `logs/faulthandler.log` | `ui/errors` | rotating log (1 MB x 3), fault handler output |
| `cache/mod_info.v1.json` | `metadata_cache`, `scan` | the derived `ModInfo` of every scanned folder (file manifest included), keyed by source and path, validated by the stat signature above; written after each scan, stale entries swept; deleting it forces a full re-read |
| `icon_cache/` | none | kept for v0.2.1; no longer written |
| `ddmanager.lock` | `QLockFile` | single-instance lock |

`mod_state.json` keeps v0.2.1's schema, parsed tolerantly by `core/state_file.parse_state` (a
wrongly typed value is repaired with a `state.*` finding where v0.2.1 would crash) and rendered by
`render_state`, which starts from the untouched original document, so unknown keys and key order
survive. The 22 keys: `language`, `mods_path`, `last_save_path`, `last_backup_path`,
`last_output_path`, `selected_profile_path`, `manual_game_root`, `manual_local_mods_path`,
`manual_workshop_mods_path`, `first_run_summary_shown`, `view_mode`, `order`, `categories`,
`category_order`, `category_colors`, `category_memory`, `auto_category_attempted`,
`custom_categories`, `enabled`, `nicknames`, `metadata`, `mod_paths`. The compatibility contract
and what 0.3.0 does with each is in `docs/migration.md`.

Writes (`services/fsutil.atomic_write_bytes`): temp file in the target's folder, write, fsync,
re-read from disk and verify, `Path.replace` with back-off while another program holds the target
(`SaveLockedError` when it never lets go). The UI saves `mod_state.json` 500 ms after a change, with
optimistic concurrency: if the file changed on disk since it was loaded, a `StateConflictError`
opens a Reload / Keep mine choice instead of overwriting.

## Extension points

- **Mod sources** (`services/sources.ModSource`): `source_id`, `display_name`, `claim_priority`
  (lower claims a folder first), `discover(install)`, `snapshot(location, ctx)`, `page_url(info)`.
- **Rules** (`core/validation.Rule`): `rule_id`, `description`, `validate(ctx) -> list[Finding]`.
  Built-in rules and user rule modules both go through `ModuleRule`.
- **Save formats** (`core/saves.SaveFormat`).
- **Data**: `rules.json` (`ddmanager.rules` v1) for tiers, relations and overlap patterns.

User plugins register through `register(registry)` into a staging registry that is merged only if
`register` returns cleanly (`PluginRegistry.staging` / `commit_into`). They are off by default and
loaded only for files whose SHA-256 the user approved; `--safe-mode` loads none. Failures are
`plugin.*` findings and never stop start-up. The user-facing contract is in the README.

## Source of truth

The reference for everything DD Manager reads and writes is the game itself: the
`persist.game.json` files it saves and the mod folders it loads. Three things follow from it:

- **The corpus check** (`just corpus`, marker `corpus`, never in CI) runs the codec, the state
  reader and the scan against the maintainer's real data. `tools/make_corpus.py`
  (`just corpus-refresh`) fills `<repo>/.corpus` with the app's own detection
  (`Environment.from_host`, `InstallDetector`, `resolve_app_paths`): every `persist.game.json`
  the game wrote, the game's own `backup/` copy next to each one, and the active `mod_state.json`;
  the originals are only read and `manifest.json` records every source and its SHA-256.
  `tools/corpus_env.py` supplies `DDM_SAVE_CORPUS`, `DDM_STATE_CORPUS` and `DDM_MODS_ROOT` from
  `.corpus` (and the detected Workshop folder) when they are unset. The tests
  (`tests/core/saves/test_corpus.py`, `tests/services/test_corpus_state.py`): every real save is
  detected, structurally and strictly valid, and survives parse/serialize and its own identity
  rewrite byte for byte; reorder/add/remove rewrites re-validate strictly, read back exactly and
  restore the original file when the original list is written back; the state file round-trips
  through parse/render, and a full scan of the mods folder resolves every mod the state holds a
  metadata identity for to exactly that identity.
- **Goldens are frozen outputs of this program** (`tests/golden/`): the bytes `write_applied`
  produces for the matrix in `tests/support/parity_matrix.py`, the identity and display tables of
  the synthetic mod folders in `tests/support/mod_facts.py`, and the classification of every
  sample mod. `tools/regen_goldens.py` (`just regen-goldens`) rebuilds them from the current code,
  prints what differs and refuses to overwrite a changed golden unless `--update` is passed.
- **History.** The previous version, DD Manager 0.2.1 (the Tkinter app), was deleted at the 0.3.0
  cutover; its code is still in the git history (tag `v0.2.1`) if anyone ever needs to read it.
  Nothing in the repository imports or compares against it any more: the data-format
  compatibility that matters (the 22-key state file, beside-save backups, the 0.2 loadout import)
  is specified by this program's own tests.

## Test strategy

`pytest` runs the whole suite (about 2,350 tests) in a couple of minutes. Warnings are errors
(`filterwarnings = ["error", ...]`) and `xfail` is strict.

- **Layering and purity** (`tests/test_layering.py`, `tests/test_purity.py`): the import matrix and
  the purity rules above, as AST walks.
- **Goldens** (`tests/golden/`): frozen outputs of this program, regenerated by
  `just regen-goldens` (see "Source of truth"); `tests/fixtures/mod_state_v0.json` is a real-shape
  0.2.x state file.
- **Builders and fakes**: `tests/support/dson_builder.py` builds DSON saves independently of the
  codec; `tests/conftest.py` provides `data_dir` and `sample_mods_dir` (the `modding/` samples,
  read in place); `tests/services/conftest.py` and `helpers.py` provide `mod_dir`, `fake_env`,
  `fixed_clock`, `fake_probe`, a fake `SaveFormat` and a fake Steam tree.
- **Rules, services, plugins**: `tests/rules`, `tests/services`, `tests/plugins` run against temporary
  trees with injected environment, clock and process probe; failure injection covers atomic writes,
  conflicts, corrupt state, backup retention and restore of invalid bytes.
- **UI** (`tests/ui`, `pytest-qt`, `QT_QPA_PLATFORM=offscreen` set in `tests/ui/conftest.py`): model
  tests with `QAbstractItemModelTester`, drag-and-drop contracts, the controller with fake ports and
  an immediate executor, dialogs, theme contrast, shortcut conflicts, tooltips and key-set parity in
  all four languages, and a main-window smoke test.
- **Parity checklist** (`tests/test_parity_checklist.py`): the table of P01-P30 maps each id to
  concrete test functions and fails if one is missing, renamed, or marked `skip`, `skipif`, `xfail`
  or `corpus` (so it could silently not run). The ids and their status are in `docs/migration.md`.
- **Corpus** (marker `corpus`, skipped in CI): the real-data check described under "Source of
  truth".
- **Frozen build**: `DD Manager.exe --self-test` runs in `packaging/build.ps1` and CI (`BUILD.md`).
