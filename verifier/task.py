"""The price-day verdict: 12 constraints, in order, on the answer key, the run the submission
names, the receipt read_inventory left, the saved and submitted report, and the lines themselves.

The verdict is valid only when every one holds. A failure among the first 9 -- the source file
and the report's integrity -- scores 0; otherwise the score is the share of the items priced
correctly, where correct means the status and the price are both right. An item is one or the
other, never half: a line with the right price under the wrong status is wrong, which is what
makes the colour of the week worth getting right even when it changes no number.
"""

from pathlib import Path

from .checks import RECEIPT, REPORT, constraint, read_json, result, run_folder, run_problem, summary
from .rules import STATUSES, color_of_the_week, load, price_lines

TEXT = {
    "answer-key": "The answer key is for this task's inventory",
    "sources": "The inventory file is well formed",
    "answer-key-right": "The answer key's lines are the day's prices",
    "this-run": "The report names a run of this workspace",
    "read-inventory": "read_inventory read this task's inventory in this run",
    "report-saved": "report_prices saved this run's report for this task",
    "submitted-task": "The submitted report is for this task",
    "submitted-shape": "The submitted report is well formed",
    "submitted-as-saved": "The submitted report equals the saved report",
    "all-items": "Every item is priced exactly once",
    "status-exact": "Every item's status is the one the rules give",
    "price-exact": "Every item's price is the one the rules give, and null exactly when PULLED",
}
ORDER = tuple(TEXT)
GATES = ORDER[:9]
ANSWER_CHECKS = ORDER[9:]
MOST_NAMED = 3
SUBMIT = "Submit the report the last report_prices call returned, as it is."


def named(names):
    shown = ", ".join(str(name) for name in names[:MOST_NAMED])
    return shown + (f" and {len(names) - MOST_NAMED} more" if len(names) > MOST_NAMED else "")


def also(words, names):
    return f" Also {words}: {named(names[1:])}." if len(names) > 1 else ""


def saved_report(workspace, run):
    """(the run's saved report, None) or (None, what is wrong with it)."""
    where = f"{run_folder(run)}/{REPORT}"
    found, problem = read_json(Path(workspace) / where)
    if problem == "missing":
        return None, f"no report at {where}: report_prices never saved this task's lines"
    if problem:
        return None, f"{where} is not a report: {problem}"
    if not isinstance(found, dict) or not isinstance(found.get("lines"), dict) or not isinstance(found.get("task"), dict):
        return None, f"{where} was altered after report_prices: it must hold task and lines"
    for item, line in found["lines"].items():
        if not isinstance(item, str) or not isinstance(line, dict) or set(line) != {"status", "price"}:
            return None, f"{where} was altered after report_prices: every line holds a status and a price"
        if line["status"] not in STATUSES or not isinstance(line["price"], (str, type(None))):
            return None, f"{where} was altered after report_prices: {item} is not a status and a price"
    return found, None


def shape_problem(ids, reported):
    """Why the submitted report cannot be judged, or None."""
    listed = [item for item, _, _ in reported]
    unknown = [item for item in listed if item not in ids]
    if unknown:
        return f"{unknown[0]!r} is not an item in this inventory"
    repeated = [item for item in listed if listed.count(item) > 1]
    if repeated:
        return f"{repeated[0]} is priced twice"
    for item, status, price in reported:
        if status == "PULLED" and price is not None:
            return f"{item}: a pulled item has no price, so price is null, not {price!r}"
        if status != "PULLED" and price is None:
            return f"{item}: only a pulled item has a null price"
    return None


