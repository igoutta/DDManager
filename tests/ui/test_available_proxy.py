"""AvailableModsModel + AvailableFilterProxy."""

import pytest
from PySide6.QtCore import QModelIndex, Qt

from src.core.display import sort_key
from src.core.ids import ModId
from src.ui.models.available_model import AvailableModsModel
from src.ui.models.available_proxy import AvailableFilterProxy
from src.ui.models.roles import DragOrigin, Role, decode_payload
from tests.support.factories import local_mod
from tests.ui.helpers import build, make_row, make_rows


@pytest.fixture
def stack(qtbot, thumbs, translator):
    model = build(AvailableModsModel, thumbs=thumbs, translator=translator)
    proxy = build(AvailableFilterProxy)
    proxy.setSourceModel(model)
    return model, proxy


def shown(proxy):
    return [proxy.index(i, 0).data(Role.MOD_ID) for i in range(proxy.rowCount())]


def catalog_rows():
    return [
        make_row(
            "chorus",
            title="The Chorus",
            tier_id="class",
            source_id="steam_workshop",
            enabled=False,
            search_blob="the chorus class steam",
        ),
        make_row(
            "wayfarer",
            title="Superior Wayfarer",
            tier_id="class",
            source_id="local_folder",
            enabled=True,
            search_blob="superior wayfarer class local",
        ),
        make_row(
            "ui_mod",
            title="Better UI",
            tier_id="ui",
            source_id="steam_workshop",
            enabled=False,
            search_blob="better ui steam",
        ),
        make_row(
            "loose",
            title="Straße Mod",
            tier_id="unassigned",
            source_id="local_folder",
            enabled=False,
            search_blob="strasse mod unassigned local",
        ),
    ]


@pytest.mark.parametrize("count", [0, 1, 50])
def test_model_tester(stack, qtmodeltester, count):
    model, proxy = stack
    model.set_rows(make_rows(count))
    proxy.set_show_enabled(True)
    qtmodeltester.check(proxy)
    assert proxy.rowCount() == count


def test_model_tester_on_the_source_after_set_rows_sequences(stack, qtmodeltester):
    model, _ = stack
    pool = make_rows(30)
    for chunk in (pool[:10], pool[5:25], pool[::2], [], pool):
        model.set_rows(chunk)
        qtmodeltester.check(model)
        assert model.rowCount() == len(chunk)


def test_query_is_a_casefolded_token_and(stack):
    model, proxy = stack
    model.set_rows(catalog_rows())
    proxy.set_show_enabled(True)
    proxy.set_query("CHORUS")
    assert shown(proxy) == ["chorus"]
    proxy.set_query("class  LOCAL")
    assert shown(proxy) == ["wayfarer"]
    proxy.set_query("class chorus ui")
    assert shown(proxy) == []
    proxy.set_query("STRAẞE")  # casefold: capital sharp s -> "ss"
    assert shown(proxy) == ["loose"]
    proxy.set_query("   ")
    assert len(shown(proxy)) == 4


def test_tier_and_source_filters(stack):
    model, proxy = stack
    model.set_rows(catalog_rows())
    proxy.set_show_enabled(True)
    proxy.set_tiers(frozenset({"ui", "unassigned"}))
    assert sorted(shown(proxy)) == ["loose", "ui_mod"]
    proxy.set_tiers(frozenset())
    assert len(shown(proxy)) == 4
    proxy.set_sources(frozenset({"steam_workshop"}))
    assert sorted(shown(proxy)) == ["chorus", "ui_mod"]
    proxy.set_tiers(frozenset({"class"}))
    assert shown(proxy) == ["chorus"]


def test_show_enabled_toggle_refilters_without_reset(stack, qtbot):
    model, proxy = stack
    model.set_rows(catalog_rows())
    with qtbot.assertNotEmitted(proxy.modelReset):
        proxy.set_show_enabled(True)
        assert "wayfarer" in shown(proxy)
        proxy.set_show_enabled(False)
        assert "wayfarer" not in shown(proxy)
        assert len(shown(proxy)) == 3


def test_enabling_a_mod_updates_the_proxy_through_data_changed_only(stack, qtbot):
    model, proxy = stack
    model.set_rows(catalog_rows())
    proxy.set_show_enabled(False)
    assert "chorus" in shown(proxy)
    with qtbot.waitSignal(model.dataChanged) as blocker, qtbot.assertNotEmitted(model.modelReset):
        model.set_enabled(["chorus"], True)
    assert Role.ENABLED in blocker.args[2]
    assert "chorus" not in shown(proxy)
    model.set_enabled(["chorus"], False)
    assert "chorus" in shown(proxy)


def test_set_rows_diffs_by_id(stack, qtbot):
    model, _ = stack
    rows = catalog_rows()
    model.set_rows(rows)
    with qtbot.assertNotEmitted(model.modelReset):
        model.set_rows([*rows[1:], make_row("fresh", title="Fresh")])
    assert model.rowCount() == 4


def test_sort_key_role_ignores_a_leading_the(stack):
    model, proxy = stack
    infos = {
        "chorus": local_mod("chorus", title="The Zebra Pack"),
        "alpha": local_mod("alpha", title="Alpha Pack"),
        "mango": local_mod("mango", title="Mango Pack"),
    }
    model.set_rows(
        [
            make_row(
                key,
                title=info.title,
                sort_key=sort_key(info, None),
                search_blob=info.title.casefold(),
                enabled=False,
            )
            for key, info in infos.items()
        ]
    )
    assert proxy.sortRole() == Role.SORT_KEY
    proxy.sort(0, Qt.SortOrder.AscendingOrder)
    assert shown(proxy) == ["alpha", "mango", "chorus"]


def test_drag_from_a_filtered_view_carries_source_ids(stack):
    model, proxy = stack
    model.set_rows(catalog_rows())
    proxy.set_show_enabled(True)
    proxy.set_query("steam")
    indexes = [proxy.index(row, 0) for row in range(proxy.rowCount())]
    payload = decode_payload(proxy.mimeData(indexes))
    assert payload is not None
    assert payload.origin is DragOrigin.AVAILABLE
    assert set(payload.ids) == {"chorus", "ui_mod"}
    assert len(payload.ids) == 2


def test_load_order_drop_requests_disable(stack, qtbot):
    from src.ui.models.roles import encode_payload

    model, _ = stack
    model.set_rows(catalog_rows())
    with qtbot.waitSignal(model.disableRequested) as blocker:
        assert model.dropMimeData(
            encode_payload(DragOrigin.LOAD_ORDER, [ModId("wayfarer")]),
            Qt.DropAction.MoveAction,
            -1,
            0,
            QModelIndex(),
        )
    assert blocker.args == [["wayfarer"]]


def test_check_state_toggle_emits_toggle_requested(stack, qtbot):
    model, _ = stack
    model.set_rows(catalog_rows())
    index = model.index(0, 0)
    assert model.flags(index) & Qt.ItemFlag.ItemIsUserCheckable
    with qtbot.waitSignal(model.toggleRequested) as blocker:
        model.setData(index, Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
    assert blocker.args == [["chorus"], True]
