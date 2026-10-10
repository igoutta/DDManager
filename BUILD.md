# Build Instructions

This repository contains the full source of DD Manager, a PySide6 (Qt) desktop application for
Darkest Dungeon. The portable Windows release is built with PyInstaller from a locked Python
environment managed by [uv](https://docs.astral.sh/uv/).

## Source layout

- Application package: `src/` (the import name is literally `src`; layers and entry points are
  described in `docs/architecture.md`)
- Frozen entry point: `packaging/entry.py` (calls `src.cli.main`; with no arguments it starts the
  window, `--self-test` checks the installation and exits)
- Build script: `packaging/build.ps1` (PowerShell 5.1 or newer)
- PyInstaller spec: `packaging/ddmanager.spec`
- Windows version resource template: `packaging/version_info.tmpl`
- Application icon: `packaging/ddmanager.ico` (used when present)
- Runtime resources bundled into the app: `src/resources/` (translations, default rules, icons) and
  `src/ui/theme/dark.qss` (the stylesheet template)
- Version, single source: `src/__about__.py`
- Dependencies: `pyproject.toml`, locked in `uv.lock`

## Build environment

- Windows (the build recipe is Windows only)
- [uv](https://docs.astral.sh/uv/), which provisions **Python 3.14** itself (`.python-version`)
- The `dev` and `build` dependency groups: PySide6-Essentials, PyInstaller, and the test and lint
  tools

## Clean build steps

1. Open PowerShell in the repository root.
2. Provision Python and install every dependency from `uv.lock`:

   ```powershell
   uv python install 3.14
   uv sync --group dev --group build
   ```

3. Run the checks (recommended; this is what CI runs):

   ```powershell
   uv run just check
   ```

4. Build:

   ```powershell
   uv run just build
   ```

`just build` runs `./packaging/build.ps1`; running that script directly is the same thing. (Use
`uv run just ...`, or activate `.venv` to type plain `just`.)

## What the build script does

Inputs: the working tree (`src/`, `packaging/`, `README.md`), `uv.lock`, and the version in
`src/__about__.py`.

1. Reads the version from `src/__about__.py`. The release label for the zip name is the tag name
   when CI runs on a tag (`GITHUB_REF_TYPE=tag`), else the exact git tag at `HEAD`, else
   `v<version>`.
2. Renders `build/version_info.txt` (the Windows VERSIONINFO resource) from
   `packaging/version_info.tmpl`.
3. Runs PyInstaller on `packaging/ddmanager.spec` in `--onedir` mode with `--noconfirm --clean`,
   producing `dist/DD Manager/` (`DD Manager.exe` plus `_internal/`). The spec trims Qt to what a
   widgets application needs: it excludes `tkinter` and the Qt modules the app does not use
   (QtNetwork, QtQml, QtQuick, QtOpenGL, QtPdf, QtMultimedia, QtWebEngine, Qt3D, QtCharts,
   QtDesigner, ...), keeps only the `qwindows` platform plugin, the `qjpeg`, `qgif`, `qico`, `qsvg`
   and `qwebp` image formats, the SVG icon engine, the styles plugin and the Qt translations of the
   four UI languages, and drops `opengl32sw.dll`.
4. Self-tests the frozen build: `DD Manager.exe --self-test --data-dir %TEMP%\ddm-frozen-selftest`
   (started with a 2 minute timeout and its output captured) checks the image formats, the platform
   plugin, the bundled resources, that the built-in mod sources, rules and save formats are
   registered, and where the data folder lands. The build fails if it does not exit 0 and print
   `self-test: ok`. To repeat this check on an existing build: `just build-check`.
5. Assembles `release/DD Manager Portable/`: the app, `README.md`, and `DD Manager Data/`
   containing `README.txt` and `icon_cache/.keep`. The build fails if any `mod_state*.json` is
   inside, so user state can never be packaged.
6. Zips it as `release/DD Manager Portable <version>.zip` (retrying if antivirus holds a file), then
   opens the zip and verifies it holds the exe, `_internal/`, `README.md` and the two data-folder
   files and no `mod_state*.json`; otherwise it deletes the zip and fails.

Outputs:

- `dist/DD Manager/DD Manager.exe` (the frozen app)
- `release/DD Manager Portable/` (the portable folder)
- `release/DD Manager Portable <version>.zip`

The layout is the same as the v0.2.x releases, so users extract a new zip over their existing
`DD Manager Portable` folder and keep `DD Manager Data`.

## Continuous integration

- `.github/workflows/ci.yml` runs ruff, `ruff format --check` and `ty` on Linux, the test suite on
  Windows and Linux (Qt runs offscreen; `fetch-depth: 0` so the build can label the zip with the
  exact git tag at `HEAD`), and on pushes to `main` the build above.
- `.github/workflows/release.yml` runs the same `packaging/build.ps1` on a `v*` tag and attaches
  the zip and its `.sha256` file to the GitHub release.

## Reproducibility

The environment is pinned by `uv.lock` (PySide6, PyInstaller and every transitive dependency) and
by Python 3.14. A fresh clone builds with `uv sync --group dev --group build` followed by
`just build`. `just clean` removes `build/`, `dist/`, caches and `__pycache__` folders (it never
touches `release/`, `.venv/` or any `DD Manager Data`).

## Notes for review

- The program is a local desktop application written in Python with PySide6. It makes no network
  requests (`Open Workshop Page` only hands a URL to your browser) and has no custom installer.
- It is packaged with PyInstaller, which can sometimes trigger antivirus heuristics.
- UPX compression is disabled (`upx=False` in the spec) to reduce false positives on some scanners.
- The portable zip never contains user data; `DD Manager Data/README.txt` explains that extracting
  a newer release over the folder keeps it.
