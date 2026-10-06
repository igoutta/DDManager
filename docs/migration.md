# Migration from v0.2.1 (and how to go back)

DD Manager 0.3.0 replaces the Tkinter app (`dd2.py` and its modules) with the layered PySide6
application in `src/`. This document is the contract that keeps your data safe across that
change, the checklist that proves nothing was lost, the places where behavior intentionally
differs, and the rollback procedure. "v0.2.1" is git tag `v0.2.1` (commit `31e85d6`), the last
release of the Tkinter app.

## Data compatibility and rollback contract

Each point is enforced by code and by the tests named after it.

1. **The data folder is pinned.** `DD Manager Data` next to `DD Manager.exe` when frozen, at the
   repository root when run from source (`services/app_paths.py`). The working directory and
   `sys.argv` are never consulted. `--data-dir` and `DDMANAGER_DATA_DIR` override it. An existing
   but unwritable portable folder raises `DataDirNotWritableError`; state is never silently forked
   into a per-user folder. (`tests/services/test_app_paths.py`)
2. **`mod_state.json` keeps the v0.2.1 schema**: the same 22 keys with the same meaning and the same
   canonical values (folder basenames as keys, English category names, `view_mode` keys, language
   codes, `#RRGGBB` colors). The only addition is `schema_version: 1`. `enabled` is written as an
   explicit bool for every `order` entry and read the way v0.2.1 reads it (a missing flag means
   enabled). Unknown keys pass through untouched and keep their position. The file is written with
   `json.dumps(indent=2)`, byte-for-byte the style of v0.2.1. (`tests/core/test_legacy_state.py`,
   `tests/services/test_state_repo.py`)
3. **First launch** of 0.3.0 copies `mod_state.json` to `mod_state.pre-0.3.0.json`, once, never
   overwriting it. Every write is atomic (temp file, fsync, read-back, replace). The previous good
   file is rotated to `mod_state.backup.json` only when the main file still parses; an unreadable
   main is preserved as `mod_state.corrupt.<timestamp>.json` before anything replaces it.
   (`tests/services/test_state_repo.py`)
4. **Nothing is pruned.** A mod whose folder is gone stays in the load order as a missing row
   (Error finding when it is enabled, Info when disabled) until you choose `Edit > Forget Missing
   Mods`, and an enabled one is excluded from patching. A briefly unmounted drive no longer wipes
   categories and nicknames.
   (`tests/ui/test_forget_missing.py`, `tests/ui/test_patch_gate.py`,
   `tests/rules/test_missing_from_disk.py`)
5. **Discovery** reads `mods_path` plus its companion roots (the port of `paths.py`), with two
   consistency fixes (both `DarkestDungeon` and `Darkest Dungeon` folder names; GOG `<root>/mods`).
   The first root wins a duplicated folder name and the shadowed copies are reported; existing keys
   never change, a new root only adds mods. (`tests/services/test_detection.py`,
   `tests/services/test_scan.py`)
6. **Identity parity.** What the game sees does not change: a Workshop mod is written as
   `(PublishedFileId, "Steam")` and a local mod as `(Title or folder name without numeric prefix,
   "mod_local_source")`, computed by a verbatim port of v0.2.1's `read_mod_metadata` and
   `save_identity_for_mod`. (`tests/core/test_identity.py`, `tests/golden/identity/`)
7. **Bytes parity.** For the same list of enabled mods, `write_applied` produces exactly the bytes
   v0.2.1's `dson_patch_mod_list_resize` produced. The priority direction changes labels and rule
   verdicts only, never bytes. (`tests/core/saves/test_dson_parity.py`,
   `tests/core/saves/test_goldens.py`)
8. **Backups** are written to `DD Manager Data/backups/<save folder>-<8 hex>/
   persist.game.backup.<YYYYMMDD-HHMMSS>[-N].json`, outside the folder Steam Cloud syncs. After a
   backup or patch `last_backup_path` and `last_save_path` are still written as absolute paths, so
   v0.2.1's `Restore Last Backup` works on a rollback. Retention (newest 20, newest 3, younger than
   30 days) never deletes the newest backup and never touches the legacy `persist.game.backup.*`
   files beside a save, which stay listed and restorable. Restore validates the backup, makes a
   pre-restore backup and writes atomically with a fresh modification time.
   (`tests/services/test_backup.py`)
