"""The price-day verdict: a gold run holds every constraint, and each one fails on its own case
with its own message; plus the per-call checks and a random differential.

The cases are the five a verifier has to decide -- correct, wrong, missing, malformed, and the
boundaries where a plausible price is the wrong one.
"""

from __future__ import annotations

import copy
import json
import random
import shutil
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest
from helpers import BAD_COLOR, FIXTURES, FUTURE, IDS, INVENTORY, NEXT_DAY, Run, failed, stage, unchecked
from slimconfig import build_output, plain_output

import verifier
import verifier.rules as checked
from contract import InventoryOutput, KeyOutput, PriceInput, ReportInput
from plugin import age_markdown, price_key, read_inventory
from plugin.rules import marked as plugin_marked
from plugin.rules import price_all, read_inventory_data
from verifier.task import TEXT

CONSTRAINTS = len(TEXT)
FILES = (INVENTORY, NEXT_DAY)


# ----- Correct -----


@pytest.mark.parametrize("inventory", FILES)
def test_a_gold_run_holds_every_constraint(tmp_path: Path, inventory: str) -> None:
    run = Run(tmp_path, inventory=inventory)
    run.gold()
    found = run.verdict()
    assert found["valid"], found["message"]
    assert found["score"] == 1.0 and found["message"].startswith(f"All {CONSTRAINTS} checks hold")
    assert [entry["ok"] for entry in found["details"]["constraints"]] == [True] * CONSTRAINTS
    assert found["details"]["items"] == len(IDS)
    assert len(json.dumps(found)) < 8000, "the verdict lands in the chat's context: keep it small"


def test_the_week_boundary_changes_the_answer(tmp_path: Path) -> None:
    """The same items one day later: a different colour of the week, a different answer."""
    first = Run(tmp_path / "a", inventory=INVENTORY).gold()
    second = Run(tmp_path / "b", inventory=NEXT_DAY).gold()
    assert first["lines"] != second["lines"]
    changed = [a["item"] for a, b in zip(first["lines"], second["lines"], strict=True) if a != b]
    assert changed == ["t01", "t03", "t07", "t08", "t09", "t11", "t12"], changed


def test_the_reports_carry_one_line_per_item_in_the_file_order(tmp_path: Path) -> None:
    report = Run(tmp_path).gold()
    assert [line["item"] for line in report["lines"]] == IDS


# ----- Wrong -----


def test_a_wrong_price_fails_price_exact_and_costs_one_item(tmp_path: Path) -> None:
    run = Run(tmp_path)
    run.read()
    lines = run.answer()
    lines[1] = {**lines[1], "price": "9.01"}
    run.report(lines)
    found = run.verdict()
    assert failed(found) == ["price-exact"]
    assert "t02 is reported at 9.01, but the rules give 9.00" in found["message"]
    assert found["score"] == pytest.approx(11 / 12)


def test_a_wrong_status_fails_status_exact_even_when_the_price_is_right(tmp_path: Path) -> None:
    """t07 is 50% off by age and the week's colour at once. The price is the same either way, so
    only the status says whether the no-stacking tie was read the right way round."""
    run = Run(tmp_path)
    run.read()
    lines = [{**line, "status": "MARKED_DOWN"} if line["item"] == "t07" else line for line in run.answer()]
    run.report(lines)
    found = run.verdict()
    assert failed(found) == ["status-exact"]
    assert "t07 is reported MARKED_DOWN, but on day 49 it is COLOR_OF_THE_WEEK" in found["message"]
    assert found["score"] == pytest.approx(11 / 12)


def test_trusting_the_age_markdown_tool_costs_the_colour_of_the_week(tmp_path: Path) -> None:
    """age_markdown is honest and is not how the task is solved: copying it straight through
    misprices every item wearing the week's colour."""
    run = Run(tmp_path)
    run.read()
    aged = age_markdown(run.given, run.workspace)
    run.report([{"item": line.item, "status": line.status.value, "price": line.price} for line in aged.lines])
    found = run.verdict()
    assert failed(found) == ["status-exact", "price-exact"]
    assert found["score"] == pytest.approx(9 / 12)
    assert "t07 is reported MARKED_DOWN" in found["message"]


