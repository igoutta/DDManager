"""Install/save discovery: parity with legacy paths.py plus the documented fixes."""

from pathlib import Path

import pytest

from src.services.detection import (
    DD_GAME_DIR_NAMES,
    InstallDetector,
    ManualPaths,
    candidate_game_folders,
    candidate_local_mod_folders,
    candidate_mod_folders,
    candidate_workshop_mod_folders,
    companion_mod_folders,
    detect_best_mod_folder,
    discover_save_files,
    first_valid_manual_path,
    gog_game_roots,
    is_steam_cloud_path,
    is_workshop_content_path,
    order_save_candidates,
    parse_appworkshop_acf,
    parse_libraryfolders_vdf,
    steam_install_roots,
    steam_library_roots,
    workshop_id_for_folder,
)
from src.services.environment import DictRegistry, Hive
from tests.services.helpers import acf_text

STEAM_KEY = r"Software\Valve\Steam"
WOW_KEY = r"Software\WOW6432Node\Valve\Steam"
GOG_KEY = r"Software\GOG.com\Games"
GOG_WOW_KEY = r"Software\WOW6432Node\GOG.com\Games"


def dirs(base: Path, *names: str) -> list[Path]:
    made = [base / name for name in names]
    for folder in made:
        folder.mkdir(parents=True, exist_ok=True)
    return made


class CountingRegistry:
    def __init__(self, inner: DictRegistry) -> None:
        self.inner = inner
        self.log: list[tuple[str, Hive, str, str]] = []

    def read_value(self, hive: Hive, key: str, name: str) -> str | None:
        self.log.append(("value", hive, key.casefold(), name.casefold()))
        return self.inner.read_value(hive, key, name)

    def subkeys(self, hive: Hive, key: str) -> list[str]:
        self.log.append(("subkeys", hive, key.casefold(), ""))
        return self.inner.subkeys(hive, key)


# ------------------------------------------------------------------ steam roots


def test_windows_steam_roots_follow_the_legacy_order(fake_env, tmp_path: Path) -> None:
    a, b, c, d, pf86, pf = dirs(tmp_path, "a", "b", "c", "d", "pf86/Steam", "pf/Steam")
    registry = DictRegistry(
        values={
            (Hive.HKCU, STEAM_KEY, "SteamPath"): str(a),
            (Hive.HKCU, STEAM_KEY, "InstallPath"): str(b),
            (Hive.HKLM, STEAM_KEY, "InstallPath"): str(c),
            (Hive.HKLM, WOW_KEY, "InstallPath"): str(d),
        }
    )
    env = fake_env(
        env={"PROGRAMFILES(X86)": str(tmp_path / "pf86"), "PROGRAMFILES": str(tmp_path / "pf")},
        registry=registry,
    )
    assert steam_install_roots(env)[:6] == [a, b, c, d, pf86, pf]


def test_steam_roots_skip_missing_dirs_and_dedupe_keeping_order(fake_env, tmp_path: Path) -> None:
    a, b = dirs(tmp_path, "a", "b")
    registry = DictRegistry(
        values={
            (Hive.HKCU, STEAM_KEY, "SteamPath"): str(a) + "/",
            (Hive.HKCU, STEAM_KEY, "InstallPath"): str(tmp_path / "missing"),
            (Hive.HKLM, STEAM_KEY, "InstallPath"): str(b),
            (Hive.HKLM, WOW_KEY, "InstallPath"): str(a),
        }
    )
    roots = steam_install_roots(fake_env(registry=registry))[:2]
    assert [r.absolute() for r in roots] == [a.absolute(), b.absolute()]


def test_registry_keys_are_case_insensitive(fake_env, tmp_path: Path) -> None:
    (a,) = dirs(tmp_path, "a")
    registry = DictRegistry(values={(Hive.HKCU, STEAM_KEY.upper(), "SteamPath"): str(a)})
    assert steam_install_roots(fake_env(registry=registry))[0] == a


