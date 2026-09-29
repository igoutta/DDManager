"""Write the two probe mods used to confirm which end of the load order wins conflicts.

See docs/load-order-semantics.md for the protocol. Both mods override the same file
(``campaign/town/buildings/stage_coach/stage_coach.building.json``) with a different base
number of stage-coach recruits, which is visible in town without any other setup.
"""

import argparse
import json
from pathlib import Path

REL_TARGET = "campaign/town/buildings/stage_coach/stage_coach.building.json"

_PROJECT_XML = """<?xml version="1.0" encoding="utf-8"?>
<project>
\t<Title>{title}</Title>
\t<Language>english</Language>
\t<VersionMajor>1</VersionMajor>
\t<VersionMinor>0</VersionMinor>
\t<TargetBuild>0</TargetBuild>
\t<Tags>
\t\t<Tags>Gameplay Tweaks</Tags>
\t</Tags>
	<ItemDescriptionShort>DD Manager probe {letter}: {amount} recruits.</ItemDescriptionShort>
	<ItemDescription>Temporary DD Manager probe mod. Safe to delete.</ItemDescription>
</project>
"""


def _building_json(base_recruits: int) -> str:
    """The stage-coach building definition with a custom base recruit count."""
    upgrades = [{"amount": base_recruits}]
    for code, amount in zip("abcdef", range(base_recruits + 1, base_recruits + 7), strict=True):
        upgrades.append(
            {
                "amount": amount,
                "upgrade_tree_id": "stage_coach.numrecruits",
                "upgrade_requirement_code": code,
            }
        )
    roster = [{"amount": 10}]
    for code, amount in zip("abcdef", (13, 17, 22, 27, 32, 38), strict=True):
        roster.append(
            {
                "amount": amount,
                "upgrade_tree_id": "stage_coach.rostersize",
                "upgrade_requirement_code": code,
            }
        )
    upgraded: list[dict[str, object]] = []
    table = (
        (1, 0.375, 0, 1, 2),
        (2, 0.25, 1, 1, 3),
        (3, 0.1875, 2, 2, 4),
        (4, 0.125, 2, 2, 5),
        (5, 0.0625, 3, 3, 6),
    )
    for (level, chance, quirks, skills, dead_level), code in zip(table, "abcde", strict=True):
        upgraded.append(
            {
                "level": level,
                "chance": chance,
                "number_of_extra_positive_quirks": quirks,
                "number_of_extra_negative_quirks": quirks,
                "number_of_extra_combat_skills": skills,
                "number_of_extra_camping_skills": max(skills, 1),
                "guaranteed_previous_raid_dead_hero_levels": [dead_level],
                "upgrade_tree_id": "stage_coach.upgraded_recruits",
                "upgrade_requirement_code": code,
            }
        )
    doc = {
        "on_start_town_visit_priority": 0,
        "requirements": {"number_of_quests_finished": 0, "highest_dungeon_level": 0},
        "data": {
            "stores": [
                {
                    "id": "hero_recruit",
                    "data": {
                        "first_hero_classes": ["plague_doctor"],
                        "number_of_recruits_upgrades": upgrades,
                        "roster_size_upgrades": roster,
                        "upgraded_recruits_upgrades": upgraded,
                    },
                }
            ]
        },
    }
    return json.dumps(doc, indent="\t") + "\n"


def write_kit(dest: Path) -> list[Path]:
    """Create ``ddm_probe_a`` (4 recruits) and ``ddm_probe_b`` (8 recruits) under ``dest``."""
    written: list[Path] = []
    for letter, amount in (("a", 4), ("b", 8)):
        mod_dir = dest / f"ddm_probe_{letter}"
        target = mod_dir / REL_TARGET
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_building_json(amount), "utf-8")
        title = f"DD Manager Probe {letter.upper()} ({amount} recruits)"
        (mod_dir / "project.xml").write_text(
            _PROJECT_XML.format(title=title, letter=letter.upper(), amount=amount), "utf-8"
        )
        listed = [REL_TARGET, "project.xml"]
        if letter == "b":
            # Deliberately NOT listed in modfiles.txt: tells us whether the game loads
            # files that the manifest does not mention.
            extra = mod_dir / "localization" / "ddm_probe_unlisted.string_table.xml"
            extra.parent.mkdir(parents=True, exist_ok=True)
            extra.write_text(
                '<?xml version="1.0" encoding="utf-8"?>\n<root>\n\t<language id="english">\n'
                '\t\t<entry id="ddm_probe_unlisted">'
                "<![CDATA[DD Manager probe: unlisted file loaded]]></entry>\n"
                "\t</language>\n</root>\n",
                "utf-8",
            )
        (mod_dir / "modfiles.txt").write_text("\n".join(listed) + "\n", "utf-8")
        written.append(mod_dir)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("dest", type=Path, help="folder to write ddm_probe_a and ddm_probe_b into")
    args = parser.parse_args(argv)
    for path in write_kit(args.dest):
        print(path)
    print("Next: see docs/load-order-semantics.md for the launch protocol.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