9. **The frozen layout is unchanged**: `DD Manager Portable/{DD Manager.exe, _internal/, README.md,
   DD Manager Data/{README.txt, icon_cache/.keep}}`. The zip never contains `mod_state.json`
   (the build fails if it would). Extract over the old folder; stale Tcl/Tk files in `_internal/`
   are harmless and you may delete `_internal/` first. (`BUILD.md`)
10. **The legacy oracle is read from git, never from the working tree.** `tools/legacy_oracle.py`
    extracts `dd2.py`, `state.py`, `categories.py`, `localization.py`, `paths.py` and
    `legacy_loadout.py` from commit `31e85d6` into a temporary folder, so the files could be deleted
    from the repository while the differential tests keep working.

A missing mod that is **enabled** is an Error finding with a one-click Disable, and it is
**excluded** from patching: the entries written to the save skip it, and the identity v0.2.1 cached
for it in `metadata` is never used. The patch preview says how many enabled mods are left out for
that reason and, like every Error of the Health Check, keeps the Patch button disabled until *Patch
despite N errors* is ticked. The CLI (`save plan`, `save patch`) leaves them out the same way and
prints a note.

## What 0.3.0 reads and writes in mod_state.json

| Key | 0.3.0 |
| --- | --- |
| `language` | read at start (also by the early language probe); written when you switch language |
| `mods_path` | read; written on first run, `Choose Mods Folder`, `Auto Detect`, `Edit File Paths` |
| `last_save_path`, `last_output_path` | read; written after a patch, a backup, or when you pick a save |
| `last_backup_path` | written after every backup or patch (absolute path of the newest backup) |
| `selected_profile_path` | the selected save slot; read and written |
| `manual_game_root`, `manual_local_mods_path`, `manual_workshop_mods_path` | read; written by `Edit File Paths` |
| `first_run_summary_shown` | read; set after the first-run notice |
| `view_mode` | the density (`No Icons`, `Compact`, `Comfortable`, `Visual`); read and written with the same keys |
| `order` | every known mod, enabled or not, missing ones included; written whenever the order changes |
| `enabled` | folder to bool; an explicit bool for every `order` entry on write; keys of folders no longer in `order` are dropped on write |
| `categories`, `nicknames`, `category_order`, `custom_categories`, `category_colors`, `category_memory`, `auto_category_attempted` | read and written with v0.2.1's meaning (colors as `#RRGGBB`) |
| `metadata`, `mod_paths` | v0.2.1's caches, **never rewritten** by 0.3.0 (`metadata` is read only to recognise, in the active-save guard, a missing mod the save still lists; it is never written into a save); v0.2.1 rebuilds both on its first scan |
| `schema_version` | new, `1`, additive; v0.2.1 passes unknown keys through |

The settings v0.2.1 never had live elsewhere: `settings.json` (priority direction, retention,
plugin trust), `ui.ini`, `profiles/`, `backups/`, `rules/`, `plugins/`, `logs/`, `cache/`,
`ddmanager.lock`. v0.2.1 ignores all of them.

### Why the v0.2.1 exe still works on the same folder

- It finds the same file name in the same place and understands every key. The pinned v0.2.1 loader
  (`state.load_state_file` and `migrate_state_data`) is run against files 0.3.0 renders, on seeded
  random orders, and must load them without notices and with the identical active list; a rendered
  file is already in migrated form. (`tests/core/test_legacy_state.py`,
  `tests/services/test_state_repo.py::test_the_rendered_file_is_accepted_by_the_pinned_legacy_loader`)
- `order` keeps disabled mods in their slots and `enabled` carries explicit bools, so v0.2.1's own
  filter (`order` entries whose `enabled` is not false) yields exactly the list 0.3.0 would write.
- `schema_version` is just an extra key; the 22 keys are all still present.
- `last_backup_path` and `last_save_path` are absolute, so its `Restore Last Backup` finds backups
  in `backups/`.
- `mod_state.pre-0.3.0.json` is the belt-and-braces copy of what the file was before 0.3.0 ever ran.
- The patched save is byte-identical to what v0.2.1 would have written.

## Parity checklist

Every feature of v0.2.1 is ported. `tests/test_parity_checklist.py` maps each id to concrete test
functions and fails when a test is missing, renamed or marked so it could silently not run. Status of
every row: **done**. Test files are relative to `tests/`.

