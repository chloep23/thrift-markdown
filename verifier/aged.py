"""age_markdown: checked against the age schedule it claims, not against the task's answer.

It is right to ignore the colour of the week here. The tool says that is what it does, and the
check holds it to exactly that, so the trap it sets for the agent is never scored as a bug.
"""

from .checks import result, verify_inventory_input
from .rules import load, price_lines_by_age

verify_input = verify_inventory_input


def verify_output(input_value, output_value, workspace):
    store, items, _, problem = load(workspace, input_value.inventory)
    if problem:
        return result(False, problem)
    wanted = price_lines_by_age(store, items)
    given = [(line.item, line.status.value, line.price) for line in output_value.lines]
    if given != wanted:
        return result(False, "the lines are not the age schedule's prices, in the file's order")
    return result(True, "the lines are the age schedule alone", lines=len(wanted))
