# DD Manager

DD Manager is a desktop mod manager for **Darkest Dungeon** (the original game, Steam app 262060).
It finds your Workshop and local mods, lets you enable and order them, checks the order for
problems, and writes the result into your save's `applied_ugcs_1_0` list (the list the game reads
to load mods) with a backup first.

Version 0.3.0 is a rewrite on PySide6 (Qt). Every feature of v0.2.1 is still there, your existing
data is read as it is, and v0.2.1 can still open the same data folder if you need to go back
([`docs/migration.md`](docs/migration.md)).

## Repository Status

This repository is not open source.

Code is published here for visibility and release distribution, but all rights
are reserved. You may not copy, modify, redistribute, or reuse this project
without prior written permission.

See [`LICENSE.md`](LICENSE.md) for the repository terms.

## Install and upgrade

The packaged app is Windows only. Download `DD Manager Portable <version>.zip` (and its `.sha256`)
from the GitHub Releases page.

- **New install:** extract the zip anywhere you can write to (not `Program Files`) and run
  `DD Manager.exe`. Nothing is installed; everything lives in that folder.
- **Upgrade from v0.2.x:** extract the zip over your existing `DD Manager Portable` folder and
  accept the overwrite. Your data stays in `DD Manager Data` next to the exe: the zip never
  contains `mod_state.json`. Old Tcl/Tk files left in `_internal/` are harmless; you may delete
  `_internal/` before extracting.
- On its first launch, 0.3.0 copies `mod_state.json` to `mod_state.pre-0.3.0.json` once and never
  overwrites that copy.

## Quick start

You need at least one save that has been opened in the game once.

1. Start `DD Manager.exe`. It detects the Steam or GOG install, the mod folders and your saves. If
   something is missing, use `File > Edit File Paths...`, `File > Auto Detect File Paths`,
   `File > Choose Mods Folder...` or `File > Choose Save File...`, then `File > Rescan` (F5).
2. The window has three panes: **Available** (every installed mod), **Load Order** (the enabled
   mods, in the order written to the save) and **Details** (preview, folder, tier, findings).
3. **Enable** a mod: double-click it or press Space or Ctrl+Right in Available, tick its checkbox,
   or drag it into Load Order. **Disable** with Space, Delete or Ctrl+Left in Load Order, or drag
   it out.
4. **Reorder** in Load Order by dragging, with Ctrl+Up / Down / Home / End, or let `Tools >
   Auto-Sort` (Ctrl+Shift+A) propose an order. Auto-Sort, importing an order and applying a
   profile always show a before/after preview you can reject.
