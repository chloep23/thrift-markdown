"""price_key: every item's price on the query day, recomputed."""

from .checks import result, verify_inventory_input
from .rules import color_of_the_week, load, price_lines

verify_input = verify_inventory_input


def verify_output(input_value, output_value, workspace):
    store, items, source, problem = load(workspace, input_value.inventory)
    if problem:
        return result(False, problem)
    if output_value.source_sha256 != source:
        return result(False, "source_sha256 is not the hash of the inventory file")
    color = color_of_the_week(store)
    if output_value.color_of_the_week != color:
        return result(False, f"the colour of the week reads {output_value.color_of_the_week!r}, not {color!r}")
    wanted = price_lines(store, items)
    given = [(line.item, line.status.value, line.price) for line in output_value.lines]
    if given != wanted:
        return result(False, "the answer key's lines are not the day's prices, in the file's order")
    return result(True, "the answer key is the day's prices", lines=len(wanted), color_of_the_week=color)