def verify_task(arguments, output, reference, workspace):
    """The verdict on a submitted price-day report (see the module's docstring)."""
    checks = {}

    def put(identifier, ok, expected_value=None, actual=None, message=""):
        checks[identifier] = constraint(identifier, TEXT[identifier], ok, expected_value, actual, message)

    def skip(identifier, *needs):
        blocking = [need for need in needs if checks[need]["ok"] is not True]
        checks[identifier] = constraint(identifier, TEXT[identifier], None, message=f"Not checked: {' and '.join(blocking)} did not hold.")

    def hold(*identifiers):
        return all(checks[identifier]["ok"] is True for identifier in identifiers)

    # 1-3: the inventory file and the answer key over it.
    store, items, source, problem = load(workspace, arguments.inventory)
    if reference is None:
        put("answer-key", False, None, None, f"No answer key: price_key never read {arguments.inventory}.")
    elif problem is None and reference.source_sha256 != source:
        put("answer-key", False, source[:16], reference.source_sha256[:16], "The answer key read another file than this task names.")
    else:
        put("answer-key", True)
    put("sources", problem is None, None, None, problem or "")
    # The items are the file's, so they are known as soon as sources holds; only the prices to
    # compare against need the answer key.
    ids = [name for name, _, _, _ in items] if problem is None else []
    wanted, color = [], None
    if hold("answer-key", "sources"):
        wanted = price_lines(store, items)
        color = color_of_the_week(store)
        given = [(line.item, line.status.value, line.price) for line in reference.lines]
        if reference.color_of_the_week != color:
            message = f"The answer key calls the week's colour {reference.color_of_the_week!r}, not {color!r}."
        elif given != wanted:
            message = "The answer key's lines are not the day's prices."
        else:
            message = ""
        put("answer-key-right", not message, None, None, message)
    else:
        skip("answer-key-right", "answer-key", "sources")

    # 4-5: the run, and the receipt read_inventory left in it.
    run = output.run
    problem = run_problem(workspace, run)
    put("this-run", problem is None, None, run, problem or "")
    if hold("this-run", "sources"):
        where = f"{run_folder(run)}/{RECEIPT}"
        found, trouble = read_json(Path(workspace) / where)
        if trouble == "missing":
            message = f"read_inventory was never called in run {run} (no {where}): read the inventory before pricing."
        elif trouble:
            message = f"{where} is not a receipt: {trouble}."
        elif not isinstance(found, dict) or found.get("run") != run:
            message = f"{where} was altered after read_inventory: it does not name run {run}."
        elif found.get("inventory") != arguments.inventory:
            message = f"read_inventory read {found.get('inventory')!r}, not this task's {arguments.inventory!r}."
        else:
            message = ""
        put("read-inventory", not message, None, None, message)
    else:
        skip("read-inventory", "this-run", "sources")

    # 6-9: the saved and the submitted report.
    saved = None
    if hold("this-run"):
        saved, problem = saved_report(workspace, run)
        if saved is not None and saved["task"] != {"inventory": arguments.inventory}:
            saved, problem = None, f"the saved report is for another task: {saved['task']}"
        put("report-saved", saved is not None, None, None, problem or "")
    else:
        skip("report-saved", "this-run")
    given_task = {"inventory": output.task.inventory}
    wanted_task = {"inventory": arguments.inventory}
    put("submitted-task", given_task == wanted_task, wanted_task, given_task, f"The submitted report names {given_task}, not this task's. {SUBMIT}")
    reported = [(line.item, line.status.value, line.price) for line in output.lines]
    if hold("sources", "submitted-task"):
        problem = shape_problem(set(ids), reported)
        put("submitted-shape", problem is None, None, None, f"The submitted report is malformed: {problem}" if problem else "")
    else:
        skip("submitted-shape", "sources", "submitted-task")
    if saved is not None and hold("submitted-shape"):
        held = saved["lines"]
        difference = ""
        for item, status, price in reported:
            if item not in held:
                difference = f"it adds {item}, which the saved report does not hold"
            elif (held[item]["status"], held[item]["price"]) != (status, price):
                difference = f"{item} reads {status} {price} in the submission but {held[item]['status']} {held[item]['price']} in the saved report"
            if difference:
                break
        if not difference and len(held) != len(reported):
            difference = "it leaves out a line the saved report holds"
        put("submitted-as-saved", not difference, len(held), len(reported), f"The submitted report is not the saved report {run_folder(run)}/{REPORT}: {difference}. {SUBMIT}")
    else:
        skip("submitted-as-saved", "report-saved", "submitted-shape")

    # 10-12: the lines themselves.
    right = None
    if hold("answer-key-right", "submitted-shape"):
        by_item = {item: (status, price) for item, status, price in reported}
        rules = {item: (status, price) for item, status, price in wanted}
        missing = [item for item in ids if item not in by_item]
        put(
            "all-items",
            not missing,
            len(ids),
            len(by_item),
            f"{len(missing)} of the {len(ids)} items {'is' if len(missing) == 1 else 'are'} not priced ({named(missing)}).",
        )
        off_status = [item for item in ids if item in by_item and by_item[item][0] != rules[item][0]]
        if off_status:
            first = off_status[0]
            put(
                "status-exact",
                False,
                {item: rules[item][0] for item in off_status},
                {item: by_item[item][0] for item in off_status},
                f"{first} is reported {by_item[first][0]}, but on day {store['query_day']} it is {rules[first][0]}.{also('wrong', off_status)}",
            )
        else:
            put("status-exact", True)
        off_price = [item for item in ids if item in by_item and by_item[item][1] != rules[item][1]]
        if off_price:
            first = off_price[0]
            put(
                "price-exact",
                False,
                {item: rules[item][1] for item in off_price},
                {item: by_item[item][1] for item in off_price},
                f"{first} is reported at {by_item[first][1]}, but the rules give {rules[first][1]}.{also('wrong', off_price)}",
            )
        else:
            put("price-exact", True)
        right = sum(1 for item in ids if by_item.get(item) == rules[item])
    else:
        for identifier in ANSWER_CHECKS:
            skip(identifier, "answer-key-right", "submitted-shape")

    constraints = [checks[identifier] for identifier in ORDER]
    valid = all(entry["ok"] is True for entry in constraints)
    if any(checks[identifier]["ok"] is not True for identifier in GATES) or right is None or not ids:
        score = 0.0
    else:
        score = right / len(ids)
    details = {"constraints": constraints, "items": len(ids) or None, "color_of_the_week": color}
    if right is not None:
        details["right"] = right
    if valid:
        return result(True, f"All {len(constraints)} checks hold: {right} of {len(ids)} items priced right, the week's colour {color}.", score=1.0, **details)
    return result(False, summary(constraints), score=min(score, 0.99), **details)