def test_stacking_the_two_discounts_is_wrong(tmp_path: Path) -> None:
    """t08 is 25% off by age and 50% off by colour. Stacking gives 24.00 x 0.75 x 0.50 = 9.00;
    the rules give the larger of the two and nothing more, so 12.00."""
    run = Run(tmp_path)
    run.read()
    lines = [{**line, "price": "9.00"} if line["item"] == "t08" else line for line in run.answer()]
    run.report(lines)
    found = run.verdict()
    assert failed(found) == ["price-exact"]
    assert "t08 is reported at 9.00, but the rules give 12.00" in found["message"]


def test_a_submission_that_is_not_the_saved_report_fails_submitted_as_saved(tmp_path: Path) -> None:
    run = Run(tmp_path)
    report = run.gold()
    changed = copy.deepcopy(report)
    changed["lines"][0]["price"] = "11.00"
    found = run.verdict(changed)
    assert failed(found)[0] == "submitted-as-saved" and found["score"] == 0.0


def test_an_answer_key_that_is_not_the_days_prices_fails_answer_key_right(tmp_path: Path) -> None:
    run = Run(tmp_path)
    report = run.gold()
    key = plain_output(run.key)
    key["lines"][0] = {**key["lines"][0], "price": "11.00"}
    found = run.verdict(report, reference=build_output(key, KeyOutput))
    assert failed(found)[0] == "answer-key-right" and found["score"] == 0.0


def test_an_answer_key_naming_the_wrong_colour_fails_answer_key_right(tmp_path: Path) -> None:
    run = Run(tmp_path)
    report = run.gold()
    key = plain_output(run.key)
    key["color_of_the_week"] = "yellow"
    found = run.verdict(report, reference=build_output(key, KeyOutput))
    assert failed(found) == ["answer-key-right"]
    assert "calls the week's colour 'yellow', not 'pink'" in found["message"]


def test_an_answer_key_for_another_file_fails_answer_key(tmp_path: Path) -> None:
    run = Run(tmp_path)
    report = run.gold()
    stage(tmp_path, NEXT_DAY)
    other = Run(tmp_path, inventory=NEXT_DAY).key
    found = run.verdict(report, reference=other)
    assert failed(found) == ["answer-key"] and found["score"] == 0.0
    assert "read another file than this task names" in found["message"]


# ----- Missing -----


def test_no_answer_key_fails_first_and_scores_zero(tmp_path: Path) -> None:
    run = Run(tmp_path)
    report = run.gold()
    found = run.verdict(report, reference=None)
    assert failed(found)[0] == "answer-key" and found["score"] == 0.0 and "price_key never read" in found["message"]


def test_prices_without_reading_the_inventory_fail_read_inventory(tmp_path: Path) -> None:
    run = Run(tmp_path)
    run.gold()
    (tmp_path / "reports" / run.run / "task.json").unlink()
    found = run.verdict()
    assert failed(found) == ["read-inventory"] and found["score"] == 0.0
    assert "read_inventory was never called" in found["message"]


def test_a_report_that_was_never_saved_fails_report_saved(tmp_path: Path) -> None:
    run = Run(tmp_path)
    report = run.gold()
    (tmp_path / "reports" / run.run / "prices.json").unlink()
    found = run.verdict(report)
    assert failed(found) == ["report-saved"] and unchecked(found) == ["submitted-as-saved"]
    assert "report_prices never saved" in found["message"]


def test_an_unpriced_item_fails_all_items(tmp_path: Path) -> None:
    run = Run(tmp_path)
    run.read()
    run.report(run.answer()[:-1])
    found = run.verdict()
    assert failed(found) == ["all-items"] and found["score"] == pytest.approx(11 / 12)
    assert "1 of the 12 items is not priced (t12)" in found["message"]


def test_a_run_this_workspace_never_made_fails_this_run(tmp_path: Path) -> None:
    run = Run(tmp_path)
    report = run.gold()
    found = run.verdict({**report, "run": "0" * 16})
    assert failed(found) == ["this-run"] and found["score"] == 0.0
    assert unchecked(found) == ["read-inventory", "report-saved", "submitted-as-saved"]


def test_a_missing_inventory_file_fails_sources(tmp_path: Path) -> None:
    run = Run(tmp_path)
    report = run.gold()
    (tmp_path / INVENTORY).unlink()
    found = run.verdict(report)
    assert failed(found) == ["sources"] and f"No file at {INVENTORY}" in found["message"]


# ----- Malformed -----