def test_linux_steam_roots(fake_env, tmp_path: Path) -> None:
    home = tmp_path / "home"
    flatpak = home / ".var" / "app" / "com.valvesoftware.Steam"
    expected = [
        home / ".steam" / "steam",
        home / ".steam" / "root",
        home / ".local" / "share" / "Steam",
        flatpak / ".local" / "share" / "Steam",
        flatpak / "data" / "Steam",
    ]
    for folder in expected:
        folder.mkdir(parents=True)
    assert steam_install_roots(fake_env("linux", home=home)) == expected


def test_darwin_steam_root(fake_env, tmp_path: Path) -> None:
    home = tmp_path / "home"
    root = home / "Library" / "Application Support" / "Steam"
    root.mkdir(parents=True)
    assert steam_install_roots(fake_env("darwin", home=home)) == [root]


# ------------------------------------------------------------------ vdf / acf / workshop


def test_vdf_paths_are_unescaped_in_order() -> None:
    text = (
        '"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"C:\\\\Program Files (x86)\\\\Steam"\n'
        '\t\t"label"\t\t""\n\t}\n\t"1"\n\t{\n\t\t"path"\t\t"D:\\\\SteamLibrary"\n\t}\n}\n'
    )
    assert parse_libraryfolders_vdf(text) == [r"C:\Program Files (x86)\Steam", r"D:\SteamLibrary"]
    assert parse_libraryfolders_vdf("") == []
    assert parse_libraryfolders_vdf('"apath" "x"') == []


def test_steam_library_roots_add_vdf_libraries(make_steam_root, tmp_path: Path) -> None:
    tree = make_steam_root(tmp_path, libraries=("lib2", "lib3"))
    assert steam_library_roots([tree.root]) == [tree.root, *tree.libraries]


def test_steam_library_roots_skip_missing_and_duplicates(tmp_path: Path) -> None:
    root, other = dirs(tmp_path, "root", "other")
    (root / "steamapps").mkdir()
    vdf = f'"path" "{str(root).replace(chr(92), chr(92) * 2)}"\n"path" "{tmp_path / "nope"}"'
    (root / "steamapps" / "libraryfolders.vdf").write_text(vdf, "utf-8")
    assert steam_library_roots([root, other]) == [root, other]


def test_acf_first_occurrence_wins() -> None:
    text = (
        '"AppWorkshop"\n{\n"WorkshopItemsInstalled"\n{\n"111"\n{\n"size" "1"\n'
        '"timeupdated" "1700000001"\n}\n"222"\n{\n"timeupdated" "1700000002"\n}\n}\n'
        '"WorkshopItemDetails"\n{\n"111"\n{\n"timeupdated" "1999999999"\n}\n}\n}\n'
    )
    assert parse_appworkshop_acf(text) == {"111": "1700000001", "222": "1700000002"}
    assert parse_appworkshop_acf(acf_text({"5": "9"})) == {"5": "9"}
    assert parse_appworkshop_acf("") == {}


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("C:/Steam/steamapps/workshop/content/262060", True),
        ("C:/Steam/steamapps/workshop/content/262060/1234567", True),
        ("C:/Steam/SteamApps/Workshop/Content/262060/x", True),
        ("C:/Steam/steamapps/workshop/content/2620601", False),
        ("C:/Steam/steamapps/workshop/content/2620601/1234567", False),
        ("C:/Steam/steamapps/workshop/content/1", False),
        ("C:/mysteamapps/workshop/content/262060", False),
        ("C:/Games/DarkestDungeon/mods/x", False),
    ],
)
def test_workshop_path_is_an_exact_segment_match(path: str, expected: bool) -> None:
    assert is_workshop_content_path(Path(path)) is expected


def test_workshop_path_other_app_id() -> None:
    path = Path("C:/Steam/steamapps/workshop/content/42/x")
    assert is_workshop_content_path(path, "42") is True
    assert is_workshop_content_path(path) is False


