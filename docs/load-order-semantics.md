# Load-order semantics (Darkest Dungeon 1)

## What the app writes

The only order DD Manager writes to the game is the child order of the `applied_ugcs_1_0`
object inside `persist.game.json` (a binary DSON file). Entry `'0'` is the first enabled mod in
the Load Order pane, entry `'N-1'` the last. **Rank N in the UI == entry N-1 in the save**, always.
This is byte-identical to what DD Manager v0.2.1 wrote for the same order.

Each entry has two string fields:

| Mod kind | `name` | `source` |
|---|---|---|
| Steam Workshop | `PublishedFileId` (digits) | `Steam` |
| Local (`<game>/mods`) | `project.xml` `<Title>` (fallback: folder name without numeric prefix) | `mod_local_source` |

## Which end wins a conflict

**Decision (maintainer, 2026-09-29): the first entry wins.** When two enabled mods ship the same
file, the mod with the lower rank (closer to the top) is the one the game uses.

The app stores this as a setting, not a constant (`DD Manager Data/settings.json`; change it in
`View > Priority direction` or `Tools > Settings...`):

```json
{ "priority": { "direction": "first_wins", "verified": true } }
```

Everything that depends on direction (the "wins conflicts" label, `core.file_overlap`,
`core.patch_before_target`, `core.declared_load_after`, Auto-Sort placement) reads that setting.
Flipping it changes labels and rule verdicts only; the bytes written for a given order never change.
While `verified` is `false`, direction-dependent findings are capped at INFO.

## Confirming it empirically (probe kit)

`just probe-kit` writes two local mods straight into the game's local mods folder
(`<game>/mods` as the app detects it; pass a folder to write somewhere else instead):

- `ddm_probe_a` and `ddm_probe_b` both override
  `campaign/town/buildings/stage_coach/stage_coach.building.json` with a different, visible
  number of stage-coach recruits.
- `ddm_probe_b` also ships one file that its `modfiles.txt` does not list.

Setup in DD Manager: Rescan (F5); both probes appear in Available as local mods. For the
duration of the test, disable every other mod that overrides the stage coach (the Health panel
lists them as file overlaps with the probes, for example "Level 7 Stage Coach"); otherwise that
mod, not a probe, may be the winner you see.

Protocol (each step is one game launch):

1. Enable both at ranks 1 and 2 with A above B, patch, launch, note the recruit count in the
   Stage Coach (A = 4 base recruits, B = 8; stage-coach upgrades add to the base).
2. Swap to B above A, patch, launch, note the count. If step 1 showed A's value and step 2 showed
   B's, the first entry wins; the reverse means the last entry wins.
3. Rename the folders so their alphabetical order inverts (`zz_ddm_probe_a`) and repeat 1–2. If
   the winner follows the folder name instead of the list, the game orders local mods by folder
   name and the folder-rename tool ("Apply order to local mod folders") matters.
4. Save in-game, then run `ddmanager save inspect <persist.game.json>` and check whether the
   game rewrote `applied_ugcs_1_0` (order, entries).
5. Check whether B's unlisted file took effect (whether the game loads only `modfiles.txt`
   entries).

Record the outcome in the table below and set `verified` accordingly (`View > Priority direction > Direction verified`, or `Tools > Settings...`).

## Results

| Date | Tester | Direction | Folder name matters? | Game rewrites applied_ugcs? | Unlisted files load? |
|---|---|---|---|---|---|
| 2026-09-29 | maintainer (statement, not probe run) | first wins | unknown | unknown | unknown |