def test_an_unknown_item_in_the_submission_fails_submitted_shape(tmp_path: Path) -> None:
    run = Run(tmp_path)
    report = run.gold()
    changed = copy.deepcopy(report)
    changed["lines"].append({"item": "t99", "status": "FULL_PRICE", "price": "1.00"})
    found = run.verdict(changed)
    assert failed(found) == ["submitted-shape"] and "'t99' is not an item in this inventory" in found["message"]


def test_an_item_priced_twice_fails_submitted_shape(tmp_path: Path) -> None:
    run = Run(tmp_path)
    report = run.gold()
    changed = copy.deepcopy(report)
    changed["lines"].append(copy.deepcopy(changed["lines"][0]))
    found = run.verdict(changed)
    assert failed(found) == ["submitted-shape"] and "t01 is priced twice" in found["message"]


def test_a_price_on_a_pulled_item_fails_submitted_shape(tmp_path: Path) -> None:
    run = Run(tmp_path)
    report = run.gold()
    changed = copy.deepcopy(report)
    pulled = next(line for line in changed["lines"] if line["status"] == "PULLED")
    pulled["price"] = "10.00"
    found = run.verdict(changed)
    assert failed(found) == ["submitted-shape"]
    assert "a pulled item has no price, so price is null" in found["message"]


def test_a_null_price_on_an_item_still_on_the_floor_fails_submitted_shape(tmp_path: Path) -> None:
    run = Run(tmp_path)
    report = run.gold()
    changed = copy.deepcopy(report)
    changed["lines"][0]["price"] = None
    found = run.verdict(changed)
    assert failed(found) == ["submitted-shape"] and "only a pulled item has a null price" in found["message"]


def test_report_prices_refuses_a_line_whose_price_and_status_disagree(tmp_path: Path) -> None:
    """The tool refuses it on the way in, so a report file never holds one."""
    run = Run(tmp_path)
    run.read()
    from plugin.rules import RuleError

    with pytest.raises(RuleError, match="a pulled item has no price"):
        run.report([{"item": "t04", "status": "PULLED", "price": "10.00"}])
    with pytest.raises(RuleError, match="only a pulled item has a null price"):
        run.report([{"item": "t01", "status": "FULL_PRICE", "price": None}])
    with pytest.raises(RuleError, match="has no item 'nope'"):
        run.report([{"item": "nope", "status": "FULL_PRICE", "price": "1.00"}])


def test_a_submission_for_another_file_fails_submitted_task(tmp_path: Path) -> None:
    run = Run(tmp_path)
    report = run.gold()
    found = run.verdict({**report, "task": {"inventory": NEXT_DAY}})
    assert failed(found) == ["submitted-task"] and found["score"] == 0.0
    assert unchecked(found) == ["submitted-shape", "submitted-as-saved", "all-items", "status-exact", "price-exact"]


def test_an_altered_report_file_fails_report_saved(tmp_path: Path) -> None:
    run = Run(tmp_path)
    report = run.gold()
    (tmp_path / "reports" / run.run / "prices.json").write_text(json.dumps({"task": {"inventory": INVENTORY}, "lines": 7}))
    found = run.verdict(report)
    assert failed(found) == ["report-saved"] and "was altered after report_prices" in found["message"]


@pytest.mark.parametrize(
    ("fixture", "says"),
    [(FUTURE, "after the query day 49"), (BAD_COLOR, "not a colour the store stocks")],
)
def test_an_invalid_inventory_fails_sources(tmp_path: Path, fixture: str, says: str) -> None:
    """Rule 5: an item tagged after the query day, or wearing a colour the store does not stock,
    makes the file invalid rather than giving the item some other status. There is no status for
    it, so it fails as a source and the run scores 0."""
    run = Run(tmp_path)
    report = run.gold()
    shutil.copy(FIXTURES / fixture, tmp_path / INVENTORY)  # the same name, now invalid
    found = run.verdict(report)
    assert failed(found) == ["sources"] and says in found["message"] and found["score"] == 0.0


@pytest.mark.parametrize("fixture", [FUTURE, BAD_COLOR])
def test_the_tools_refuse_an_invalid_inventory(tmp_path: Path, fixture: str) -> None:
    """No tool prices an item out of an invalid file, so a run cannot get as far as a report."""
    from plugin.rules import RuleError

    stage(tmp_path, fixture)
    given = build_output({"inventory": fixture}, PriceInput)
    for tool in (read_inventory, price_key, age_markdown):
        with pytest.raises(RuleError):
            tool(given, tmp_path)


