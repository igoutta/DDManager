"""``python run.py --self-test`` boots Qt headless, checks the install and exits 0."""

import os
import subprocess
from pathlib import Path

import pytest

from src.cli import main as cli_main

ROOT = Path(__file__).parents[2]


@pytest.mark.slow
def test_self_test_exits_zero_in_the_dev_environment(tmp_path: Path):
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    result = subprocess.run(
        ["uv", "run", "python", "run.py", "--self-test", "--data-dir", str(tmp_path / "data")],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    # the contract prints the AppPaths mode and path; no window is shown, so it returns promptly
    assert str(tmp_path / "data") in result.stdout, result.stdout
    assert "self-test: ok" in result.stdout, result.stdout


def test_the_cli_forwards_the_gui_flags_to_the_app(monkeypatch: pytest.MonkeyPatch):
    """``DD Manager.exe --self-test`` enters through ``src.cli.main`` (see packaging/entry.py)."""
    seen: list[list[str]] = []

    def fake_app_main(argv: list[str] | None = None) -> int:
        seen.append(list(argv or []))
        return 0

    monkeypatch.setattr("src.app.main", fake_app_main)
    flags = ["--self-test", "--lang", "es_ES", "--log-level", "DEBUG", "--safe-mode"]
    assert cli_main([*flags, "--data-dir", "somewhere"]) == 0
    assert seen == [[*flags, "--data-dir", "somewhere"]]
