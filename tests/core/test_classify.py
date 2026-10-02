"""The legacy category classifier over ``ModInfo`` (src/core/classify.py).

Contract: ``category_scores`` ports categories.py:134-229 (``auto_category_scores``) with the same
weights and ignore list, reading tags from ``info.tags`` (the legacy tag list), directories from
``top_level_dirs`` / ``subdirs_of("heroes")`` and the title bits from key, save name,
``display_name(info, nickname)`` and title; ``suggest_category`` ports 232-253 (best >= 4,
Dungeons wins ties, Class wins strictly, otherwise a margin of 2).

Parity: every ``modding/*`` sample and every synthetic folder of tests/support/mod_facts.py
against ``categories.suggested_category_for_mod`` with the legacy callbacks (live) and against the
committed goldens under tests/golden/classify (no oracle needed).
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from src.core.categories import DEFAULT_CATEGORIES
from src.core.classify import category_scores, suggest_category
from src.core.identity import derive_mod_info
from src.core.model import ModInfo
from tests.support import factories
from tests.support import mod_facts as mf
from tools.legacy_oracle import LegacyOracle

GOLDEN_FILE = Path(__file__).absolute().parents[1] / "golden" / "classify" / "cases.json"

_local = datetime.now(UTC).astimezone().tzinfo
assert _local is not None
LOCAL_TZ = _local


def _load_golden() -> dict[str, Any]:
    if not GOLDEN_FILE.is_file():
        pytest.fail(
            f"{GOLDEN_FILE} is missing: the classify goldens are the parity proof that outlives the"
            " legacy oracle; restore them from git or run tools/regen_goldens.py",
            pytrace=False,
        )
    return json.loads(GOLDEN_FILE.read_text("utf-8"))


GOLDEN = _load_golden()


def _mod(
    key: str, *, title: str | None = None, tags: tuple[str, ...] = (), files: tuple[str, ...] = ()
) -> ModInfo:
    return factories.local_mod(key, title=title, tags=tags, files=files)


def _nonzero(scores: dict[str, int]) -> dict[str, int]:
    return {k: v for k, v in scores.items() if v}


# ----------------------------------------------------------------- scores (contract)


def test_scores_cover_every_builtin_category_and_start_at_zero() -> None:
    scores = category_scores(_mod("plain", title="Plain"))
    assert list(scores) == list(DEFAULT_CATEGORIES)
    assert set(scores.values()) == {0}


def test_tag_rules_add_four_per_matching_tag_and_ignore_the_noise_list() -> None:
    assert _nonzero(category_scores(_mod("m", title="M", tags=("Patch", "Compatibility")))) == {
        "Class Patch": 8
    }
    assert _nonzero(category_scores(_mod("m", title="M", tags=("Character Mod", "Class Mod")))) == {
        "Class": 8
    }
    assert (
        _nonzero(
            category_scores(
                _mod("m", title="M", tags=("english", "cc", "Pets Compatible", "S-Purple"))
            )
        )
        == {}
    )
    assert (
        _nonzero(category_scores(_mod("m", title="M", tags=("New Class support hive mind",)))) == {}
    )  # pseudo tag never matches
    assert _nonzero(category_scores(_mod("m", title="M", tags=("UI", "QoL", "tooltips")))) == {
        "UI": 12
    }
    assert _nonzero(
        category_scores(_mod("m", title="M", tags=("Butcher's Circus", "Farmstead")))
    ) == {"Dungeons": 8}


def test_directory_rules() -> None:
    assert _nonzero(category_scores(_mod("m", title="M", files=("trinkets/x.json",)))) == {
        "Trinkets": 4
    }
    assert _nonzero(category_scores(_mod("m", title="M", files=("monsters/beast/a",)))) == {
        "Enemies": 6
    }
    assert _nonzero(category_scores(_mod("m", title="M", files=("dungeons/ruins/a",)))) == {
        "Dungeons": 5
    }
    assert _nonzero(category_scores(_mod("m", title="M", files=("quirks/a",)))) == {"Quirks": 5}
    assert _nonzero(category_scores(_mod("m", title="M", files=("diseases/a", "quirks/a")))) == {
        "Quirks": 5
    }
    assert _nonzero(
        category_scores(_mod("m", title="M", files=("panels/a", "overlays/b", "fe_flow/c")))
    ) == {"UI": 4}
    assert _nonzero(category_scores(_mod("m", title="M", files=("upgrades/a",)))) == {}
    with_tag = _mod("m", title="M", tags=("New District",), files=("upgrades/a",))
    assert _nonzero(category_scores(with_tag)) == {"Districts": 9}


def test_heroes_branch_rules() -> None:
    hero = ("heroes/x/x.info.darkest",)
    assert _nonzero(category_scores(_mod("m", title="M", files=hero))) == {"Class": 6}
    new_class = _mod("m", title="M", tags=("New Class",), files=hero)
    assert _nonzero(category_scores(new_class)) == {"Class": 12}
    skin = _mod("m", title="M", tags=("New Class", "Skin"), files=hero)
    assert _nonzero(category_scores(skin)) == {"Class": 4, "Skins": 11}
    patch = _mod("m", title="Crusader Fix", tags=("New Class",), files=hero)
    assert _nonzero(category_scores(patch)) == {"Class": 4, "Class Patch": 6}
    tweaks = _mod("m", title="M", tags=("Class Tweaks",), files=hero)
    assert _nonzero(category_scores(tweaks)) == {"Class Patch": 11}
    tweaks_with_identity = _mod("m", title="M", tags=("Class Tweaks", "Class Mod"), files=hero)
    assert _nonzero(category_scores(tweaks_with_identity)) == {"Class Patch": 4, "Class": 12}
    empty_heroes = _mod("m", title="M", tags=("New Class",), files=("heroes/readme.txt",))
    assert _nonzero(category_scores(empty_heroes)) == {"Class": 4}  # no child dirs: no heroes bonus


def test_title_bits_come_from_key_save_name_display_name_and_title() -> None:
    assert _nonzero(category_scores(_mod("0001_district_pack", title="Pack"))) == {"Districts": 5}
    assert _nonzero(category_scores(_mod("m", title="Tooltip Fixes"))) == {"UI": 5}
    assert _nonzero(category_scores(_mod("m", title="character_ui"))) == {"UI": 11}
    assert _nonzero(category_scores(_mod("m", title="Roster Size"))) == {"UI": 5}
    assert _nonzero(category_scores(_mod("m", title="Vermintide"))) == {"Dungeons": 6}
    # "ui" is a substring test (categories.py:200): "Ruin" and "Quirk" both hit it
    assert _nonzero(category_scores(_mod("m", title="Smouldering Ruin"))) == {
        "UI": 5,
        "Districts": 6,
    }
    assert _nonzero(category_scores(_mod("m", title="A Monster Mod"))) == {"Enemies": 6}
    assert _nonzero(category_scores(_mod("m", title="Quirk Doctor"))) == {"UI": 5, "Quirks": 6}
    assert _nonzero(category_scores(_mod("m", title="Trinket Skin"))) == {"Trinkets": 2, "Skins": 2}
    assert _nonzero(category_scores(_mod("m", title="Plain"), nickname="Quirky Nick")) == {
        "UI": 5,
        "Quirks": 6,
    }
    assert _nonzero(category_scores(_mod("m", title="Plain"), nickname=None)) == {}


# ----------------------------------------------------------------- suggestion thresholds


def test_suggest_category_thresholds() -> None:
    assert suggest_category(_mod("m", title="M", files=("trinkets/x.json",))) == "Trinkets"
    assert suggest_category(_mod("m", title="M", files=("monsters/beast/a",))) == "Enemies"
    assert suggest_category(_mod("m", title="Skin")) is None  # 2 < 4
    assert suggest_category(_mod("m", title="M")) is None
    assert suggest_category(_mod("m", title="UI Skin")) == "UI"  # 5 vs 2
    assert (
        suggest_category(_mod("m", title="M", tags=("Class", "Skin"))) is None
    )  # Class 4 == Skins 4
    assert (
        suggest_category(_mod("m", title="M", tags=("Class", "Trinket"), files=("heroes/x/a",)))
        == "Class"
    )  # 10 vs 4
    assert (
        suggest_category(_mod("m", title="M", files=("dungeons/a/b", "quirks/c"))) == "Dungeons"
    )  # tie -> Dungeons
    assert (
        suggest_category(_mod("m", title="M", tags=("Trinket", "Class"))) is None
    )  # 4 == 4, neither special
    assert (
        suggest_category(_mod("m", title="M", tags=("Trinket", "Trinkets", "Class"))) == "Trinkets"
    )  # 8 vs 4


def test_suggest_category_margin_rule_exactly() -> None:
    assert (
        suggest_category(_mod("m", title="M", tags=("Trinket", "Monster"), files=("trinkets/x",)))
        == "Trinkets"
    )
    two_apart = _mod("m", title="Trinket Skin", tags=("Trinket",))  # Trinkets 6, Skins 2
    assert suggest_category(two_apart) == "Trinkets"
    four_apart = _mod(
        "m", title="Skin Trinket", tags=("Skin", "Trinket"), files=("trinkets/x",)
    )  # Trinkets 10, Skins 6
    assert suggest_category(four_apart) == "Trinkets"
    assert suggest_category(_mod("m", title="UI", tags=("Trinket",))) is None  # UI 5 vs Trinkets 4
    assert (
        suggest_category(_mod("m", title="Monster Mod", tags=("Trinket",))) == "Enemies"
    )  # 6 vs 4
    assert suggest_category(_mod("m", title="District", tags=("Trinket",))) is None  # 5 vs 4
    assert (
        suggest_category(_mod("m", title="M", tags=("Trinket", "Skin"), files=("panels/a",)))
        is None
    )  # 4,4,4


def test_crusader_patch_sample_is_a_class_patch(sample_mods_dir: Path) -> None:
    info = factories.sample_patch_mod(sample_mods_dir, "crusader_hu_swf_compat")
    scores = category_scores(info)
    assert scores["Class Patch"] == 14 and scores["Class"] == 8
    assert suggest_category(info) == "Class Patch"


# ----------------------------------------------------------------- goldens (no oracle needed)


def _info_for(folder: Path, acf: dict[str, str] | None = None) -> ModInfo:
    return derive_mod_info(mf.snapshot_from_dir(folder, acf=acf), tz=LOCAL_TZ)


def test_golden_is_pinned_and_covers_every_sample(sample_mods_dir: Path) -> None:
    assert GOLDEN["legacy_commit"] == "31e85d6"
    samples = sorted(p.name for p in sample_mods_dir.iterdir() if p.is_dir())
    assert sorted(GOLDEN["samples"]) == samples
    assert set(GOLDEN["synthetic"]) == {spec.id for spec in mf.CASES}


@pytest.mark.parametrize("name", sorted(GOLDEN["samples"]))
def test_sample_classification_matches_golden(sample_mods_dir: Path, name: str) -> None:
    case = GOLDEN["samples"][name]
    folder = sample_mods_dir / name
    assert mf.sample_digest(folder) == case["digest"], "sample mod drifted: regenerate the goldens"
    info = _info_for(folder)
    assert category_scores(info) == case["scores"]
    assert suggest_category(info) == case["suggestion"]


@pytest.fixture(scope="module")
def case_dirs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    return mf.materialize_all(tmp_path_factory.mktemp("classify"))


@pytest.mark.parametrize("case_id", sorted(GOLDEN["synthetic"]))
def test_synthetic_classification_matches_golden(case_dirs: dict[str, Path], case_id: str) -> None:
    case = GOLDEN["synthetic"][case_id]
    spec = mf.spec_by_id(case_id)
    assert spec.digest() == case["spec_digest"], "case spec drifted: regenerate the goldens"
    info = _info_for(case_dirs[case_id], dict(spec.acf))
    assert category_scores(info) == case["scores"]
    assert suggest_category(info) == case["suggestion"]
    for nickname, expected in case["nicknames"].items():
        assert category_scores(info, nickname=nickname) == expected["scores"], nickname
        assert suggest_category(info, nickname=nickname) == expected["suggestion"], nickname


# ----------------------------------------------------------------- live parity vs the pinned oracle


def _legacy_classify(
    legacy: LegacyOracle, manager: Any, mod: str
) -> tuple[dict[str, int], str | None]:
    cat = legacy.module("categories")
    dd2 = legacy.module("dd2")
    manager.current_metadata_for_mod(mod)  # the app always has metadata before classifying
    args = (
        manager.state,
        mod,
        manager.mod_folder_path,
        manager.save_name,
        manager.display_name,
        dd2.parse_xml_file_forgiving,
    )
    return cat.auto_category_scores(*args), cat.suggested_category_for_mod(*args)


@pytest.mark.legacy
def test_samples_match_legacy_classifier(legacy: LegacyOracle, sample_mods_dir: Path) -> None:
    dd2 = legacy.module("dd2")
    folders = {p.name: p for p in sample_mods_dir.iterdir() if p.is_dir()}
    manager = mf.legacy_manager(dd2, folders)
    for name, folder in sorted(folders.items()):
        scores, suggestion = _legacy_classify(legacy, manager, name)
        info = _info_for(folder)
        assert category_scores(info) == scores, name
        assert suggest_category(info) == suggestion, name


@pytest.mark.legacy
@pytest.mark.parametrize("spec", mf.CASES, ids=[s.id for s in mf.CASES])
def test_synthetic_folders_match_legacy_classifier(
    legacy: LegacyOracle, case_dirs: dict[str, Path], spec: mf.ModDirSpec
) -> None:
    dd2 = legacy.module("dd2")
    folder = case_dirs[spec.id]
    manager = mf.legacy_manager(dd2, {spec.folder: folder}, acf=dict(spec.acf))
    info = _info_for(folder, dict(spec.acf))
    scores, suggestion = _legacy_classify(legacy, manager, spec.folder)
    assert category_scores(info) == scores
    assert suggest_category(info) == suggestion
    for nickname in spec.nicknames:
        manager.state["nicknames"][spec.folder] = nickname
        scores, suggestion = _legacy_classify(legacy, manager, spec.folder)
        assert category_scores(info, nickname=nickname) == scores, nickname
        assert suggest_category(info, nickname=nickname) == suggestion, nickname