@pytest.mark.parametrize(
    ("folder", "under", "expected"),
    [
        ("1234567890", True, "1234567890"),
        ("1234567890", False, ""),
        ("12345_mod", True, ""),
        ("1234567_mod", True, "1234567"),
        ("0001_1234567_mod", True, "1234567"),
        ("mod_1234567", True, "1234567"),
        ("a_b_1234567", True, ""),
        ("plain_name", True, ""),
        ("1234567_mod", False, ""),
    ],
)
def test_workshop_id_for_folder(folder: str, under: bool, expected: str) -> None:
    path = Path("C:/Steam/steamapps/workshop/content/262060") / folder
    assert workshop_id_for_folder(path, under_workshop=under) == expected


# ------------------------------------------------------------------ gog / candidates


def test_gog_filter_keeps_darkest_dungeon_one_only(fake_env, tmp_path: Path) -> None:
    one, two, bare, other = dirs(tmp_path, "gog1", "gog2", "DarkestDungeon", "other/Thing")
    subkeys = {
        (Hive.HKLM, GOG_KEY): ["1", "2", "3", "4"],
        (Hive.HKLM, GOG_WOW_KEY): [],
    }
    values: dict[tuple[Hive, str, str], str] = {}
    for sub, path, name in (
        ("1", one, "Darkest Dungeon"),
        ("2", two, "Darkest Dungeon II"),
        ("3", bare, ""),
        ("4", other, "Some Other Game"),
    ):
        values[(Hive.HKLM, rf"{GOG_KEY}\{sub}", "path")] = str(path)
        if name:
            values[(Hive.HKLM, rf"{GOG_KEY}\{sub}", "gameName")] = name
    env = fake_env(registry=DictRegistry(values=values, subkeys=subkeys))
    assert gog_game_roots(env)[:2] == [one, bare]
    assert "DarkestDungeon" in DD_GAME_DIR_NAMES


def test_gog_roots_are_windows_only(fake_env, tmp_path: Path) -> None:
    (one,) = dirs(tmp_path, "gog1")
    registry = DictRegistry(
        values={(Hive.HKLM, rf"{GOG_KEY}\1", "path"): str(one)},
        subkeys={(Hive.HKLM, GOG_KEY): ["1"]},
    )
    assert gog_game_roots(fake_env("linux", registry=registry)) == []


def test_candidate_folders(tmp_path: Path) -> None:
    lib1, lib2, gog = dirs(tmp_path, "lib1", "lib2", "gog")
    steam_game, spaced = (
        dirs(lib1, "steamapps/common/DarkestDungeon")[0],
        dirs(lib2, "steamapps/common/Darkest Dungeon")[0],
    )
    assert candidate_game_folders([lib1, lib2], [gog, tmp_path / "gone"]) == [
        steam_game,
        spaced,
        gog,
    ]
    (steam_game / "mods").mkdir()
    (gog / "mods").mkdir()
    assert candidate_local_mod_folders([steam_game, spaced, gog]) == [
        steam_game / "mods",
        gog / "mods",
    ]
    (lib2 / "steamapps" / "workshop" / "content" / "262060").mkdir(parents=True)
    assert candidate_workshop_mod_folders([lib1, lib2]) == [
        lib2 / "steamapps" / "workshop" / "content" / "262060"
    ]


def test_first_valid_manual_path(tmp_path: Path) -> None:
    manual, cand = dirs(tmp_path, "manual", "cand")
    assert first_valid_manual_path(manual, [cand]) == manual
    assert first_valid_manual_path(tmp_path / "gone", [cand]) == cand
    assert first_valid_manual_path(None, [cand]) == cand
    assert first_valid_manual_path(None, []) is None