| Id | v0.2.1 behavior | In 0.3.0 | Status | Tests |
| --- | --- | --- | --- | --- |
| P01 | Two lists (Reserve / Load Order) and Enable/Disable buttons | Three panes Available, Load Order, Details and a button column | done | `ui/test_parity_gaps.py`, `ui/test_main_window_smoke.py` |
| P02 | Drag within a list and across lists at a position; 6 px threshold; "N mods" badge; gold insertion line | Qt drag and drop, drop indicator drawn as one line, drag badge, autoscroll | done | `ui/test_load_order_model.py`, `ui/test_available_proxy.py`, `ui/test_parity_gaps.py` |
| P03 | Multi-select: Shift range, Ctrl toggle | Extended selection in both lists | done | `ui/test_parity_gaps.py` |
| P04 | Left-edge 28 px click toggles enabled | Explicit checkbox column, double-click, Space, Delete | done | `ui/test_available_proxy.py`, `ui/test_parity_gaps.py` |
| P05 | Space enables (Reserve) / disables (Load Order) | Same, plus Delete and Ctrl+Left/Right | done | `ui/test_shortcuts.py`, `ui/test_parity_gaps.py` |
| P06 | Warn before disabling a mod the selected save lists | One guard for every disable path (button, key, drag, menu, undo, profile) | done | `ui/test_controller.py` |
| P07 | Right-click: assign category, Open Workshop Page | Context menu: categories, nickname, open folder, Workshop page | done | `ui/test_categories_dialog.py`, `ui/test_nickname.py`, `plugins/test_sources.py`, `services/test_platform_actions.py` |
| P08 | Row text: NEW, `+`, `[Category]`, name, `(version/MM/YY)`, `[BR]`, nickname, `[id]`; category color | Row delegate: tier stripe and badge, nickname-aware title, suffix line, NEW pill for 15 s, no re-sort | done | `ui/test_parity_gaps.py`, `ui/test_load_order_model.py`, `core/test_identity.py` |
| P09 | Category filter; search over name, save name, folder, title, id | Tier chips, source filter, debounced search over a precomputed blob | done | `ui/test_available_proxy.py`, `ui/test_main_window_smoke.py` |
| P10 | View modes No Icons / Compact / Comfortable / Visual, saved in `view_mode` | Density setting, same four keys and sizes | done | `ui/test_density.py`, `ui/test_theme.py` |
| P11 | Preview icons with an on-disk PNG cache | Row thumbnails decoded by Qt in a worker, cached in memory | done | `ui/test_thumbnails.py` |
| P12 | Edit Categories: reorder, add, rename custom, color, remove, atomic Save/Cancel | Category editor over the verbatim category operations | done | `ui/test_categories_dialog.py`, `core/test_categories.py` |
| P13 | File Paths editor: five overrides with Browse / Auto / Clear | Paths dialog, same five state keys | done | `ui/test_paths_dialog.py` |
| P14 | Auto Detect with summary; Refresh Mods; first-run flow | Same flow; scan in a worker; one-time summary | done | `ui/test_paths_dialog.py` |
| P15 | Profile dropdown; Load Profile Mods; Patch Selected Profile | Toolbar slot combo, Profile Manager (slots, profiles, backups), import with preview, Patch Save on the selected slot | done | `ui/test_dialogs.py`, `services/test_save_slots.py`, `services/test_profiles.py`, `ui/test_controller.py` |
| P16 | Patch Chosen Save; Patch Auto-Detected | `Patch Other File...`, `Patch Latest Detected Save`; a non-default file name needs an acknowledgement | done | `services/test_save_patch.py`, `ui/test_patch_targets.py`, `ui/test_dialogs.py`, `ui/test_controller.py` |
| P17 | Generate Save Code with Copy | Save code dialog (names now JSON-escaped) | done | `ui/test_save_code_dialog.py`, `core/saves/test_applied_text.py` |
| P18 | Apply Order to Local Mods (`NNNN_` renames, two-phase, rollback, re-key) | Preview, monotonic prefixes, two-phase rename with rollback, every state map re-keyed including nicknames | done | `ui/test_apply_order_flow.py`, `core/test_folder_order.py`, `services/test_folder_renamer.py` |
| P19 | Restore Last Backup | Backups tab: managed and legacy backups, validated restore with a pre-restore backup | done | `ui/test_backups_tab.py`, `services/test_backup.py` |
| P20 | Check Setup; Copy Debug Info | Copyable report from `core/diagnostics` (English on purpose) | done | `ui/test_diagnostics_dialog.py`, `core/test_diagnostics.py` |
| P21 | Launch Game; Open Local Mods folder | Menu and toolbar via `platform_actions` | done | `ui/test_platform_actions.py`, `services/test_platform_actions.py` |
| P22 | Auto Sort; Auto Categorize; silent categorize on load | Auto-Sort with preview; Auto Categorize with summary; silent classify assigns categories only | done | `ui/test_auto_categorize.py`, `ui/test_controller.py`, `core/test_sorting.py` |
| P23 | Nickname dialog; equal to default clears | Nickname dialog, same clearing rule | done | `ui/test_nickname.py` |
| P24 | Languages en, zh_CN, pt_PT, es_ES, live switch | Key-based translator over four JSON catalogs, live retranslation, key-set parity enforced | done | `ui/test_i18n_parity.py`, `ui/test_retranslate.py`, `ui/test_translator.py` |
| P25 | Startup splash; duplicate warning after splash; crash log at startup | No splash; duplicate warning after the first scan; exception hooks and crash dialog for the whole session | done | `ui/test_duplicate_warning.py`, `ui/test_exception_hooks.py` |
| P26 | Status line (enabled / disabled / uncategorized) | Status bar: slot, save, last backup, finding counts, summary, transient messages | done | `ui/test_status_bar.py` |
| P27 | Scroll position and selection kept across refresh | Persistent indexes and selection by id | done | `ui/test_load_order_model.py`, `ui/test_parity_gaps.py` |
| P28 | Dark Darkest Dungeon theme, serif headings, crimson and gold | The palette ported value for value, Fusion style, palette and stylesheet from tokens | done | `ui/test_theme.py` |
| P29 | Legacy `dd_mod_loadout.json` (dormant) | Import only, through the Profile Manager | done | `ui/test_legacy_loadout_import.py`, `services/test_profiles.py` |
| P30 | Portable data folder; `mod_state.json` with backup rotation; save on every change | Same names, atomic writes, 500 ms debounce, conflict detection, never prune | done | `services/test_app_paths.py`, `services/test_state_repo.py`, `ui/test_controller.py`, `ui/test_forget_missing.py` |
| - | `Start New Campaign` (hidden, never shippable) | Dropped | dropped | none |

