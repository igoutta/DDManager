# DD Manager task runner (Windows-first; recipes are single `uv run` lines so they also run under sh).
# Bootstrap once:  just install

set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command"]
set dotenv-load := false

default:
    @just --list --unsorted

# Provision Python 3.14 and create .venv with app + dev + build groups
install:
    uv python install 3.14
    uv sync --group dev --group build

# Lint without modifying files
lint:
    uv run ruff check .
    uv run ruff format --check .

# Auto-fix lint + format
fmt:
    uv run ruff check --fix .
    uv run ruff format .

# Type-check with ty
typecheck:
    uv run ty check

# All tests (Qt tests run offscreen via tests/ui/conftest.py)
test *args:
    uv run pytest {{args}}

# Domain tests WITHOUT Qt loaded: proves core/rules/services/plugins never import PySide6
test-core *args:
    uv run pytest -p no:pytestqt tests/core tests/rules tests/services tests/plugins tests/test_layering.py tests/test_purity.py {{args}}

# lint + typecheck + test (what CI runs)
check: lint typecheck test

# Run the app from source against <repo>/DD Manager Data
run *args:
    uv run python run.py {{args}}

# Headless CLI (ddmanager --help)
cli *args:
    uv run ddmanager {{args}}

# Regenerate tests/golden from this program; a changed golden is refused unless --update is passed
regen-goldens *args:
    uv run python tools/regen_goldens.py {{args}}

# Real-game corpus tests: DDM_SAVE_CORPUS / DDM_STATE_CORPUS / DDM_MODS_ROOT default to <repo>/.corpus (see corpus-refresh)
corpus *args:
    uv run python tools/corpus_env.py -- uv run pytest -m corpus {{args}}

# Copy the game's saves (and its own backup/ copies) and the active mod_state.json into <repo>/.corpus; originals are only read
corpus-refresh *args:
    uv run python tools/make_corpus.py {{args}}

# Print the corpus environment the corpus recipe would use
corpus-env:
    uv run python tools/corpus_env.py

# Write the load-order probe mods into the game's mods folder (or into dest)
probe-kit dest="":
    uv run python tools/probe_kit.py "{{dest}}"

# Build the frozen Windows app + portable zip
[windows]
build:
    ./packaging/build.ps1

# Self-test the already-built frozen exe (dist/DD Manager/DD Manager.exe --self-test); run `just build` first
[windows]
build-check:
    ./packaging/build.ps1 -SelfTestOnly

# Remove build artifacts and caches (never touches "DD Manager Data")
clean:
    uv run python tools/clean.py
