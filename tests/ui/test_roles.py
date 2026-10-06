"""Roles, mime constant and the drag payload codec."""

import json
import os

import pytest
from PySide6.QtCore import QByteArray, QMimeData, Qt

from src.core.ids import ModId
from src.ui.models.roles import (
    MIME_MOD_IDS,
    DragOrigin,
    DragPayload,
    Role,
    decode_payload,
    encode_payload,
)

EXPECTED_ROLES = [
    "MOD_ID",
    "RANK",
    "TIER",
    "TIER_COLOR",
    "SOURCE",
    "SEARCH_BLOB",
    "SORT_KEY",
    "ENABLED",
    "IS_NEW",
    "WORST_SEVERITY",
    "FINDING_COUNT",
    "CATEGORY",
    "MISSING",
    "VM",
]


def test_roles_are_user_roles_unique_and_in_contract_order():
    assert [r.name for r in Role] == EXPECTED_ROLES
    values = [int(r) for r in Role]
    assert values == list(
        range(int(Qt.ItemDataRole.UserRole) + 1, int(Qt.ItemDataRole.UserRole) + 15)
    )


def test_mime_constant():
    assert MIME_MOD_IDS == "application/x-ddmanager-mod-ids+json"


@pytest.mark.parametrize("origin", list(DragOrigin))
def test_round_trip(origin):
    ids = [ModId("a"), ModId("b c"), ModId("über")]
    md = encode_payload(origin, ids)
    assert md.hasFormat(MIME_MOD_IDS)
    assert md.text() == "a\nb c\nüber"
    assert decode_payload(md) == DragPayload(origin, tuple(ids), os.getpid())


def _mime(body: bytes | None) -> QMimeData:
    md = QMimeData()
    if body is not None:
        md.setData(MIME_MOD_IDS, QByteArray(body))
    return md


def _body(**patch):
    base = {"v": 1, "origin": "load_order", "pid": os.getpid(), "ids": ["a"]}
    base.update(patch)
    return json.dumps(base).encode()


@pytest.mark.parametrize(
    "md",
    [
        None,
        _mime(None),
        _mime(b""),
        _mime(b"{oops"),
        _mime(b"[]"),
        _mime(_body(pid=os.getpid() + 1)),
        _mime(_body(origin="elsewhere")),
        _mime(_body(ids=[])),
        _mime(_body(ids="abc")),
        _mime(json.dumps({"origin": "available"}).encode()),
    ],
    ids=[
        "none",
        "no-format",
        "empty",
        "bad-json",
        "list",
        "foreign-pid",
        "bad-origin",
        "no-ids",
        "ids-not-list",
        "missing-keys",
    ],
)
def test_decode_rejects(md):
    assert decode_payload(md) is None


def test_decode_accepts_a_well_formed_foreign_built_body():
    payload = decode_payload(_mime(_body(origin="available", ids=["x", "y"])))
    assert payload == DragPayload(DragOrigin.AVAILABLE, (ModId("x"), ModId("y")), os.getpid())
