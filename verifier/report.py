"""report_prices: the call and the merged report it returns."""

from .checks import inventory_problem, line_problem, result, run_folder
from .rules import load


def verify_input(value):
    problem = inventory_problem(value.task)
    if problem:
        return result(False, problem)
    named = [line.item for line in value.lines]
    if len(set(named)) != len(named):
        return result(False, "an item is priced twice in one call")
    for line in value.lines:
        problem = line_problem(line)
        if problem:
            return result(False, problem)
    return result(True, "input is valid", lines=len(named))


def verify_output(input_value, output_value, workspace):
    _, items, _, problem = load(workspace, input_value.task.inventory)
    if problem:
        return result(False, problem)
    order = [name for name, _, _, _ in items]
    report = output_value.report
    if output_value.path != f"{run_folder(report.run)}/prices.json":
        return result(False, f"the report path reads {output_value.path!r}, not this run's")
    if output_value.covered != len(report.lines):
        return result(False, f"covered reads {output_value.covered}, but the report holds {len(report.lines)} lines")
    if output_value.complete != (len(report.lines) == len(order)):
        return result(False, f"complete reads {output_value.complete}, which is not whether every item is priced")
    listed = [line.item for line in report.lines]
    if listed != [name for name in order if name in set(listed)]:
        return result(False, "the merged report's lines are not in the inventory file's order")
    for line in input_value.lines:
        if not any(held.item == line.item and held.status is line.status and held.price == line.price for held in report.lines):
            return result(False, f"{line.item} is not in the merged report")
    return result(True, "the merged report holds this call", covered=output_value.covered)