def test_candidate_mod_folders_and_best(tmp_path: Path) -> None:
    current, workshop, local, empty = dirs(tmp_path, "cur", "ws", "loc", "empty")
    dirs(current, "m1")
    dirs(workshop, "w1", "w2", "w3")
    dirs(local, "l1", "l2")
    (workshop / "file.txt").write_text("x", "utf-8")
    assert candidate_mod_folders(current, [workshop, empty, workshop], [local]) == [
        current,
        workshop,
        local,
    ]
    assert candidate_mod_folders(None, [workshop], [local, tmp_path / "gone"]) == [workshop, local]
    assert detect_best_mod_folder(None, [local, workshop]) == workshop
    assert detect_best_mod_folder(empty, [workshop]) == empty
    assert detect_best_mod_folder(tmp_path / "gone", [local, workshop]) == workshop
    assert not detect_best_mod_folder(None, [])


def test_companion_roots_order_and_primary_exclusion(tmp_path: Path) -> None:
    lib1, lib2, gog = dirs(tmp_path, "lib1", "lib2", "gog")
    ws1, ws2 = (lib / "steamapps" / "workshop" / "content" / "262060" for lib in (lib1, lib2))
    mods1, mods2 = (
        lib / "steamapps" / "common" / "DarkestDungeon" / "mods" for lib in (lib1, lib2)
    )
    spaced = lib2 / "steamapps" / "common" / "Darkest Dungeon" / "mods"
    for folder in (ws1, ws2, mods1, mods2, spaced, gog / "mods"):
        folder.mkdir(parents=True)
    result = companion_mod_folders(ws1, [lib1, lib2], [lib1 / "steamapps" / "common" / "x", gog])
    assert result == [mods1, ws2, mods2, spaced, gog / "mods"]
    assert companion_mod_folders(None, [lib1], [])[0] == ws1


# ------------------------------------------------------------------ saves


def save_at(folder: Path, name: str = "persist.game.json") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / name
    target.write_bytes(b"x")
    return target


def test_windows_saves_from_userdata_and_documents_only_exact_filename(
    fake_env, make_steam_root, tmp_path: Path
) -> None:
    tree = make_steam_root(tmp_path, userdata=("111", "222"))
    docs = tmp_path / "docs"
    local = save_at(docs / "Darkest" / "profile_3")
    save_at(docs / "Darkest" / "profile_3", "persist.game.backup.20240101-000000.json")
    save_at(docs / "Darkest" / "profile_3", "persist.game.decoded.json")
    env = fake_env(known_documents_dir=docs)
    found = discover_save_files(env, [tree.root], [tree.root])
    assert set(found) == {*tree.saves, local}
    assert not set(found) & set(tree.decoys)
    assert found[-1] == local


def test_linux_saves_from_compatdata_and_local_share(
    fake_env, make_steam_root, tmp_path: Path
) -> None:
    tree = make_steam_root(tmp_path)
    compat = (
        tree.root / "steamapps" / "compatdata" / "262060" / "pfx" / "drive_c" / "users"
        / "steamuser" / "Documents" / "Darkest" / "profile_0"
    )  # fmt: skip
    wine = save_at(compat)
    home = tmp_path / "home"
    native = save_at(home / ".local" / "share" / "Red Hook Studios" / "Darkest" / "profile_1")
    found = discover_save_files(fake_env("linux", home=home), [tree.root], [tree.root])
    assert found == [wine, native]


def test_darwin_saves(fake_env, tmp_path: Path) -> None:
    home = tmp_path / "home"
    mac = save_at(home / "Library" / "Application Support" / "Red Hook Studios" / "Darkest" / "p0")
    assert discover_save_files(fake_env("darwin", home=home), [], []) == [mac]