## Intentional divergences

Where 0.3.0 deliberately behaves differently, and why. None of them changes the bytes written to a
save for a given list of enabled mods.

| Change | Reason |
| --- | --- |
| Enabling a mod appends it after the last enabled mod (or lands at the drop position). v0.2.1 put it back in its remembered slot. | The rank you see is the rank written. A slot nobody can see made results unpredictable. |
| Disabling keeps the slot in `order` (v0.2.1 re-slotted the mod at the end of the disabled list). | Re-enabling and undo are exact, and the active list v0.2.1 derives is unchanged. |
| Auto-Sort keeps the current order inside a tier (v0.2.1 re-sorted alphabetically), orders tiers in precedence space (the winning end is at the top, so with "First entry wins" Patch is first and Overhaul last), honours declared rules, and ranks `Unassigned` next to `Patch` (v0.2.1 forced it last). | An alphabetical reshuffle destroyed deliberate orders; the order of tiers must follow the setting that says which end wins; declared rules need a topological sort. The result is shown in a preview before it is applied. |
| No sort at start-up. Scanning assigns categories to new mods only, never moves them. v0.2.1 silently re-sorted the whole list. | A silent re-sort is data loss for a hand-made order. |
| New mods are appended disabled and show a NEW pill for 15 s; they are not sorted to the top. | In v0.2.1 a drag inside that window promoted the new mods by accident. |
| No hidden 28 px click zone; an explicit checkbox column instead. | A control nobody could see or discover. |
| Backups live in `DD Manager Data/backups/`, not beside the save. | The save folder is synced by Steam Cloud, and backups were never pruned. Old beside-save backups are still listed and restorable. |
| A drag downward lands at the drop indicator (v0.2.1 overshot). | A block dragged down ended up below the line it was dropped on. |
| Restore validates the backup, takes a pre-restore backup, and writes atomically with a fresh mtime. | v0.2.1 copied blindly with `shutil.copy2`, which kept the old mtime and could restore garbage. |
| Patching and restoring refuse while the game is running (patching also asks for an acknowledgement when that cannot be determined; no setting turns the guard off); a patch is refused when the save changed since its preview. | v0.2.1 had no such guard, and the game rewrites its save on exit. |
| Health Check errors keep the Patch button of the preview disabled until *Patch despite N errors* is ticked. | v0.2.1 patched whatever the list held. |
| Folder renaming (`Apply Order to Local Mod Folders`) uses monotonic four-digit prefixes and re-keys every state map including nicknames. | v0.2.1 produced non-monotonic prefixes and dropped nicknames. |
| Importing a profile matches by save identity `(name, source)`, then Workshop id, folder and unique title. | Name-only matching confused a local and a Workshop mod with the same title. |
| Mods that vanish from disk are never pruned; there is a `Forget Missing Mods` action. | A briefly unmounted drive used to wipe categories, nicknames and order. |
| Thumbnails are decoded by Qt (JPEG works) and kept in memory; `icon_cache/` is kept but no longer written. | Qt decodes and scales images itself, so the on-disk PNG cache is unnecessary. |
| No splash window; a background scan with a busy indicator; crash dialog for the whole session. | A frozen windowed app had no error surface after start-up. |
| `Generate Save Code` JSON-escapes names. | Names with quotes or backslashes produced invalid text. |
| The save slot's week ignores `persist.game.backup.*` and temp files. | A backup could feed a stale week. |
| `metadata` and `mod_paths` in `mod_state.json` are no longer rewritten; 0.3.0 keeps its own cache in `cache/mod_info.v1.json`, whose signature adds the newest top-level folder mtime to the four legacy fields and looks the Workshop update time up by the resolved Workshop id. | The new app reads folders itself; the old caches are v0.2.1's, and it rebuilds them. |
| `enabled` is explicit for every entry; `schema_version: 1` is added; writes are atomic. | v0.2.1 defaulted differently when discovering (disabled) and reading (enabled), and could cut a write in half. |
| The default priority direction is "First entry wins" (`PrioritySetting(FIRST_WINS, verified=True)`), kept as a setting with a probe protocol. | It is the maintainer's statement (2026-09-29); `docs/load-order-semantics.md` explains how to verify it. |
| `Start New Campaign` is dropped. | It was hidden and unshippable in v0.2.1. |

