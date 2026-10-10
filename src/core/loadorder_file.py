"""The contract module of the ``ddmanager.loadorder`` file: one import path for the document
format (:mod:`src.core.loadorder_document`), its resolution against installed mods
(:mod:`src.core.loadorder_resolve`) and the 0.2 loadout import
(:mod:`src.core.loadout_v02`)."""

from src.core.json_values import JsonValue
from src.core.loadorder_document import (
    FORMAT,
    FORMAT_VERSION,
    GAME,
    LoadOrderDocument,
    LoadOrderEntry,
    document_from_order,
    dump_load_order,
    parse_load_order,
)
from src.core.loadorder_resolve import ResolveResult, resolve_document
from src.core.loadout_v02 import LoadoutV02Extras, parse_loadout_v02

__all__ = [
    "FORMAT",
    "FORMAT_VERSION",
    "GAME",
    "JsonValue",
    "LoadOrderDocument",
    "LoadOrderEntry",
    "LoadoutV02Extras",
    "ResolveResult",
    "document_from_order",
    "dump_load_order",
    "parse_load_order",
    "parse_loadout_v02",
    "resolve_document",
]