def test_order_save_candidates(tmp_path: Path) -> None:
    a, b, c = (save_at(tmp_path / name) for name in "abc")
    missing = tmp_path / "gone" / "persist.game.json"
    assert order_save_candidates(b, a, [a, c, b, missing]) == [b, a, c]
    assert order_save_candidates(None, None, [c, missing]) == [c]
    assert order_save_candidates(missing, a, []) == [a]


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("C:/Steam/userdata/123456/262060/remote/profile_0/persist.game.json", True),
        ("C:/Steam/userdata/abc/262060/remote/persist.game.json", False),
        ("C:/Steam/userdata/123/262061/remote/persist.game.json", False),
        ("C:/Steam/userdata/123/262060/local/persist.game.json", False),
        ("C:/Users/me/Documents/Darkest/profile_0/persist.game.json", False),
    ],
)
def test_is_steam_cloud_path(path: str, expected: bool) -> None:
    assert is_steam_cloud_path(Path(path)) is expected


# ------------------------------------------------------------------ InstallDetector


@pytest.fixture
def steam_world(fake_env, make_steam_root, tmp_path: Path):
    """A hermetic linux world (the real host Steam folder must never leak into the result)."""
    home = tmp_path / "home"
    share = home / ".local" / "share"
    share.mkdir(parents=True)
    tree = make_steam_root(
        share, libraries=("lib2",), workshop_ids=("1111111", "2222222"), userdata=("9",)
    )
    lib2_ws = tree.libraries[0] / "steamapps" / "workshop" / "content" / "262060"
    (lib2_ws / "3333333").mkdir(parents=True)
    lib2_acf = tree.libraries[0] / "steamapps" / "workshop" / "appworkshop_262060.acf"
    lib2_acf.write_text(acf_text({"3333333": "5"}), "utf-8")
    return tree, lib2_ws, lib2_acf, fake_env("linux", home=home)


def test_detect_builds_the_snapshot_in_legacy_order(steam_world) -> None:
    tree, lib2_ws, lib2_acf, env = steam_world
    snap = InstallDetector(env).detect(ManualPaths(), None)
    assert snap.steam_roots[0] == tree.root
    assert snap.libraries == (tree.root, tree.libraries[0])
    assert snap.game_roots == (tree.game_dir,)
    assert snap.local_mod_dirs == (tree.game_dir / "mods",)
    assert snap.workshop_dirs == (tree.workshop_dir, lib2_ws)
    assert snap.primary_mods_dir == tree.workshop_dir
    assert snap.mod_roots == (tree.workshop_dir, tree.game_dir / "mods", lib2_ws)
    assert snap.acf_files == (tree.acf_file, lib2_acf)
    assert snap.save_files == tree.saves


def test_detect_reads_each_registry_value_once(fake_env, make_steam_root, tmp_path: Path) -> None:
    tree = make_steam_root(tmp_path, workshop_ids=("1111111",), userdata=("9",))
    registry = CountingRegistry(
        DictRegistry(values={(Hive.HKCU, STEAM_KEY, "SteamPath"): str(tree.root)})
    )
    snap = InstallDetector(fake_env(registry=registry)).detect(ManualPaths(), tree.workshop_dir)
    assert tree.root in snap.steam_roots
    assert tree.saves[0] in snap.save_files
    assert registry.log
    assert len(registry.log) == len(set(registry.log))


def test_current_valid_folder_wins_and_missing_one_falls_back(steam_world, tmp_path: Path) -> None:
    tree, _, _, env = steam_world
    (current,) = dirs(tmp_path, "my_mods")
    detector = InstallDetector(env)
    assert detector.detect(ManualPaths(), current).primary_mods_dir == current
    gone = tmp_path / "gone"
    assert detector.detect(ManualPaths(), gone).primary_mods_dir == tree.workshop_dir


def test_manual_workshop_folder_with_most_mods_becomes_primary(steam_world, tmp_path: Path) -> None:
    _, _, _, env = steam_world
    (manual,) = dirs(tmp_path, "manual_ws")
    dirs(manual, "a", "b", "c", "d")
    snap = InstallDetector(env).detect(ManualPaths(workshop_mods=manual), None)
    assert snap.primary_mods_dir == manual
    assert snap.mod_roots[0] == manual
