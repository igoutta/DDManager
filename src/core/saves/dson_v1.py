"""``DsonV1Format``: the binary DSON layout the legacy app patched (dd2.py:1312, 1054)."""

import struct
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import ClassVar

from src.core.errors import DsonFormatError, DsonUnsupportedError, RoundTripError
from src.core.ids import SaveIdentity
from src.core.saves import dson
from src.core.saves.format import DsonScalar, SaveValidationReport


@dataclass(frozen=True, slots=True)
class DsonV1Format:
    """Reads and rewrites ``applied_ugcs_1_0`` in a DSON save with a 64-byte header.

    The descriptor values are class constants: a format's identity is not configurable.
    """

    format_id: ClassVar[str] = "dson.v1"
    writable: ClassVar[bool] = True
    applied_block: ClassVar[str] = "applied_ugcs_1_0"
    anchor_block: ClassVar[str] = "persistent_ugcs"

    def sniff(self, raw: bytes) -> bool:
        """64+ bytes, ``header_length == 64`` and ``meta1_offset == 64`` (magic NOT required)."""
        if len(raw) < dson.HEADER_SIZE:
            return False
        header_length = struct.unpack_from("<i", raw, 8)[0]
        meta1_offset = struct.unpack_from("<i", raw, 24)[0]
        return header_length == dson.HEADER_SIZE and meta1_offset == dson.HEADER_SIZE

    def validate(self, raw: bytes) -> SaveValidationReport:
        return dson.validate(raw)

    def check(self, raw: bytes) -> None:
        report = dson.validate(raw)
        if report.legacy_errors:
            first = report.legacy_errors[0]
            raise DsonFormatError(first.message, code=first.code, offset=first.offset)

    def read_applied(self, raw: bytes) -> tuple[SaveIdentity, ...]:
        """The root's applied block as identities; ``()`` when the block is absent.

        A root-level ``applied_ugcs_1_0`` that is a scalar is refused with
        :class:`DsonUnsupportedError` (``applied_not_object``), the same way ``write_applied``
        refuses it.
        """
        doc = dson.parse(raw)
        target = doc.find_child(0, self.applied_block)
        if target is None:
            return ()
        self._require_object(doc, target)
        return dson.read_name_source_object(doc, target)

    def write_applied(self, raw: bytes, entries: Sequence[SaveIdentity]) -> bytes:
        """Rewrite the applied block; byte-identical to the legacy patcher on well-formed saves.

        The one deliberate exception is bit 31 of the block's info words (an unknown game flag):
        the legacy cleared it, this keeps it per pre-existing entry (see ``dson/flags.py``), so a
        game-written save survives its own identity rewrite byte for byte.

        Gates: the input must be legacy-valid; the output must be legacy-valid and not strict-worse
        than the input ("never make a save worse"); reading the output back must give ``entries``
        exactly (full equality, not a count).  Empty ``entries`` are allowed.
        """
        wanted = tuple(entries)
        before = dson.validate(raw)
        if before.legacy_errors:
            first = before.legacy_errors[0]
            raise DsonFormatError(
                f"input save is not valid: {first.message}",
                code="input_invalid",
                problem=first.code,
                offset=first.offset,
            )
        out = dson.serialize(self._rewrite(dson.parse(raw), wanted))
        self._gate(before, out, wanted)
        return out

    def _require_object(self, doc: dson.DsonDocument, target: int) -> None:
        entry = doc.meta2[target]
        if not entry.is_object:
            raise DsonUnsupportedError(
                f"{self.applied_block} is a scalar field, not an object",
                code="applied_not_object",
                field=self.applied_block,
                offset=entry.offset,
            )

    def _rewrite(
        self, doc: dson.DsonDocument, wanted: tuple[SaveIdentity, ...]
    ) -> dson.DsonDocument:
        """Replace the root's applied block, or insert one before the anchor block."""
        target = doc.find_child(0, self.applied_block)
        if target is not None:
            self._require_object(doc, target)
            return dson.replace_name_source_object(doc, target, wanted)
        if doc.find_anywhere(self.applied_block) is not None:
            raise DsonUnsupportedError(
                f"{self.applied_block} exists but is not a direct child of the root object",
                code="applied_not_at_root",
                field=self.applied_block,
            )
        anchor = doc.find_child(0, self.anchor_block)
        if anchor is None or not doc.meta2[anchor].is_object:
            raise DsonUnsupportedError(
                f"save has neither {self.applied_block} nor an object {self.anchor_block}"
                " under the root",
                code="no_anchor",
                field=self.anchor_block,
            )
        return dson.insert_name_source_object(
            doc, before=anchor, name=self.applied_block, entries=wanted
        )

    def _gate(
        self, before: SaveValidationReport, out: bytes, wanted: tuple[SaveIdentity, ...]
    ) -> None:
        """Post-write gates: output legacy-valid, never strict-worse, entries read back exactly."""
        after = dson.validate(out)
        if after.legacy_errors:
            first = after.legacy_errors[0]
            raise RoundTripError(
                f"patched save failed validation: {first.message}",
                code="output_invalid",
                problem=first.code,
                offset=first.offset,
            )
        if before.ok_strict and not after.ok_strict:
            first = after.strict_errors[0]
            raise RoundTripError(
                f"patched save lost strict validity: {first.message}",
                code="strict_regression",
                problem=first.code,
                offset=first.offset,
            )
        if self.read_applied(out) != wanted:
            raise RoundTripError(
                "patched save does not read back the requested entries",
                code="entries_mismatch",
                expected=len(wanted),
            )

    def read_scalars(self, raw: bytes, names: Collection[str]) -> dict[str, DsonScalar]:
        return dson.read_scalars(raw, names)