def test_a_markdown_schedule_with_a_gap_is_refused(tmp_path: Path) -> None:
    """pull_age is the day after the last band. A gap would leave an age the schedule says
    nothing about and the pull age has not reached: no rule would price it."""
    from plugin.rules import RuleError

    data = json.loads((FIXTURES / INVENTORY).read_text())
    data["markdown"]["pull_age"] = 50  # the last band ends at 41, so ages 42 to 49 are uncovered
    assert "pull_age is the day after the last band, so 42" in checked.parse_inventory(data)[1]
    with pytest.raises(RuleError, match="pull_age is the day after the last band"):
        read_inventory_data(data)


# ----- Boundary -----


@pytest.mark.parametrize(
    ("item", "status", "price", "why"),
    [
        ("t01", "FULL_PRICE", "12.00", "age 13: the last day before anything comes off"),
        ("t02", "MARKED_DOWN", "9.00", "age 14: the first day of the 25% band"),
        ("t03", "MARKED_DOWN", "10.00", "age 41: the last day before it is pulled"),
        ("t04", "PULLED", None, "age 42: pulled"),
        ("t05", "FULL_PRICE", "6.50", "age 0: tagged on the query day"),
        ("t06", "PULLED", None, "pulled and the week's colour: still pulled"),
        ("t07", "COLOR_OF_THE_WEEK", "7.50", "50% by age and by colour: the tie reads as the colour"),
        ("t08", "COLOR_OF_THE_WEEK", "12.00", "25% by age, 50% by colour: the colour wins, no stacking"),
        ("t09", "MARKED_DOWN", "1.43", "1.4250 exactly: half up, not half even"),
        ("t10", "MARKED_DOWN", "0.50", "0.40 would be under the floor"),
        ("t11", "COLOR_OF_THE_WEEK", "0.25", "already under the floor: it keeps its price"),
        ("t12", "FULL_PRICE", "9.99", "no discount at all"),
    ],
)
def test_each_boundary_prices_the_way_the_readme_says(tmp_path: Path, item: str, status: str, price: str | None, why: str) -> None:
    run = Run(tmp_path)
    line = next(entry for entry in run.answer() if entry["item"] == item)
    assert (line["status"], line["price"]) == (status, price), why


def test_a_pulled_item_is_pulled_whatever_colour_it_wears(tmp_path: Path) -> None:
    """t06 is pink on a pink week and 45 days old: rule 3's last clause."""
    run = Run(tmp_path)
    data = json.loads((Path(tmp_path) / INVENTORY).read_text())
    entry = next(item for item in data["items"] if item["id"] == "t06")
    assert entry["color"] == run.key.color_of_the_week
    assert next(line for line in run.key.lines if line.item == "t06").status.value == "PULLED"


def test_the_colour_of_the_week_turns_over_between_day_seven_and_day_eight() -> None:
    """week = (day - 1) // 7, so days 1 to 7 are week 0 and day 8 opens week 1."""
    assert [checked.week_of(day) for day in (1, 7, 8, 14, 15)] == [0, 0, 1, 1, 2]
    rotation = ["blue", "pink", "yellow", "green", "orange"]
    store = {"rotation": rotation, "query_day": 7}
    assert checked.color_of_the_week(store) == "blue"
    assert checked.color_of_the_week({**store, "query_day": 8}) == "pink"


def test_the_rotation_wraps_once_it_runs_out() -> None:
    rotation = ["blue", "pink"]
    assert [checked.color_of_the_week({"rotation": rotation, "query_day": day}) for day in (1, 8, 15, 22)] == [
        "blue",
        "pink",
        "blue",
        "pink",
    ]


# ----- The per-call checks -----


def test_every_tool_has_both_checks_on_its_module() -> None:
    """NanoAgent calls verify_input and verify_output on every tool call, so every Tool must
    resolve to a module exposing both."""
    from contract import Tool

    assert set(verifier.TOOLS) == set(Tool)
    for tool in Tool:
        module = verifier.TOOLS[tool]
        for name in ("verify_input", "verify_output"):
            assert callable(module.__dict__.get(name)), f"{tool.value}: {module.__name__} has no {name}"


