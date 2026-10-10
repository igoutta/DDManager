"""Enforce the import matrix between layers with a stdlib AST walk (no import-linter dependency)."""

import ast
from pathlib import Path

SRC = Path(__file__).absolute().parent.parent / "src"

# layer prefix -> module prefixes it must NOT import
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
    # the module names of DD Manager 0.2.x (deleted at the 0.3.0 cutover) and the research
    # scripts: nothing under src/ may ever import them again
    "src": ("dd2", "categories", "localization", "paths", "state", "legacy_loadout", "research"),
}


def _module_name(path: Path) -> str:
    rel = path.relative_to(SRC.parent).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text("utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return found


def _violations() -> list[str]:
    problems: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        module = _module_name(path)
        for layer, banned in FORBIDDEN.items():
            if module != layer and not module.startswith(layer + "."):
                continue
            problems.extend(
                f"{module} imports {imported} (forbidden for {layer})"
                for imported in sorted(_imports(path))
                for prefix in banned
                if imported == prefix or imported.startswith(prefix + ".")
            )
    return problems


def test_layering() -> None:
    assert _violations() == []
