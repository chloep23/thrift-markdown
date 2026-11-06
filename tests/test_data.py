"""The committed inventory, held to the boundaries it exists to carry, and to the prices worked
out by hand.

EXPECTED and EXPECTED_NEXT below were derived on paper from the rules in the README, not read
out of either implementation. They are what keeps a bug both implementations share from passing:
the plugin's Decimal arithmetic, the verifier's whole-cent arithmetic and this table all have to
agree, and the table had no author in common with either.
"""

from __future__ import annotations

import json

import pytest
from helpers import BAD_COLOR, FIXTURES, INVENTORY, NEXT_DAY

import verifier.rules as checked

STORE = json.loads((FIXTURES / INVENTORY).read_text())
ITEMS = STORE["items"]
NEXT = json.loads((FIXTURES / NEXT_DAY).read_text())

# id -> (status, price) on day 49, when the colour of the week is pink.
#
#  id   colour  original  tagged  age  age%  pink?  taken  why
#  t01  blue      12.00     36     13    0%    no     0%   the last day before the first markdown
#  t02  blue      12.00     35     14   25%    no    25%   the first day of the 25% band
#  t03  green     20.00      8     41   50%    no    50%   the last day before it is pulled
#  t04  green     20.00      7     42     -    no      -   pulled
#  t05  white      6.50     49      0    0%    no     0%   tagged on the query day
#  t06  pink      18.00      4     45     -   yes      -   pulled, and the week's colour: still pulled
#  t07  pink      15.00     19     30   50%   yes    50%   a tie, so the colour is what the status says
#  t08  pink      24.00     29     20   25%   yes    50%   the colour beats the age
#  t09  yellow     1.90     31     18   25%    no    25%   1.90 x 0.75 = 1.4250, half up to 1.43
#  t10  orange     0.80     14     35   50%    no    50%   0.40 is under the floor, so 0.50
#  t11  pink       0.25     47      2    0%   yes    50%   already under the floor, so it keeps 0.25
#  t12  yellow     9.99     43      6    0%    no     0%   full price
EXPECTED = {
    "t01": ("FULL_PRICE", "12.00"),
    "t02": ("MARKED_DOWN", "9.00"),
    "t03": ("MARKED_DOWN", "10.00"),
    "t04": ("PULLED", None),
    "t05": ("FULL_PRICE", "6.50"),
    "t06": ("PULLED", None),
    "t07": ("COLOR_OF_THE_WEEK", "7.50"),
    "t08": ("COLOR_OF_THE_WEEK", "12.00"),
    "t09": ("MARKED_DOWN", "1.43"),
    "t10": ("MARKED_DOWN", "0.50"),
    "t11": ("COLOR_OF_THE_WEEK", "0.25"),
    "t12": ("FULL_PRICE", "9.99"),
}
# The same items one day later, on day 50. Day 49 ends week 6 and day 50 opens week 7, so the
# colour of the week moves from pink to yellow and eight of the twelve lines change.
EXPECTED_NEXT = {
    "t01": ("MARKED_DOWN", "9.00"),      # age 14: into the 25% band
    "t02": ("MARKED_DOWN", "9.00"),      # age 15
    "t03": ("PULLED", None),             # age 42: pulled a day later than t04
    "t04": ("PULLED", None),             # age 43
    "t05": ("FULL_PRICE", "6.50"),       # age 1
    "t06": ("PULLED", None),             # age 46, and no longer the week's colour either
    "t07": ("MARKED_DOWN", "7.50"),      # pink is over: the age's 50% now, same price
    "t08": ("MARKED_DOWN", "18.00"),     # pink is over: 25% by age, 24.00 x 0.75
    "t09": ("COLOR_OF_THE_WEEK", "0.95"),  # yellow now: 50% beats its 25%, 1.90 x 0.50
    "t10": ("MARKED_DOWN", "0.50"),      # still under the floor
    "t11": ("FULL_PRICE", "0.25"),       # pink is over, and age 3 takes nothing
    "t12": ("COLOR_OF_THE_WEEK", "5.00"),  # yellow now: 9.99 x 0.50 = 4.995, half up to 5.00
}
# What age_markdown gives on day 49: it never looks at the colour, so t07, t08 and t11 are wrong.
AGE_ONLY_WRONG = ("t07", "t08", "t11")


def lines_of(data):
    """The verifier's own reading of a parsed inventory, as {id: (status, price)}."""
    read, problem = checked.parse_inventory(data)
    assert problem is None, problem
    store, items = read
    return {item: (status, price) for item, status, price in checked.price_lines(store, items)}


def test_about_twelve_items_so_one_report_call_carries_them() -> None:
    assert len(ITEMS) == 12


def test_the_day_49_prices_are_the_ones_worked_out_by_hand() -> None:
    assert lines_of(STORE) == EXPECTED


def test_the_day_50_prices_are_the_ones_worked_out_by_hand() -> None:
    assert lines_of(NEXT) == EXPECTED_NEXT


def test_every_status_appears_in_the_committed_inventory() -> None:
    assert {status for status, _ in EXPECTED.values()} == set(checked.STATUSES)


def test_every_id_is_unique_and_well_formed() -> None:
    names = [item["id"] for item in ITEMS]
    assert len(set(names)) == len(names)
    assert all(set(name) <= checked.ID for name in names)


