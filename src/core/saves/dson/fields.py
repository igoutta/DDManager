"""Field payloads: alignment, string fields, scalar decoding and re-padding for a new offset.

Ports of dd2.py:758-830 and 910-935.  :func:`assert_shift_safe` is the guard the splice primitive
runs before :func:`rebuild_field_block` moves a field.
"""

from src.core.errors import DsonUnsupportedError
from src.core.saves.dson.layout import I32, DsonDocument, Meta2
from src.core.saves.format import DsonScalar


def align_pad(relative_offset: int) -> int:
    """Zero bytes needed to reach the next 4-byte boundary of the data block (dd2.py:798).

    ``relative_offset`` is the data-relative offset right AFTER the NUL-terminated field name
    (the legacy helper took the offset before the name and added the name length itself).
    """
    return (-relative_offset) % 4


def build_string_field(field_name: str, value: str, relative_offset: int) -> bytes:
    """dd2.py:803 ``dson_build_string_field``: name+NUL, pad to 4, i32 len incl. NUL, UTF-8, NUL.

    ``relative_offset`` is the data-relative offset at which the field starts.  The matching meta2
    record is ``Meta2(string_hash(field_name), relative_offset, field_info(field_name))``.
    """
    out = bytearray(field_name.encode("utf-8"))
    out.append(0)
    out.extend(b"\x00" * align_pad(relative_offset + len(out)))
    value_bytes = value.encode("utf-8") + b"\x00"
    out.extend(I32.pack(len(value_bytes)))
    out.extend(value_bytes)
    return bytes(out)


def payload_layout(data: bytes, entry: Meta2, next_offset: int) -> tuple[bytes, int, int]:
    """dd2.py:758 ``dson_field_payload_layout``: ``(payload, payload_start, value_end)``.

    Objects have no payload; a 1-byte payload is unaligned; anything longer starts at the next
    4-byte boundary of the data block.
    """
    value_start = entry.offset + entry.name_length
    value_end = next_offset
    if entry.is_object or value_end <= value_start:
        return b"", value_start, value_end
    raw_value = data[value_start:value_end]
    if len(raw_value) == 1:
        return bytes(raw_value), value_start, value_end
    aligned_start = value_start + ((-value_start) % 4)
    if aligned_start > value_end:
        return b"", aligned_start, value_end
    return bytes(data[aligned_start:value_end]), aligned_start, value_end


def _decode_string_payload(payload: bytes) -> str | None:
    """Exact length-prefixed string check (replaces the ASCII-only guess of dd2.py:362)."""
    if len(payload) < 5:
        return None
    length = I32.unpack_from(payload, 0)[0]
    if length < 1 or 4 + length != len(payload) or payload[-1] != 0:
        return None
    body = payload[4:-1]
    if 0 in body:
        return None
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        return None


def decode_scalar(data: bytes, entry: Meta2, next_offset: int) -> DsonScalar:
    """Port of dd2.py:780 ``dson_decode_scalar_field`` with an exact, UTF-8 aware string check.

    1 byte -> bool; a well-formed length-prefixed string -> str; exactly 4 bytes -> int; anything
    else (floats, vectors, empty payloads) -> the raw payload bytes.  The legacy helper returned
    the first i32 of any longer payload and ``None`` for an empty one.
    """
    payload, _, _ = payload_layout(data, entry, next_offset)
    if len(payload) == 1:
        return bool(payload[0])
    text = _decode_string_payload(payload)
    if text is not None:
        return text
    if len(payload) == 4:
        return I32.unpack_from(payload, 0)[0]
    return bytes(payload)


def rebuild_field_block(data: bytes, entry: Meta2, next_offset: int, new_offset: int) -> bytes:
    """dd2.py:910 ``dson_rebuild_existing_field_block``: re-pad a field for its new offset.

    Objects are their name only; a 1-byte payload is copied unaligned; any other payload is taken
    from its old 4-byte boundary and re-padded for the new one.
    """
    name_length = entry.name_length
    old_offset = entry.offset
    field_name_bytes = data[old_offset : old_offset + name_length]
    if entry.is_object:
        return bytes(field_name_bytes)
    old_data_start = old_offset + name_length
    old_data_size = next_offset - old_data_start
    if old_data_size == 1:
        return bytes(field_name_bytes) + bytes(data[old_data_start:next_offset])
    old_align = (-old_data_start) % 4
    payload_start = old_data_start + old_align
    payload = data[payload_start:next_offset]
    new_data_start = new_offset + name_length
    new_align = (-new_data_start) % 4
    return bytes(field_name_bytes) + (b"\x00" * new_align) + bytes(payload)


def assert_shift_safe(doc: DsonDocument, i: int, new_offset: int) -> None:
    """Refuse fields that :func:`rebuild_field_block` would silently corrupt at ``new_offset``.

    The legacy rebuild copies a 1-byte payload verbatim; for anything else it keeps the bytes from
    the field's old 4-byte boundary on (the aligned payload of :func:`payload_layout`) and replaces
    whatever came before them with ``new_align`` zero bytes.  That is a faithful move only when

    * the bytes it drops are zero padding (non-zero bytes there are data we do not understand),
    * the old boundary lies inside the region (past it the payload is dropped and zeros added),
    * and, if the alignment actually changes, the aligned payload is a plausible aligned value of
      at least 4 bytes: a 0-3 byte "aligned payload" is no int, float or string, and moving it to
      another boundary changes its size or turns it into an unaligned bool.

    A move that keeps the alignment (``delta % 4 == 0``) reproduces the region byte for byte, so
    short payloads pass there, exactly as the legacy patcher left them alone.
    """
    entry = doc.meta2[i]
    if entry.is_object:
        return
    start = entry.offset + entry.name_length
    end = doc.field_end(i)
    size = end - start
    if size == 1:
        return
    old_align = (-start) % 4
    new_align = (-(new_offset + entry.name_length)) % 4
    payload, payload_start, _ = payload_layout(doc.data, entry, end)
    if old_align > size:
        reason = f"has a {size}-byte region that ends before its 4-byte boundary"
    elif any(doc.data[start:payload_start]):
        reason = "has non-zero bytes in its alignment padding"
    elif old_align != new_align and len(payload) < 4:
        reason = f"has a {len(payload)}-byte aligned payload that cannot be realigned safely"
    else:
        return
    raise DsonUnsupportedError(
        f"field {doc.name_of(i)!r} at {entry.offset} {reason}",
        code="unsafe_realign",
        field=doc.name_of(i),
        offset=entry.offset,
        size=len(payload),
        region=size,
    )