5. **Validate** (F7) or open the Health panel (F8). The check also runs by itself a moment after
   every change. See [Health Check](#health-check).
6. Pick your save slot in the toolbar combo (for example `Slot 2 · week 14`).
7. **Backup Save** (Ctrl+B) makes a manual backup; **Patch Save** (Ctrl+Shift+P) opens a preview of
   what changes in the save, asks you to tick any risk it found, backs the save up and writes it.
   Health errors keep its button disabled until you tick *Patch despite N errors*. The game must
   be closed.
8. **Launch Game** starts Darkest Dungeon through Steam.

Order changes can be undone and redone (Ctrl+Z / Ctrl+Y). F1 shows all keyboard shortcuts.
Other tools: `Tools > Auto Categorize`, `Edit > Set Nickname...` (F2), `Edit > Assign Category`,
`Tools > Edit Categories...`, `Tools > Generate Save Code...`, `Tools > Check Setup...`, `Tools >
Copy Debug Info`, `Tools > Apply Order to Local Mod Folders...`, `Tools > Patch Other File...` and
`Tools > Patch Latest Detected Save`.

DD Manager keeps changes in `mod_state.json` about half a second after you make them. Patching
is what changes the game's save.

## The load-order model

- **Rank N is entry N-1.** The Load Order pane shows only enabled mods, numbered from 1. Rank 1 is
  written as entry `0` of `applied_ugcs_1_0` in the save, rank 2 as entry `1`, and so on. The save
  gets nothing but the enabled mods, in that order. Disabled mods keep their slot in
  `mod_state.json` but are not written.
- **First entry wins.** When two enabled mods ship the same file, the one closer to the top
  (lower rank) is the one the game uses. This is the maintainer's statement for the game, kept as
  a setting rather than a constant: `View > Priority direction` (or `Tools > Settings...`) offers
  "First entry wins" / "Last entry wins" and a "Direction verified" box. Changing the direction
  only changes the labels above and below the list, the Health Check verdicts and Auto-Sort's
  placement; the bytes written for a given order never change. While the direction is not
  verified, direction-dependent findings are capped at Info. How to confirm it with two probe
  mods: [`docs/load-order-semantics.md`](docs/load-order-semantics.md).
- **Tiers and categories.** Every mod has a category (UI, Districts, Dungeons, Quirks, Trinkets,
  Enemies, Class Patch, Class, Skins, Unassigned, or one you add). Internally the category maps to
  a tier with a weight, and Auto-Sort orders mods by tier weight. New mods are categorized once
  from their tags, folders and title (and never re-sorted); you can change any category by hand
  (`Edit > Assign Category`, or the category editor).

| Category | Tier id | Color |
| --- | --- | --- |
| UI | `ui` | `#8FA6B8` |
| Districts | `district` | `#6D9C9A` |
| Dungeons | `dungeon` | `#B88B4A` |
| Quirks | `quirk` | `#B26B7B` |
| Trinkets | `item` | `#C1A85D` |
| Enemies | `enemy` | `#B65A4D` |
| Class Patch | `class_patch` | `#879B5B` |
| Class | `class` | `#A4B56C` |
| Skins | `skin` | `#9D7A9A` |
| Unassigned | `unassigned` | `#82786B` |
| Overhaul (a category with this name) | `overhaul` | `#C8553D` |
| Patch (a category with this name) | `patch` | `#8C7BB0` |
| any other custom category | `custom:<name>` | from a color cycle, editable |

Auto-Sort works in precedence space: `overhaul` has the lowest weight, then your categories in
the order shown in the category editor, then `unassigned`, then `patch` (patches always win).
With "First entry wins" the strongest tier is placed at the top: Patch, Unassigned, then your
categories from last to first, and Overhaul at the bottom. With "Last entry wins" the same order
is mirrored. Inside a tier the current order is kept, and declared rules (see
[rules.json](#rulesjson)) are honoured. Contradictory rules produce one `core.sort_cycle` error.

Colors can be changed per category in the category editor and are stored as `#RRGGBB` in
`category_colors`. Color is never the only signal: every row also carries a three-letter tier badge.

## Health Check

The Health panel (View > Health Panel, F8) lists findings by severity: Errors, Warnings, Info.
Selecting a finding selects its mods; **Fix** applies the suggested fix as one undoable change.
Errors gate **Patch Save**: the preview lists them and its button stays disabled until you tick
*Patch despite N errors*. Warnings and Info never block. An enabled mod whose folder is missing is
never written into the save, whatever you tick. A rule that crashes shows up as
`internal.rule_failed` instead of hiding the rest of the report.

| Rule id | What it detects | Severity | Fix |
| --- | --- | --- | --- |
| `core.missing_from_disk` | A load-order entry whose mod folder is not installed (an enabled one is left out of the patched save) | Error if enabled, Info if disabled | Disable it (`Edit > Forget Missing Mods` removes entries for good) |
| `core.duplicate_identity` | Two enabled mods that would be written as the same save entry; or a local copy and a Workshop copy of the same mod | Error (same entry), Warning (local + Workshop copy) | Disable all but the highest-precedence mod; disable the local copies |
| `core.multiple_overhauls` | More than one enabled overhaul-tier mod that is not declared `compatible_with` the others | Warning | Disable all but the highest-precedence overhaul |
| `core.patch_before_target` | A patch (by tier, tag or title) that does not win over the mod it patches (declared `patch_for`, a `Load this after:` hint, a title match or shared files) | Warning (Info while the direction is unverified) | Move the patch right above its target |
| `core.file_overlap` | Enabled mods that ship the same file; one finding per winner and losers, up to 5 sample paths. Also: a mod that loses every file it ships ("has no effect") | Info when expected (the winner declares it or its tier is stronger), otherwise Warning (Info while unverified) | None; reorder or set a tier |
| `core.declared_requires` | A mod that `rules.json` says requires another one that is missing or not enabled | Error | Enable the required mods when installed |
| `core.declared_load_after` | A declared `load_after`, `patch_for` or `requires` precedence that the order violates | Warning (Info while unverified) | Make the declared winner win |
| `core.declared_incompatible` | Both sides of a declared `incompatible` pair are enabled | Error | Disable the lower-precedence mod |
| `core.folder_key_collision` | The same folder name exists in several mod roots; only the first root's copy is used | Warning | None |
| `core.sort_cycle` | Auto-Sort only: declared precedence rules contradict each other | Error | Fix the rules |

The scan itself can add findings (`scan.shadowed`, `scan.temp_folder` for a leftover `__temp__`
folder from an interrupted rename, `scan.mod_unreadable`, `detect.no_mods_root`).

## Profiles and shareable load orders

`File > Profile Manager...` (Ctrl+P) has three tabs: **Save Slots** (the game's `profile_N`
saves, with the mods each one lists), **Profiles** and **Backups**. In **Profiles** you can
save the current order under a name, apply, rename, delete, export and import profiles. Applying
or importing shows the before/after preview first and reports entries that match no installed mod.
On the **Save Slots** tab, `Import order from save` adopts the mod list a save currently
writes (with the same preview), `Use as active` selects the slot to patch.

A profile is a plain `ddmanager.loadorder` JSON file, stored as
`DD Manager Data/profiles/<name>.loadorder.json`; the same file is what you export and share. An
entry is matched to an installed mod by exact save identity, then Workshop id, then folder name
(same kind of mod), then a unique normalized title, so a shared file works on another machine.
`rank` is written for enabled entries only; `tier` is informational. Unknown keys are kept.

```json
{
  "format": "ddmanager.loadorder",
  "format_version": 1,
  "name": "Vanilla plus",
  "game": "darkest_dungeon",
  "priority_direction": "first_wins",
  "verified": true,
  "created_with": "ddmanager 0.3.0",
  "created_at": "2026-10-06T12:00:00+00:00",
  "notes": "Shared with the club.",
  "mods": [
    {
      "rank": 1,
      "enabled": true,
      "title": "Example Overhaul",
      "save_identity": { "name": "1234567890", "source": "Steam" },
      "workshop_id": "1234567890",
      "folder": "1234567890",
      "tier": "overhaul"
    },
    {
      "enabled": false,
      "title": "Old Skin Pack",
      "save_identity": { "name": "Old Skin Pack", "source": "mod_local_source" },
      "workshop_id": null,
      "folder": "old_skin_pack",
      "tier": null
    }
  ]
}
```

The legacy `dd_mod_loadout.json` can be imported through the same Import button; its order goes
through the preview and its nicknames and categories are applied after you accept.

## Backups and restore

Before every patch DD Manager copies the exact bytes it is about to replace to
`DD Manager Data/backups/<save folder name>-<8 hex digits>/persist.game.backup.<YYYYMMDD-HHMMSS>.json`
(a `-2`, `-3`... suffix when two share a second), with an `index.json` that records why and when.
Backups are kept out of the Steam Cloud folder on purpose. `File > Backup Save` makes a manual one.

- **Retention:** a managed backup is deleted only when it is outside all three protections: the
  newest 20, the newest 3, and anything younger than 30 days. The newest backup (the last one
  made) is never deleted. Adjust in `Tools > Settings... > Backups`; it applies at the next start.
- **Legacy backups** (`persist.game.backup.*.json` beside the save, made by v0.2.x) are listed and
  can be restored, and are never pruned or deleted.
- **Restore** (Profile Manager > Backups > Restore): the backup must still be a valid save, the
  current file is backed up first, and the restored file is written atomically with a fresh
  modification time. Restore refuses while the game is running.

Writes to saves, `mod_state.json` and settings are atomic (temp file, fsync, read-back, replace).
A patch is refused when the save changed since the preview, and it re-reads the written file from
disk and checks it before replacing the save.

## rules.json

Community knowledge lives in data. The shipped defaults are in `src/resources/default_rules.json`
(which file paths to ignore or merge when comparing mods). You add your own in
`DD Manager Data/rules/rules.json`; it is read at start-up. For the same mod reference, your entry
replaces the shipped one; the `overlap` lists are merged. Problems in the file become findings
(`rules.*`); a wrong entry is skipped, never half-applied.

A mod reference is `steam:<PublishedFileId>`, `local:<normalized save name>`,
`title:<normalized title>` (lower case, `&` as `and`, punctuation as spaces) or
`key:<folder name>` (your own file only). Entry fields (all optional):

| Field | Meaning |
| --- | --- |
| `tier` | Force a tier (`overhaul`, `ui`, `district`, `dungeon`, `quirk`, `item`, `enemy`, `class_patch`, `class`, `skin`, `patch`, `unassigned`, `custom:<name>`) |
| `requires` | Mods that must be enabled (the dependent must win over them) |
| `load_after` | Mods this mod must win over |
| `patch_for` | Mods this patch must win over |
| `incompatible` | References, or `{ "ref": ..., "reason": ... }`, that must not both be enabled |
| `compatible_with` | Overhauls that may coexist with this one |
| `title_hint` | A label for humans; not used for matching |

`overlap.ignore` lists patterns (case-insensitive, `*` and `?`, matched against paths relative to
the mod folder) that never count as a conflict. `overlap.merge` lists paths assumed to be merged
by the game rather than overridden; like ignored paths they are not reported as conflicts. The
shipped default for localization tables is an assumption that has not been verified in the game.

```json
{
  "format": "ddmanager.rules",
  "format_version": 1,
  "overlap": {
    "ignore": ["notes/*"],
    "merge": ["localization/*.string_table.xml"]
  },
  "mods": {
    "steam:1234567890": {
      "tier": "overhaul",
      "title_hint": "Example Overhaul",
      "compatible_with": ["steam:2222222222"]
    },
    "title:example tweaks": {
      "tier": "patch",
      "patch_for": ["steam:1234567890"],
      "requires": ["steam:1234567890"],
      "incompatible": [
        { "ref": "key:old_skin_pack", "reason": "Both replace the same hero skins." }
      ]
    }
  }
}
```

## Plugins and user rules

Plugins and rule modules are Python code that runs **with your permissions**. They are off by
default. A file runs only while its switch is on **and** its SHA-256 equals the one you approved;
editing a file revokes the approval. Approve only code you have read or trust. `--safe-mode` starts
the app without loading any user code. Failures (a syntax error, an exception, `sys.exit`, an
unsupported `API_VERSION`) are reported as findings and never stop the app.

- **User rule:** `DD Manager Data/rules/<name>.py` exporting `validate(ctx)` returning a list of
  findings. `RULE_ID` and `DESCRIPTION` are optional (the id defaults to `user.<file name>`).
  `ctx` is a `ValidationContext`: `order` (a `LoadOrder`), `mods` (`ModInfo` by folder), `tiers`,
  `rules`, `priority` and `precedence`.
- **Plugin:** `DD Manager Data/plugins/<name>.py` exporting `register(registry)`. A plugin can add
  mod sources (`registry.add_mod_source`), rules (`add_rule`) and save formats (`add_save_format`).
  Everything a plugin adds is registered all or nothing. Files starting with `_` are ignored.
  `src/plugins/nexus_example.py` is a complete example source that is shipped but not enabled.

```python
"""DD Manager Data/rules/too_many_mods.py"""

from src.core.validation import Finding, ValidationContext

RULE_ID = "user.too_many_mods"
DESCRIPTION = "More than 60 enabled mods."


def validate(ctx: ValidationContext) -> list[Finding]:
    active = ctx.order.active()
    if len(active) <= 60:
        return []
    return [Finding.warning(RULE_ID, f"{len(active)} mods are enabled; loading may be slow.")]
```

To turn it on: `Tools > Settings... > Plugins and rules`, switch on "Load approved rule modules",
select the file and press Approve (`Tools > Plugin Approval...` lists new or changed files; the
app also asks at start-up). Changes apply the next time DD Manager starts. Trust is stored in
`settings.json` as the file name and its SHA-256.

## Command line

`ddmanager` (from a source checkout: `uv run ddmanager`) has headless subcommands that use the same
services as the window. With no subcommand it starts the window and accepts the GUI options shown
below. Exit codes: 0 success, 1 a reported error, 2 usage error or an unreadable file. The packaged
`DD Manager.exe` accepts the same subcommands and, started from a terminal, prints to that
terminal.

```text
usage: ddmanager [-h] [--version] [--data-dir DATA_DIR] [--lang LANG]
                 [--log-level LOG_LEVEL] [--self-test] [--safe-mode]
                 {save,scan,diagnostics,profile} ...

DD Manager (Darkest Dungeon 1)

positional arguments:
  {save,scan,diagnostics,profile}
    save                inspect or verify a binary save (persist.game.json)
    scan                list the installed mods
    diagnostics         print the setup report (Check Setup)
    profile             named load-order profiles

options:
  -h, --help            show this help message and exit
  --version             show program's version number and exit
  --data-dir DATA_DIR   override the DD Manager Data directory

GUI options (used when no command is given):
  --lang LANG           UI language code (en, es_ES, pt_PT, zh_CN)
  --log-level LOG_LEVEL
                        DEBUG, INFO, WARNING or ERROR
  --self-test           check the installation, exit
  --safe-mode           do not load user plugins/rules
```

| Subcommand | Does |
| --- | --- |
| `scan [--json]` | Lists the installed mods and whether each is enabled |
| `save inspect <file>` | Prints the save format, header numbers, the applied mods and validation problems |
| `save verify <file>` | Exit code 0 when the save is valid, 1 otherwise |
| `save plan <file> [--emit out.bin]` | Shows what patching would change; `--emit` writes the patched bytes elsewhere and never touches the save |
| `save patch <file> [--ack ...]` | Backs up and patches; `--ack` accepts a reported risk (`steam_cloud`, `duplicate_identity`, `non_default_filename`, `game_state_unknown`) |
| `save backup <file>` / `save restore <file> [--from backup]` | Manual backup; validated restore (latest backup by default) |
| `profile list`, `save <name>`, `export <name> <file>`, `import <file>`, `apply <name> [--dry-run]` | Profiles; `apply` adopts a profile in `mod_state.json` and never touches a save |
| `diagnostics` | Prints the "Check Setup" report |

`--data-dir` is a global option and goes before the subcommand:
`ddmanager --data-dir "D:\DD Manager Data" scan`.

## Languages

English, Simplified Chinese (`zh_CN`), Portuguese (`pt_PT`) and Spanish (`es_ES`). Switch live with
`View > Language`; the choice is saved in `mod_state.json`. On the very first start the OS language
is used when it is one of these. `--lang <code>` overrides it for one run. Every button and menu
entry has a tooltip in all four languages. The "Check Setup" report is English on purpose so bug
reports read the same everywhere.

## Troubleshooting

- **Logs:** `DD Manager Data/logs/ddmanager.log` (1 MB, 3 rotated files) and `faulthandler.log`.
  Start with `--log-level DEBUG` for more detail. After an unexpected error a dialog offers Copy,
  Open log folder, Continue and Quit.
- **Where is my data?** In order: `--data-dir <folder>`, the `DDMANAGER_DATA_DIR` environment
  variable, `DD Manager Data` next to `DD Manager.exe` (the repository root when run from source),
  and only if that location is not writable and has no data folder yet, `%LOCALAPPDATA%\DD Manager`.
  An existing but unwritable `DD Manager Data` is an error; it is never replaced by another folder.
  `Tools > Check Setup...` shows the folder in use and the detected paths.
- **Report a problem:** `Tools > Copy Debug Info` copies the version, paths, counts and the
  selected save; paste it into the report.
- **Nothing detected:** use `File > Edit File Paths...`: five fields (game folder, active mods,
  local mods, Workshop mods, profile save), each with Browse, Auto and Clear. Steam installs are the
  main target; GOG and others may need manual paths.
- **"mod_state.json changed" banner:** another program (or v0.2.1) wrote the file. Reload takes the
  disk version; Keep mine overwrites it. If the file cannot be read, the last good copy
  `mod_state.backup.json` is loaded, and the unreadable file is kept as
  `mod_state.corrupt.<time>.json` before it is replaced.
- **Plugins misbehave:** start with `--safe-mode`, or switch them off in Settings.
- **A mod shows stale details:** the scan keeps what it read about each mod folder in
  `DD Manager Data/cache/mod_info.v1.json` and re-reads a folder only when its `project.xml`,
  localization files, Workshop update time or top-level folders changed (a file added deeper than
  one level inside an existing folder is not noticed). Delete the file to force a full re-read.
- **Going back to v0.2.1:** extract the v0.2.1 release over `DD Manager Portable` (or run its exe
  from another folder with the same `DD Manager Data`). It reads the same `mod_state.json`. The
  full procedure and what v0.2.1 will do differently is in [`docs/migration.md`](docs/migration.md).

## Developing

Needs [uv](https://docs.astral.sh/uv/); it installs Python 3.14 and all dependencies.

```text
uv sync --group dev --group build   # once: Python 3.14 (uv provisions it), app, dev and build tools
uv run just install     # the same, as a recipe (uv python install 3.14 + uv sync)
uv run just check       # ruff, ruff format --check, ty, then the whole test suite
uv run just run         # start the app from source on <repo>/DD Manager Data
uv run just test-core   # domain tests without Qt (core, rules, services, plugins, layering, purity)
uv run just build       # Windows only: frozen app + portable zip (see BUILD.md)
```

(Activate `.venv` to type plain `just`.) `just --list` shows every recipe: `lint`, `fmt`,
`typecheck`, `test`, `cli`, `regen-goldens`, `corpus`, `probe-kit <dest>`, `build-check`, `clean`.

The package folder is literally `src/` (`from src.core.load_order import LoadOrder`). Layers:
`src/core` (pure domain, stdlib only), `src/rules` (health rules), `src/services` (all I/O),
`src/plugins` (mod sources), `src/ui` (PySide6), composed in `src/app.py`; `tests/` enforces the
import rules. Further reading:

- [`docs/architecture.md`](docs/architecture.md): layers, data flow, save format, state, tests
- [`docs/migration.md`](docs/migration.md): data compatibility, parity checklist, divergences, rollback
- [`docs/load-order-semantics.md`](docs/load-order-semantics.md): which end of the list wins
- [`BUILD.md`](BUILD.md): building the release
- [`CHANGELOG.md`](CHANGELOG.md): release notes
- [`research/README.md`](research/README.md): historical DSON research scripts
