"""Typed error hierarchy shared by every layer.

Every error carries a human-readable ``message``, a machine-readable ``code`` and free-form
``details``.  Two levels of "what went wrong" are modelled explicitly:

* ``family`` is the class-level error family (``DsonUnsupportedError.family == "dson_unsupported"``)
  and is what ``isinstance`` narrows on;
* ``code`` is the per-instance reason, passed through the ``code=`` keyword
  (``DsonUnsupportedError("...", code="no_anchor")``) and defaulting to the family when no reason
  is given.  Service code matches on ``exc.code``; the family stays readable as
  ``type(exc).family``.

``str(exc)`` is always ``[code] message`` so logs carry the reason; ``exc.args`` keeps the bare
message.
"""

from typing import ClassVar


class DDManagerError(Exception):
    """Base class for every error raised by DD Manager code."""

    family: ClassVar[str] = "error"
    message_key: ClassVar[str] = "error.generic"

    code: str
    message: str
    details: dict[str, object]

    def __init__(self, message: str, **details: object) -> None:
        super().__init__(message)
        self.message = message
        self.details = dict(details)
        code = details.get("code")
        self.code = code if isinstance(code, str) and code else type(self).family

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"


class SaveFormatError(DDManagerError):
    """Anything wrong with a save file's bytes or with how we may rewrite them."""

    family = "save_format"
    message_key = "error.save_format"


class UnknownSaveFormatError(SaveFormatError):
    """No registered save format recognised the bytes."""

    family = "unknown_save_format"
    message_key = "error.unknown_save_format"


class AmbiguousSaveFormatError(SaveFormatError):
    """More than one registered save format claimed the bytes."""

    family = "ambiguous_save_format"
    message_key = "error.ambiguous_save_format"


class DsonFormatError(SaveFormatError):
    """The input is not a (legacy-)valid DSON document, or a lookup hit a malformed field.

    Reason codes: the validator's problem codes (``file_size_mismatch``, ``hash_mismatch``, ...),
    ``input_invalid`` (``write_applied``'s input gate; ``details["problem"]`` holds the validator
    code), ``unsupported_header_layout``, ``not_an_object``, ``not_a_scalar``,
    ``name_source_shape`` (a name/source list whose child is not ``{name, source}``).
    """

    family = "dson_format"
    message_key = "error.dson_format"


class DsonUnsupportedError(SaveFormatError):
    """Valid DSON, but a layout we refuse to read as, or rewrite into, the applied-mods block.

    Reason codes: ``applied_not_at_root``, ``applied_not_object``, ``no_anchor``,
    ``unsafe_realign``, ``nested_object_span``.
    """

    family = "dson_unsupported"
    message_key = "error.dson_unsupported"


class RoundTripError(SaveFormatError):
    """The rewritten save failed a post-write gate.

    Reason codes: ``output_invalid``, ``entries_mismatch``, ``strict_regression``.
    """

    family = "round_trip"
    message_key = "error.round_trip"