def test_verify_input_answers_for_every_tool(tmp_path: Path) -> None:
    run = Run(tmp_path)
    from contract import Tool

    valid = {
        Tool.READ_INVENTORY: run.given,
        Tool.PRICE_KEY: run.given,
        Tool.AGE_MARKDOWN: run.given,
        Tool.REPORT_PRICES: build_output({"task": run.task, "lines": []}, ReportInput),
    }
    assert set(valid) == set(Tool)
    for tool, value in valid.items():
        found = verifier.verify_input(tool.value, value)
        assert found["valid"] is True, (tool.value, found["message"])
    empty = verifier.verify_input("read_inventory", build_output({"inventory": " "}, PriceInput))
    assert empty["valid"] is False


def test_verify_output_recomputes_the_inventory_from_the_file(tmp_path: Path) -> None:
    run = Run(tmp_path)
    data = plain_output(run.read())
    assert verifier.verify_output("read_inventory", run.given, build_output(data, InventoryOutput), str(tmp_path))["valid"]
    changed = copy.deepcopy(data)
    changed["items"] = changed["items"][:-1]
    found = verifier.verify_output("read_inventory", run.given, build_output(changed, InventoryOutput), str(tmp_path))
    assert not found["valid"] and "not the file's, in its order" in found["message"]
    moved = copy.deepcopy(data)
    moved["store"]["query_day"] = 50
    found = verifier.verify_output("read_inventory", run.given, build_output(moved, InventoryOutput), str(tmp_path))
    assert not found["valid"] and "query_day reads 50" in found["message"]


def test_the_age_distractor_is_checked_against_the_age_schedule_not_the_answer(tmp_path: Path) -> None:
    """age_markdown is honest about what it does; its check holds it to that and nothing more."""
    run = Run(tmp_path)
    found = age_markdown(run.given, tmp_path)
    assert verifier.verify_output("age_markdown", run.given, found, str(tmp_path))["valid"]
    assert all(line.status.value != "COLOR_OF_THE_WEEK" for line in found.lines)
    key = {line.item: (line.status.value, line.price) for line in run.key.lines}
    aged = {line.item: (line.status.value, line.price) for line in found.lines}
    assert sorted(item for item in aged if aged[item] != key[item]) == ["t07", "t08", "t11"]


def test_the_answer_key_is_checked_against_the_rules(tmp_path: Path) -> None:
    run = Run(tmp_path)
    assert verifier.verify_output("price_key", run.given, run.key, str(tmp_path))["valid"]


# ----- The two arithmetics, and the rules' own invariants -----


def random_store(source: random.Random) -> dict:
    colors = ["blue", "pink", "yellow", "green", "orange", "white"]
    rotation = source.sample(colors, source.randint(1, len(colors)))
    tops = sorted(source.sample(range(60), source.randint(1, 4)))
    bands = [{"max_age": top, "percent": source.choice([0, 10, 25, 50, 70, 100])} for top in tops]
    day = source.randint(1, 120)
    return {
        "query_day": day,
        "colors": colors,
        "rotation": rotation,
        "markdown": {
            "bands": bands,
            "pull_age": tops[-1] + 1,  # the day after the last band: the format allows no gap
            "color_percent": source.choice([0, 25, 50, 75, 100]),
            "minimum_price": source.choice(["0.00", "0.50", "1.00", "2.00"]),
        },
        "items": [
            {
                "id": f"x{index:03d}",
                "color": source.choice(colors),
                "price": f"{source.randint(0, 5000) // 1}.{source.randint(0, 99):02d}",
                "tagged": source.randint(1, day),
            }
            for index in range(source.randint(1, 8))
        ],
    }


def test_the_two_arithmetics_agree_over_a_thousand_random_inventories() -> None:
    """The plugin holds money as Decimal and rounds with ROUND_HALF_UP; the verifier works in
    whole cents and rounds with an integer comparison. They are written independently, so a
    rounding or floor bug in one of them shows up here as a disagreement."""
    source = random.Random(20261106)
    checkedtotal = 0
    for _ in range(1000):
        data = random_store(source)
        read, problem = checked.parse_inventory(data)
        assert problem is None, problem
        store, items = read
        theirs = checked.price_lines(store, items)
        inventory = read_inventory_data(data)
        mine = [(line.item, line.status.value, line.price) for line in price_all(inventory)]
        assert mine == theirs, data
        checkedtotal += len(items)
    assert checkedtotal > 3000