## Rollback procedure

Use this if 0.3.0 misbehaves and you want v0.2.1 back. Your mods, saves and data stay intact.

1. Close DD Manager 0.3.0 (and Darkest Dungeon).
2. Optional safety copy: copy the whole `DD Manager Data` folder somewhere else.
3. Download the v0.2.1 `DD Manager Portable` zip from the GitHub Releases page (tag `v0.2.1`).
4. Extract it **over** your `DD Manager Portable` folder, or into a new folder; in the second case
   move `DD Manager Data` next to the new `DD Manager.exe`, because v0.2.1 looks for it there.
   Deleting `_internal/` first gives a clean install; leftover 0.3.0 files are otherwise harmless.
5. Start v0.2.1. It reads the same `mod_state.json`: order, enabled mods, categories, nicknames,
   language and paths are all there. `Refresh Mods` rebuilds its caches.
6. If v0.2.1 rejects or misreads the state file (it should not), copy
   `mod_state.pre-0.3.0.json` over `mod_state.json`. That is your state as it was before 0.3.0
   first ran; changes made in 0.3.0 since then are lost.
7. If a save patched by 0.3.0 is wrong, close the game and restore the backup:
   v0.2.1's `Restore Last Backup` works because `last_backup_path` is an absolute path into
   `DD Manager Data/backups/`; or copy the right `persist.game.backup.*.json` from there over
   `persist.game.json`.

To come back to 0.3.0, extract its zip over the folder again. Nothing from 0.3.0 was deleted
(`profiles/`, `settings.json`, `backups/`, `rules/`, `plugins/` are simply not used by v0.2.1), and
`mod_state.pre-0.3.0.json` is not recreated because it already exists.

What v0.2.1 will still do in its own way, as it always did: on each scan it removes categories,
nicknames, enabled flags and metadata of mods whose folder is not on disk (so keep your mod drives
mounted while it runs), and its start-up auto-categorize may silently re-sort the list when it assigns a category
to a mod that is new to it or still `Unassigned` and was never attempted (0.3.0 records every mod it
classified in `auto_category_attempted`, which v0.2.1 respects).
