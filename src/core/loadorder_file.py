"""The contract module of the ``ddmanager.loadorder`` file: one import path for the document
format (:mod:`src.core.loadorder_document`), its resolution against installed mods
(:mod:`src.core.loadorder_resolve`) and the legacy loadout import
(:mod:`src.core.loadorder_legacy`)."""

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
from src.core.loadorder_legacy import LegacyLoadoutExtras, parse_legacy_loadout
from src.core.loadorder_resolve import ResolveResult, resolve_document

__all__ = [
    "FORMAT",
    "FORMAT_VERSION",
    "GAME",
    "JsonValue",
    "LegacyLoadoutExtras",
    "LoadOrderDocument",
    "LoadOrderEntry",
    "ResolveResult",
    "document_from_order",
    "dump_load_order",
    "parse_legacy_loadout",
    "parse_load_order",
    "resolve_document",
]
