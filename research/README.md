# Research scripts

Historical DSON research scripts from the v0.2.x era, kept for reference only:

- `dson_*.py`, `DD Parse.py`, `DD extractor.py`: one-off experiments that decode, probe and patch
  Darkest Dungeon's binary save files (`persist.game.json`)
- `replacement_list.json`: sample input used by some of them

They contain hardcoded paths, are not maintained, are not linted or type-checked, are not part of the
test suite or the packaged app, and nothing in `src/` may import them (`tests/test_layering.py`).

**The codec in `src/core/saves` is the source of truth** for the save format. Use
`ddmanager save inspect <file>` to look at a save instead of running these scripts.
