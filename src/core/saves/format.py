"""Save-format abstraction: validation reports, the ``SaveFormat`` protocol and its registry."""

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Protocol

from src.core.errors import AmbiguousSaveFormatError, UnknownSaveFormatError
from src.core.ids import SaveIdentity

type DsonScalar = bool | int | str | bytes
"""What ``read_scalars`` can decode: 1-byte bool, 4-byte int, length-prefixed string, else raw."""


@dataclass(frozen=True, slots=True)
class DsonProblem:
    """One validation finding.

    ``offset`` is the field's data-relative offset for field-level problems (the same number the
    structural validator reports) and the header byte offset for header/layout problems.
    """

    code: str
    offset: int
    message: str


@dataclass(frozen=True, slots=True)
class SaveValidationReport:
    """STRUCTURAL-level problems (what parsing requires) plus the extra STRICT-level ones."""

    structural_errors: tuple[DsonProblem, ...] = ()
    strict_errors: tuple[DsonProblem, ...] = ()

    @property
    def ok(self) -> bool:
        """True when the bytes are structurally valid (what parsing requires)."""
        return not self.structural_errors

    @property
    def ok_strict(self) -> bool:
        """True when there are no problems at either level."""
        return not self.structural_errors and not self.strict_errors

    @property
    def problems(self) -> tuple[DsonProblem, ...]:
        return self.structural_errors + self.strict_errors


class SaveFormat(Protocol):
    """A save file format that can at least read, and maybe rewrite, the applied-mods block."""

    @property
    def format_id(self) -> str: ...

    @property
    def writable(self) -> bool: ...

    def sniff(self, raw: bytes) -> bool:
        """Cheap check whether ``raw`` looks like this format (never raises)."""
        ...

    def validate(self, raw: bytes) -> SaveValidationReport:
        """Full validation report. NEVER raises."""
        ...

    def check(self, raw: bytes) -> None:
        """Raise ``DsonFormatError`` unless ``raw`` is structurally valid."""
        ...

    def read_applied(self, raw: bytes) -> tuple[SaveIdentity, ...]: ...

    def write_applied(self, raw: bytes, entries: Sequence[SaveIdentity]) -> bytes: ...

    def read_scalars(self, raw: bytes, names: Collection[str]) -> dict[str, DsonScalar]: ...


class SaveFormatRegistry:
    """Static list of formats; ``detect`` requires exactly one sniff hit."""

    def __init__(self, formats: Sequence[SaveFormat]) -> None:
        self._formats: tuple[SaveFormat, ...] = tuple(formats)
        ids = [f.format_id for f in self._formats]
        if len(set(ids)) != len(ids):
            raise ValueError(f"duplicate save format ids: {ids}")

    @property
    def formats(self) -> tuple[SaveFormat, ...]:
        return self._formats

    def detect(self, raw: bytes) -> SaveFormat:
        hits = [f for f in self._formats if f.sniff(raw)]
        if len(hits) == 1:
            return hits[0]
        if not hits:
            hint = ""
            if raw.lstrip()[:1] == b"{":
                hint = " (the file starts with '{': is this a decoded text save?)"
            raise UnknownSaveFormatError(
                f"no registered save format recognises these bytes{hint}",
                code="unknown_save_format",
                size=len(raw),
                head=bytes(raw[:8]),
            )
        raise AmbiguousSaveFormatError(
            "several save formats claim these bytes: " + ", ".join(f.format_id for f in hits),
            code="ambiguous_save_format",
            formats=tuple(f.format_id for f in hits),
        )

    def get(self, format_id: str) -> SaveFormat:
        for fmt in self._formats:
            if fmt.format_id == format_id:
                return fmt
        raise KeyError(format_id)
