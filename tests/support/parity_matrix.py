"""The write_applied parity matrix shared by the differential test, the goldens and the generator.

N (rows) is the number of entries already in the save's applied_ugcs_1_0 block, ``None`` meaning
the block is absent (insert path). M (columns) is the number of entries written. The names cover
every byte-length residue mod 4 and include one non-ASCII local name; all values are readable by
the legacy heuristic scanner (printable ASCII or UTF-8 whose length prefix is not an ASCII digit),
so the pinned oracle is expected to succeed on every cell.
"""

from tests.support.dson_builder import LOCAL, STEAM, Entry, standard_save

N_VALUES: tuple[int | None, ...] = (None, 0, 1, 3, 7)
M_VALUES: tuple[int, ...] = (0, 1, 2, 5, 12)
CASES: tuple[tuple[int | None, int], ...] = tuple((n, m) for n in N_VALUES for m in M_VALUES)

# (N, M) cells where the pinned legacy patcher raises. Any cell listed here must raise in the
# legacy, and any cell not listed must match byte for byte, so a new divergence fails loudly.
EXPECTED_DIVERGENCE: frozenset[tuple[int | None, int]] = frozenset()

_EXISTING: dict[int, tuple[Entry, ...]] = {
    0: (),
    1: (("999", STEAM),),
    3: (("1", STEAM), ("Old Local", LOCAL), ("12345", STEAM)),
    7: (
        ("7", STEAM),
        ("77", STEAM),
        ("777", STEAM),
        ("7777", STEAM),
        ("Legacy Mod", LOCAL),
        ("1234567890123", STEAM),
        ("z" * 33, LOCAL),
    ),
}

# byte lengths: 1, 2, 3, 4, 12 (CJK), 14, 10, 18, 5, 26, 6, 2
_NEW_POOL: tuple[Entry, ...] = (
    ("1", STEAM),
    ("22", STEAM),
    ("333", STEAM),
    ("4444", STEAM),
    ("测试模组", LOCAL),
    ("Local Mod Five", LOCAL),
    ("2861478271", STEAM),
    ("Another Local Mod!", LOCAL),
    ("55555", STEAM),
    ("Yet another local mod name", LOCAL),
    ("666666", STEAM),
    ("Zz", LOCAL),
)


def existing_entries(n: int | None) -> tuple[Entry, ...] | None:
    return None if n is None else _EXISTING[n]


def new_entries(m: int) -> tuple[Entry, ...]:
    if m > len(_NEW_POOL):
        raise ValueError(f"the pool holds {len(_NEW_POOL)} entries, {m} requested")
    return _NEW_POOL[:m]


def build_input(n: int | None) -> bytes:
    return standard_save(existing_entries(n))


def case_id(n: int | None, m: int) -> str:
    return f"N{'none' if n is None else n}_M{m}"


def stub_identities(entries: tuple[Entry, ...]) -> tuple[list[str], dict[str, Entry]]:
    """Folder keys plus the folder -> (name, source) map the legacy stub manager answers with."""
    keys = [f"mod_{k}" for k in range(len(entries))]
    return keys, dict(zip(keys, entries, strict=True))
