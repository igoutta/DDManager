"""Save formats: the DSON codec, the ``SaveFormat`` protocol and the default registry."""

from src.core.saves.dson_v1 import DsonV1Format
from src.core.saves.format import (
    DsonProblem,
    DsonScalar,
    SaveFormat,
    SaveFormatRegistry,
    SaveValidationReport,
)

DEFAULT_SAVE_FORMATS: tuple[SaveFormat, ...] = (DsonV1Format(),)


def default_registry() -> SaveFormatRegistry:
    """A registry with every built-in format (static, so PyInstaller sees the imports)."""
    return SaveFormatRegistry(DEFAULT_SAVE_FORMATS)


__all__ = [
    "DEFAULT_SAVE_FORMATS",
    "DsonProblem",
    "DsonScalar",
    "DsonV1Format",
    "SaveFormat",
    "SaveFormatRegistry",
    "SaveValidationReport",
    "default_registry",
]