def test_the_rules_own_invariants_hold_over_random_inventories() -> None:
    """Stated as properties rather than cases: pulled is exactly an age past pull_age, the floor
    is never broken unless the original was already under it, the two discounts never stack, and
    a status only ever names the discount that was actually taken."""
    source = random.Random(760213)
    for _ in range(500):
        data = random_store(source)
        read, problem = checked.parse_inventory(data)
        assert problem is None, problem
        store, items = read
        color = checked.color_of_the_week(store)
        markdown = store["markdown"]
        floor = markdown["minimum_price"]
        for (name, own, cents, tagged), (line_item, status, price) in zip(items, checked.price_lines(store, items), strict=True):
            assert line_item == name
            age = store["query_day"] - tagged
            if age >= markdown["pull_age"]:
                assert (status, price) == ("PULLED", None)
                continue
            assert price is not None and status != "PULLED"
            schedule = checked.age_percent(markdown, age)
            of_the_week = markdown["color_percent"] if own == color else 0
            taken = max(schedule, of_the_week)
            got = checked.cents_of(price)[0]
            # Never stacked: the price is the original with exactly `taken` off, bar the floor.
            assert got == checked.marked(cents, taken, floor)
            assert got >= min(cents, floor), "the floor is broken only by an item already under it"
            assert got <= cents, "a markdown never raises a price"
            if status == "COLOR_OF_THE_WEEK":
                assert own == color and of_the_week >= schedule and of_the_week > 0
            elif status == "MARKED_DOWN":
                assert schedule > 0 and schedule > of_the_week
            else:
                assert (schedule, of_the_week) == (0, 0)


@pytest.mark.parametrize(
    ("price", "percent", "floor"),
    [("1.90", 25, 50), ("9.99", 50, 50), ("0.25", 50, 50), ("0.80", 50, 50), ("0.01", 100, 0), ("3.33", 70, 100)],
)
def test_a_hand_rounded_price_matches_both_arithmetics(price: str, percent: int, floor: int) -> None:
    cents = checked.cents_of(price)[0]
    plain = (Decimal(price) * (100 - percent)).scaleb(-2).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    wanted = max(plain, Decimal(floor).scaleb(-2)) if cents >= floor else Decimal(price)
    assert checked.written(checked.marked(cents, percent, floor)) == str(wanted)
    assert str(plugin_marked(Decimal(price), percent, Decimal(floor).scaleb(-2))) == str(wanted)


# ----- The verdict's own shape -----


def test_every_verdict_entry_has_the_same_keys_and_says_why(tmp_path: Path) -> None:
    run = Run(tmp_path)
    report = run.gold()
    broken = copy.deepcopy(report)
    broken["lines"][0]["price"] = "11.00"
    for found in (run.verdict(report), run.verdict(broken), run.verdict({**report, "run": "0" * 16})):
        entries = found["details"]["constraints"]
        order = [entry["id"] for entry in entries]
        assert order == list(TEXT)
        for position, entry in enumerate(entries):
            assert set(entry) == {"id", "constraint", "ok", "expected", "actual", "message"}
            assert (entry["message"] == "") == (entry["ok"] is True)
            if entry["ok"] is None:
                blocking = entry["message"].removeprefix("Not checked: ").removesuffix(" did not hold.").split(" and ")
                assert all(name in order[:position] for name in blocking), entry
        wrong = [entry for entry in entries if entry["ok"] is False]
        if wrong:
            more = f" (+{len(wrong) - 1} more)" if len(wrong) > 1 else ""
            assert found["message"] == f"{wrong[0]['id']}: {wrong[0]['message'].removesuffix('.')}{more}"


def test_the_verdict_is_the_same_on_a_second_reading(tmp_path: Path) -> None:
    """NanoAgent runs the verifier twice in a fresh process and fails the run on two verdicts."""
    run = Run(tmp_path)
    report = run.gold()
    assert json.dumps(run.verdict(report), sort_keys=True) == json.dumps(run.verdict(report), sort_keys=True)


def test_the_readme_lists_every_constraint_as_the_verifier_names_it() -> None:
    import re

    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    rows = re.findall(r"^\| (\d+) \| `([a-z-]+)` \| ([^|]+) \|", readme, re.MULTILINE)
    assert [(int(n), name, text.strip()) for n, name, text in rows] == [(n, *e) for n, e in enumerate(TEXT.items(), 1)]
