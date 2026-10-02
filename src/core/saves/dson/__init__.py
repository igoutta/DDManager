"""Binary DSON codec for Darkest Dungeon 1 saves (``persist.game.json`` and friends).

Pure port of the module-level ``dson_*`` helpers of the legacy app (``dd2.py`` at commit
``31e85d6``, lines 315-1641).  The legacy file had four copy-pasted serializers and two
near-duplicate resize algorithms; here there is ONE :func:`serialize` and ONE splice primitive
that :func:`replace_name_source_object`, :func:`insert_name_source_object` and
:func:`patch_scalar_string` all go through.

The package is layered bottom-up; every module documents the legacy lines it ports:

* :mod:`.layout` - constants, bit helpers, ``DsonHeader`` / ``Meta1`` / ``Meta2`` /
  ``DsonDocument`` and the table readers;
* :mod:`.fields` - payload alignment, string fields, scalar decoding, re-padding;
* :mod:`.walk` - the one stack walk shared by the validator and the document builder;
* :mod:`.validate` - the LEGACY and STRICT validation levels;
* :mod:`.document` - ``parse`` / ``serialize`` and tree lookups;
* :mod:`.splice` - the splice primitive;
* :mod:`.edits` - the public edits;
* :mod:`.readers` - identities and scalars out of a document.

The public API is what ``__all__`` lists (``from src.core.saves import dson`` is the whole
API, including the two codec errors); names defined in the submodules are package internals,
whatever their spelling.
"""

from src.core.errors import DsonFormatError, DsonUnsupportedError
from src.core.saves.dson.document import parse, serialize
from src.core.saves.dson.edits import (
    insert_name_source_object,
    patch_scalar_string,
    replace_name_source_object,
)
from src.core.saves.dson.fields import (
    align_pad,
    build_string_field,
    decode_scalar,
    payload_layout,
    rebuild_field_block,
)
from src.core.saves.dson.layout import (
    DSON_MAGIC,
    HEADER_SIZE,
    META1_SIZE,
    META2_SIZE,
    DsonDocument,
    DsonHeader,
    Meta1,
    Meta2,
    field_info,
    meta2_name,
    object_index_from_info,
    read_header,
    set_object_index_in_info,
    string_hash,
)
from src.core.saves.dson.readers import read_name_source_object, read_scalars
from src.core.saves.dson.validate import validate

__all__ = [
    "DSON_MAGIC",
    "HEADER_SIZE",
    "META1_SIZE",
    "META2_SIZE",
    "DsonDocument",
    "DsonFormatError",
    "DsonHeader",
    "DsonUnsupportedError",
    "Meta1",
    "Meta2",
    "align_pad",
    "build_string_field",
    "decode_scalar",
    "field_info",
    "insert_name_source_object",
    "meta2_name",
    "object_index_from_info",
    "parse",
    "patch_scalar_string",
    "payload_layout",
    "read_header",
    "read_name_source_object",
    "read_scalars",
    "rebuild_field_block",
    "replace_name_source_object",
    "serialize",
    "set_object_index_in_info",
    "string_hash",
    "validate",
]
