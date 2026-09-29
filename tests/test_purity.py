"""src/core and src/rules are pure: stdlib-only, no filesystem, no clock, no Qt."""

import ast
from pathlib import Path

ROOT = Path(__file__).absolute().parent.parent / "src"
PURE_DIRS = (ROOT / "core", ROOT / "rules")

ALLOWED_MODULES = {
    "struct",
    "dataclasses",
    "enum",
    "typing",
    "collections",
    "collections.abc",
    "itertools",
    "functools",
    "heapq",
    "re",
    "html",
    "json",
    "fnmatch",
    "unicodedata",
    "math",
    "bisect",
    "types",
    "xml.etree.ElementTree",
    "datetime",
    "operator",
    "string",
    "textwrap",
    "hashlib",
    "pathlib",
    "abc",
    "copy",
    "warnings",
}
ALLOWED_PATHLIB_NAMES = {"PurePath", "PurePosixPath", "PureWindowsPath"}
FORBIDDEN_CALLS = {"open", "print", "input", "exec", "eval"}
# method names that imply filesystem I/O or wall-clock access
FORBIDDEN_ATTR_CALLS = {
    "exists",
    "is_file",
    "is_dir",
    "read_bytes",
    "read_text",
    "write_bytes",
    "write_text",
    "stat",
    "iterdir",
    "glob",
    "rglob",
    "walk",
    "mkdir",
    "unlink",
    "rename",
    "now",
    "today",
    "utcnow",
    "time",
    "monotonic",
}


def _check(path: Path) -> list[str]:
    tree = ast.parse(path.read_text("utf-8"), filename=str(path))
    rel = path.relative_to(ROOT)
    problems: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            problems.extend(
                f"{rel}: import {alias.name}"
                for alias in node.names
                if alias.name not in ALLOWED_MODULES and not alias.name.startswith("src.core")
            )
        elif isinstance(node, ast.ImportFrom) and node.module:
            mod = node.module
            if mod == "pathlib":
                bad = {a.name for a in node.names} - ALLOWED_PATHLIB_NAMES
                if bad:
                    problems.append(f"{rel}: from pathlib import {sorted(bad)}")
            elif mod not in ALLOWED_MODULES and not mod.startswith(("src.core", "src.rules")):
                problems.append(f"{rel}: from {mod} import ...")
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in FORBIDDEN_CALLS:
                problems.append(f"{rel}:{node.lineno}: call to {func.id}()")
            elif isinstance(func, ast.Attribute) and func.attr in FORBIDDEN_ATTR_CALLS:
                problems.append(f"{rel}:{node.lineno}: call to .{func.attr}()")
        elif isinstance(node, ast.Name) and node.id == "Path":
            problems.append(f"{rel}:{node.lineno}: concrete pathlib.Path is not allowed in core")
    return problems


def test_core_and_rules_are_pure() -> None:
    problems: list[str] = []
    for directory in PURE_DIRS:
        if not directory.exists():
            continue
        for path in sorted(directory.rglob("*.py")):
            problems.extend(_check(path))
    assert problems == []
