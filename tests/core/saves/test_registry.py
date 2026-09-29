"""SaveFormatRegistry.detect/get and the default registry."""

import random
import struct
from collections.abc import Collection, Sequence
from dataclasses import dataclass

import pytest

from src.core.errors import AmbiguousSaveFormatError, SaveFormatError, UnknownSaveFormatError
from src.core.ids import SaveIdentity
from src.core.saves import DEFAULT_SAVE_FORMATS, default_registry
from src.core.saves.dson_v1 import DsonV1Format
from src.core.saves.format import SaveFormatRegistry, SaveValidationReport
from tests.support.dson_builder import (
    THREE_ENTRIES,
    build_save,
    sample_variants,
    standard_root,
    standard_save,
)


@dataclass(frozen=True, slots=True)
class AlwaysSniffs:
    """A second format whose sniff always hits, to provoke ambiguity."""

    format_id: str = "fake.always"
    writable: bool = False

    def sniff(self, raw: bytes) -> bool:
        return True

    def validate(self, raw: bytes) -> SaveValidationReport:
        return SaveValidationReport((), ())

    def check(self, raw: bytes) -> None:
        return None

    def read_applied(self, raw: bytes) -> tuple[SaveIdentity, ...]:
        return ()

    def write_applied(self, raw: bytes, entries: Sequence[SaveIdentity]) -> bytes:
        return raw

    def read_scalars(
        self, raw: bytes, names: Collection[str]
    ) -> dict[str, bool | int | str | bytes]:
        return {}


def test_default_registry_holds_dson_v1() -> None:
    assert [f.format_id for f in DEFAULT_SAVE_FORMATS] == ["dson.v1"]
    registry = default_registry()
    assert isinstance(registry.formats, tuple)
    assert [f.format_id for f in registry.formats] == ["dson.v1"]
    assert registry.get("dson.v1").format_id == "dson.v1"


@pytest.mark.parametrize("name", sorted(sample_variants()))
def test_detect_picks_dson_v1_for_builder_saves(name: str) -> None:
    detected = default_registry().detect(sample_variants()[name])
    assert detected.format_id == "dson.v1"
    assert isinstance(detected, DsonV1Format)


def test_sniff_does_not_need_the_magic() -> None:
    raw = build_save(standard_root(THREE_ENTRIES), magic=b"\x00\x00\x00\x00")
    assert default_registry().detect(raw).format_id == "dson.v1"


NOT_DSON = {
    "empty": b"",
    "short": standard_save(None)[:63],
    "random": random.Random(3).randbytes(256),
    "decoded_text": b'{\n    "base_root" : {\n        "version" : 5\n    }\n}\n',
    "header_length_60": standard_save(None)[:8] + struct.pack("<i", 60) + standard_save(None)[12:],
    "meta1_offset_0": standard_save(None)[:24] + struct.pack("<i", 0) + standard_save(None)[28:],
}


@pytest.mark.parametrize("name", sorted(NOT_DSON))
def test_detect_raises_unknown_for_non_dson_bytes(name: str) -> None:
    registry = default_registry()
    assert not registry.get("dson.v1").sniff(NOT_DSON[name])
    with pytest.raises(UnknownSaveFormatError):
        registry.detect(NOT_DSON[name])


def test_detect_raises_ambiguous_when_two_sniffers_hit() -> None:
    registry = SaveFormatRegistry([DsonV1Format(), AlwaysSniffs()])
    with pytest.raises(AmbiguousSaveFormatError):
        registry.detect(standard_save(None))
    # the fake alone still resolves
    assert registry.get("fake.always").format_id == "fake.always"
    assert SaveFormatRegistry([AlwaysSniffs()]).detect(b"anything").format_id == "fake.always"


def test_get_unknown_id_raises_key_error() -> None:
    with pytest.raises(KeyError):
        default_registry().get("dson.v9")


def test_registry_errors_are_save_format_errors() -> None:
    assert issubclass(UnknownSaveFormatError, SaveFormatError)
    assert issubclass(AmbiguousSaveFormatError, SaveFormatError)
    with pytest.raises(SaveFormatError):
        default_registry().detect(b"")