def test_every_price_is_a_two_place_decimal_string() -> None:
    assert all(checked.MONEY.fullmatch(item["price"]) for item in ITEMS)


def test_nothing_is_tagged_after_the_query_day() -> None:
    assert all(1 <= item["tagged"] <= STORE["query_day"] for item in ITEMS)


def test_the_next_day_file_is_the_same_items_one_day_later() -> None:
    """The week boundary is the only difference, which is what makes the two comparable."""
    assert NEXT["items"] == ITEMS
    assert NEXT["markdown"] == STORE["markdown"]
    assert NEXT["rotation"] == STORE["rotation"]
    assert NEXT["query_day"] == STORE["query_day"] + 1


def test_the_two_days_fall_either_side_of_a_week_boundary() -> None:
    assert checked.week_of(STORE["query_day"]) + 1 == checked.week_of(NEXT["query_day"])
    assert checked.color_of_the_week(checked.parse_inventory(STORE)[0][0]) == "pink"
    assert checked.color_of_the_week(checked.parse_inventory(NEXT)[0][0]) == "yellow"


@pytest.mark.parametrize(
    ("item", "age"),
    [("t01", 13), ("t02", 14), ("t03", 41), ("t04", 42), ("t05", 0)],
)
def test_the_age_boundaries_are_in_the_inventory(item: str, age: int) -> None:
    tagged = next(entry["tagged"] for entry in ITEMS if entry["id"] == item)
    assert STORE["query_day"] - tagged == age


def test_one_item_is_both_fifty_off_by_age_and_the_colour_of_the_week() -> None:
    """A tie, which rule 3 settles in the colour's favour."""
    entry = next(item for item in ITEMS if item["id"] == "t07")
    assert STORE["query_day"] - entry["tagged"] >= 28
    assert entry["color"] == "pink"
    assert EXPECTED["t07"][0] == "COLOR_OF_THE_WEEK"


def test_one_pulled_item_wears_the_colour_of_the_week() -> None:
    entry = next(item for item in ITEMS if item["id"] == "t06")
    assert entry["color"] == "pink"
    assert EXPECTED["t06"] == ("PULLED", None)


def test_one_price_rounds_at_exactly_half_a_cent() -> None:
    """1.90 with 25% off is 1.4250 exactly: half up gives 1.43, half even would give 1.42."""
    assert checked.marked(190, 25, 50) == 143
    assert EXPECTED["t09"][1] == "1.43"


def test_one_discount_would_fall_below_the_floor_and_one_item_starts_below_it() -> None:
    assert checked.marked(80, 50, 50) == 50, "0.40 is raised to the 0.50 floor"
    assert checked.marked(25, 50, 50) == 25, "an item already under the floor keeps its price"
    assert EXPECTED["t10"][1] == "0.50"
    assert EXPECTED["t11"][1] == "0.25"


def test_age_markdown_is_wrong_for_exactly_the_colour_of_the_week_items() -> None:
    """The distractor's cost, stated: trusting it scores 9 of 12."""
    read, problem = checked.parse_inventory(STORE)
    assert problem is None
    store, items = read
    aged = {item: (status, price) for item, status, price in checked.price_lines_by_age(store, items)}
    wrong = sorted(item for item in aged if aged[item] != EXPECTED[item])
    assert wrong == sorted(AGE_ONLY_WRONG)
    assert all(status != "COLOR_OF_THE_WEEK" for status, _ in aged.values())


def test_the_invalid_fixtures_are_rejected_for_the_reasons_they_exist_for() -> None:
    future = json.loads((FIXTURES / "inventory_future.json").read_text())
    assert "after the query day" in checked.parse_inventory(future)[1]
    bad = json.loads((FIXTURES / BAD_COLOR).read_text())
    assert "not a colour the store stocks" in checked.parse_inventory(bad)[1]


def test_the_rotation_is_shorter_than_the_colour_list() -> None:
    """A stocked colour that is never the colour of the week, so an item can be plainly full price."""
    assert set(STORE["rotation"]) < set(STORE["colors"])
    assert "white" not in STORE["rotation"]


# ----- The manifest's own budget -----


def test_the_task_instructions_stay_inside_the_budget_that_works() -> None:
    """Instruction length is not free. An earlier plugin of this set regressed from passing to
    failing purely by growing its instructions a third longer, each added sentence taking from
    the reasoning the agent had left: every one of these numbers was measured, not guessed.
    2,500 characters is the ceiling this task was validated under.
    """
    manifest = (FIXTURES.parents[1] / "nanoagent.yaml").read_text(encoding="utf-8")
    instructions = manifest[manifest.index("instructions: |-") + len("instructions: |-") :].strip()
    assert 0 < len(instructions) <= 2500, f"the instructions run to {len(instructions)} characters"


def test_the_instructions_prescribe_the_split_report_that_fits_the_budget() -> None:
    """Four calls, at most six items a call. Twelve in one step overruns the host's 2,048-token
    output budget often enough to matter: 7 runs of 9 submitted that way against 39 of 40 split.
    A reply with no tool call ends the run, and the harness has no retry for it."""
    manifest = (FIXTURES.parents[1] / "nanoagent.yaml").read_text(encoding="utf-8")
    assert "Four tool calls" in manifest
    assert "never price more than six items in one step" in manifest.lower()
