# Changelog

All notable changes to this project should be listed here.

## v0.3.0 - 2026-10-06

DD Manager is rewritten on PySide6 (Qt) in a layered `src/` package. Everything v0.2.1 could do is still there, the data folder and `mod_state.json` stay compatible, and the release is still `DD Manager.exe` in the same portable layout. Details: `docs/architecture.md` and `docs/migration.md`.

### Added
- A new PySide6 window: Available, Load Order and Details panes with drag and drop, multi-select, undo and redo, keyboard shortcuts (F1 lists them), a toolbar and menus, and the same dark Darkest Dungeon theme and category colors. Every action has a tooltip in all four languages.
- An explicit load-order model: rank N is written as `applied_ugcs_1_0` entry N-1, and the first entry wins conflicts. The winning end is a setting (`View > Priority direction`) with a "verified" flag; it changes labels, Health Check verdicts and Auto-Sort placement, never the bytes written for an order.
- A Health Check with ten finding ids (`core.missing_from_disk`, `core.duplicate_identity`, `core.multiple_overhauls`, `core.patch_before_target`, `core.file_overlap`, `core.declared_requires`, `core.declared_load_after`, `core.declared_incompatible`, `core.folder_key_collision`, `core.sort_cycle`), one-click fixes, a status-bar summary, and a rules file: shipped defaults plus your own `DD Manager Data/rules/rules.json`.
- Tiers derived from categories, and an Auto-Sort that previews its result before it changes anything.
- Profiles as plain, shareable `ddmanager.loadorder` JSON files (`*.loadorder.json`), a Profile Manager (Save Slots, Profiles, Backups), import of the order a save currently lists, and import of the legacy `dd_mod_loadout.json`.
- Managed backups with retention (newest 20, newest 3, 30 days; configurable), a manual `Backup Save`, and a validated `Restore`.
- A Patch Save preview (before and after, added, removed, moved, backup folder) with explicit acknowledgements for risks: Steam Cloud folder, duplicate save identity, a file not named `persist.game.json`, game state unknown. Health Check errors keep the Patch button disabled until *Patch despite N errors* is ticked. Patching refuses while the game is running (no setting turns that off) or when the save changed since the preview.
- `Forget Missing Mods`: mods whose folder is gone stay in the load order as missing rows until you remove them. An enabled missing mod is an error and is left out of the patched save; it is never written from the old `metadata` cache.
- A mod info cache (`DD Manager Data/cache/mod_info.v1.json`): a rescan re-reads only the folders whose `project.xml`, localization files, Workshop update time or top-level folders changed (347 Workshop mods: about 3.4 s down to 0.3 s on the maintainer's machine).
- Opt-in plugins (`DD Manager Data/plugins/*.py`) and user rule modules (`DD Manager Data/rules/*.py`), each approved by SHA-256, plus `Settings` and `Plugin Approval` dialogs and `--safe-mode`.
- A headless `ddmanager` command: `scan`, `save inspect|verify|plan|patch|backup|restore`, `profile list|save|export|import|apply`, `diagnostics`.
- `--data-dir`, the `DDMANAGER_DATA_DIR` variable, `--lang`, `--log-level` and `--self-test` options.
- A rotating log (`DD Manager Data/logs/ddmanager.log`), `faulthandler.log`, a crash dialog for the whole session, and a single-instance lock.
- A `mod_state.pre-0.3.0.json` copy of your state, made once on the first 0.3.0 launch.
- `docs/architecture.md`, `docs/migration.md` (compatibility contract, parity checklist, divergences, rollback) and `docs/load-order-semantics.md`, with a probe kit (`just probe-kit`) to confirm which end wins.
- Development on uv with Python 3.14, ruff, ty, pytest and pytest-qt, a `justfile`, CI, and differential tests against the v0.2.1 code read from git.

### Changed
These are intentional differences from v0.2.1, each explained in `docs/migration.md`:
- Enabling a mod appends it after the last enabled mod; v0.2.1 put it back in its remembered slot. Disabling a mod keeps its slot in `mod_state.json`.
- Auto-Sort keeps the current order inside a tier instead of re-sorting alphabetically, and it works in precedence space: with "First entry wins" the strongest tier (Patch, then Unassigned) is at the top. `Unassigned` now sits next to `Patch` instead of being forced last.
- Nothing re-sorts your load order at start-up. Scanning assigns categories to new mods only; it never moves them.
- New mods are appended disabled and show a NEW pill for 15 seconds; v0.2.1 also sorted them to the top of the lists, so dragging during that window promoted them by accident.
- Enabling and disabling use an explicit checkbox column (plus double-click, Space and Delete); the hidden 28 px click zone at the left edge is gone.
- Backups go to `DD Manager Data/backups/` instead of next to the save, so Steam Cloud no longer syncs them. Backups made by v0.2.x beside the save are still listed and restorable. `last_backup_path` is still written, so v0.2.1's `Restore Last Backup` keeps working.
- Dragging a mod down lands it at the drop indicator; v0.2.1 overshot.
- Restore validates the backup, backs up the current save first, and writes atomically with a fresh modification time.
- `Apply Order to Local Mod Folders` uses monotonic four-digit prefixes (`0001_`, `0002_`, ...), renames in two phases with rollback, and keeps nicknames. v0.2.1 lost them.
- Importing a profile or load order matches mods by save identity `(name, source)`, then Workshop id, folder and unique title, not by name alone.
- Mods that are no longer on disk are never pruned from your state (a briefly unmounted drive used to wipe categories and nicknames).
- `mod_state.json` keeps all 22 legacy keys and gains `schema_version: 1`; `enabled` is written as an explicit true or false for every entry; `metadata` and `mod_paths` are left as they were (the new app reads mod folders itself; v0.2.1 rebuilds both). Writes are atomic and a corrupt file is preserved before it is replaced.
- Detection looks for both `DarkestDungeon` and `Darkest Dungeon` folders and for a GOG `<root>/mods` folder; the first root wins a duplicate folder name and the others are reported as findings.
- Row thumbnails are decoded by Qt (JPEG preview images now work) and cached in memory; `icon_cache/` is kept but no longer written.
- There is no splash window. The scan runs in the background with a busy indicator, and the duplicate local and Workshop warning appears after the first scan.
- `Generate Save Code` now JSON-escapes names.
- The save slot's week ignores the backup files DD Manager itself writes beside a save.
- The app now runs on Python 3.14 and PySide6; the zip keeps its name and layout (`DD Manager Portable <version>.zip`).

### Fixed
- The save codec no longer asks the UI who a mod is in the middle of patching, and the four copy-pasted serializers are one. Names in saves are read as UTF-8, so Chinese, Japanese and other non-ASCII names are no longer silently dropped.
- The validator now also checks the header magic, strictly increasing offsets and exact child counts (reported by `ddmanager save inspect`); a patched save is never allowed to be worse than the file it came from, and the written entries must read back identically.
- `mod_state.json` writes can no longer be cut in half or rotate a corrupt file over the good backup.
- Newly discovered mods are always added disabled and every reader treats a missing flag the same way; v0.2.1 defaulted to disabled on discovery but enabled everywhere it read.
- Errors after start-up are logged and shown instead of vanishing in the windowed build.

### Removed
- The Tkinter application and its modules: `dd2.py`, `categories.py`, `localization.py`, `paths.py`, `state.py`, `legacy_loadout.py`, plus `pyi_rth_tk_paths.py`, `build.ps1` and `startup_title.png`. The behavior they implemented lives in `src/` and `packaging/`; v0.2.1 stays available as a release and as the git tag `v0.2.1`.
- The hidden `Start New Campaign` prototype and the startup splash.
- The DSON research scripts (`dson_*.py`, `DD Parse.py`, `DD extractor.py`, `replacement_list.json`) moved to `research/`; they are historical, hardcode paths and are not maintained.

### Rolling back
If 0.3.0 does not work for you, extract the v0.2.1 release over `DD Manager Portable` (or run it from another folder next to the same `DD Manager Data`). It reads the same `mod_state.json`, and your original file is also kept as `mod_state.pre-0.3.0.json`. v0.2.1 prunes entries for mods that are not on disk and rebuilds its own metadata, as it always did. See `docs/migration.md#rollback-procedure`.

## v0.2.1 - 2026-06-01

### Added
- Added an `Open Workshop Page` action to the mod right-click menu for those times when a mod's icon and title are both being completely unhelpful.
- Added a `Copy Debug Info` tool so bug reports can include the app version, detected paths, selected profile, and save-patching basics without a whole screenshot scavenger hunt.
- Added a reviewer-oriented `BUILD.md` with source layout and reproducible Windows build steps for the packaged app.

### Changed
- Added drag-and-drop category reordering inside the `Edit Categories` dialog, while keeping the old move buttons around as backup.
- Trimmed the profile dropdown so it stops hogging half the row just to show one profile.
- Cleaned up the top file-controls row by removing the always-visible active mods path, renaming `Auto Detect` to `Auto Detect File Paths`, and moving `Refresh Mods` plus `Tools` up beside the other path controls.
- Split the top toolbar into left and right action groups so it feels less like every button got dumped into the same corner.
- Took a serious run at `Start New Campaign`, then hid it from the live UI again because it is still not actually shippable.
- Archived the current findings on campaign creation. At the moment it looks less like a normal app feature and more like picking a fight with Darkest Dungeon's save encoding.
- Added a divider between the category/tag actions and the new Workshop-page action in the mod right-click menu so the menu is easier to scan at a glance.
- Tidied the `Tools` menu into clearer groups and gave the profile action row a little breathing room so the buttons stop feeling glued together.
- Linked the main README to the new build instructions so reviewers can find the packaging steps without digging through the repo.

### Fixed
- Gave the `Edit Categories` dialog more vertical space so the `Remove` button stops collapsing into a sad little sliver.
- Fixed the startup splash/loading cycle so the rotating loading messages actually follow the selected app language instead of snapping back to English.
- Reduced view-switch freezing by stopping `Compact` and other icon views from trying to queue preview work for the entire mod list all at once, and by skipping a redundant full list rebuild when only the view mode changes.
- `Open Workshop Page` now disables itself when the selection is not a single Workshop-backed mod instead of pretending it can do something useful.
- Disabled UPX in the release packaging path to reduce antivirus false positives on the distributed Windows build.

## v0.2.0 - 2026-05-25

- Fixed Workshop metadata handling so mods with real titles in `project.xml` no longer get stuck showing only the numeric Workshop ID in the UI.
- Improved startup and refresh performance by removing an extra full UI refresh/save cycle from the silent auto-categorize path used during mod loading.
- Removed the dormant `Save Loadout` and `Load Loadout` buttons from the main UI while keeping the legacy loadout code quarantined for possible future reuse.
- Continued the internal cleanup work by splitting category, localization, state, path/discovery, and legacy loadout logic out of the main file without changing the app's overall workflow.

## v0.1.9 - 2026-05-25

- Fixed the stubborn `Save` and `Cancel` buttons in the `Edit Categories` dialog so they stop collapsing in the packaged app.
- Added the current app version beside `Load Order Ledger` in the main window.
- Updated release packaging so published zip and SHA256 asset filenames now include the version number automatically.

## v0.1.8 - 2026-05-25

- Fixed custom category sorting so `Auto Sort` and `Apply Order to Local Mods` now respect the user-selected category order instead of pushing custom categories to the bottom.
- Cleaned up multiple Simplified Chinese UI labels so the wording feels more natural in buttons, profile/save language, category controls, and view-mode labels.
- Fixed the `Edit Categories` dialog so the `Save` and `Cancel` buttons no longer collapse into tiny wedge-shaped controls.

## v0.1.7 - 2026-05-25

- Fixed language switching so startup-derived status text now updates to the newly selected language instead of staying in the app's startup language.
- Fixed built-in mod category tags in the enabled and reserve lists so they refresh immediately when the language is changed from the menu.
- Fixed the enabled/disabled/uncategorized summary line so it now translates correctly after changing languages at runtime.
- Adjusted the startup splash card width again for Spanish so localized splash text is less likely to clip at launch.

## v0.1.6 - 2026-05-25

- Added app localization support with a language picker and saved language preference.
- Added Simplified Chinese, Portuguese, and Spanish translations for the startup splash, main UI, file-path editor, nickname dialog, filter labels, view-mode labels, and built-in mod category tags.
- Added first-run OS language detection so packaged builds can start in Chinese, Portuguese, or Spanish when the local system language matches.
- Updated the startup splash sizing by language so longer localized titles and loading text fit cleanly without wrapping.

## v0.1.5 - 2026-05-11

- Added GOG-aware game install detection on Windows, including common GOG Galaxy folders and registry-based install paths.
- Added a Windows fallback scan for `Documents\\Darkest` saves and a Linux non-Steam fallback scan for `~/.local/share/Red Hook Studios/Darkest/`.
- Added a new `File Paths` dialog so users can review, auto-fill, clear, or manually override the game install folder, active mods folder, local mods folder, Workshop mods folder, and profile save file.
- `File Paths` now shows the live resolved paths the app is currently using, normalizes displayed paths, and lets users recover when auto-detect misses part of a non-Steam setup.
- Renamed `Load Mods` to `Refresh Mods` so the button better reflects rescanning for new installs, updates, and subscriptions.
- Windows launch now falls back to the local game executable when the Steam URI is unavailable.

## v0.1.4 - 2026-05-11

- Improved Windows profile auto-detection by reading Steam install paths from the registry instead of relying only on default `Program Files` locations.
- Added a Windows fallback scan for `Documents\\Darkest` profile saves so profiles can still be found when Steam Cloud paths are missing or not in use.

## v0.1.3 - 2026-05-10

- Added preliminary Linux-aware Steam detection for common install roots and library paths while keeping the current Windows auto-detect behavior unchanged.
- Added a Linux fallback for launching Darkest Dungeon through Steam when `os.startfile(...)` is not available.
- Added Linux font fallbacks for the main UI, splash screen, and code preview while preserving the existing Windows font choices.

## v0.1.2 - 2026-05-09

- Fixed Shift-click multi-select in both mod panels so repeated range selections keep expanding the current highlight instead of collapsing it or jumping to an unexpected anchor.
- Kept selection-anchor tracking stable across drag, reorder, and cross-panel moves so follow-up Shift selections behave consistently after list interactions.

## v0.1.1 - 2026-05-08

- Added an explicit proprietary `LICENSE.md` and README notice clarifying that the repository is not open source.
- Simplified the main UI around a profile-first patching flow.
- Removed `Patch Auto-Detected Save` from the main action row and kept it as `Tools > Patch Auto-Detected Save (Legacy)`.
- Hid the old `Save Loadout` / `Load Loadout` flow from the main UI while keeping the underlying code around for now.
- Updated the build script to retry portable zip creation so Windows file locks are less likely to break release packaging.
- Profile picker now shows save date and hours played from save metadata when available.
- Rapid repeated view-mode clicks are debounced, and icon loading after a view switch is backgrounded to prevent freezing.

## v0.1.0 - 2026-05-06

- First tagged GitHub release.
- Added GitHub Actions release automation for version tags matching `v*`.
- Added portable release packaging through `build.ps1`.
- Published `DD Manager Portable.zip` and a matching SHA256 file through GitHub Releases.
