"""read_inventory: the store's rules and every item, both recomputed from the file."""

from .checks import result, verify_inventory_input
from .rules import load, written

verify_input = verify_inventory_input


def verify_output(input_value, output_value, workspace):
    store, items, source, problem = load(workspace, input_value.inventory)
    if problem:
        return result(False, problem)
    if output_value.source_sha256 != source:
        return result(False, "source_sha256 is not the hash of the inventory file")
    given = output_value.store
    if given.query_day != store["query_day"]:
        return result(False, f"query_day reads {given.query_day}, not the file's {store['query_day']}")
    if list(given.colors) != store["colors"] or list(given.rotation) != store["rotation"]:
        return result(False, "the colours or the rotation are not the file's, in its order")
    markdown = store["markdown"]
    if [(band.max_age, band.percent) for band in given.markdown.bands] != markdown["bands"]:
        return result(False, "the age bands are not the file's, in its order")
    if given.markdown.pull_age != markdown["pull_age"]:
        return result(False, f"pull_age reads {given.markdown.pull_age}, not the file's {markdown['pull_age']}")
    if given.markdown.color_percent != markdown["color_percent"]:
        return result(False, f"color_percent reads {given.markdown.color_percent}, not the file's")
    if given.markdown.minimum_price != written(markdown["minimum_price"]):
        return result(False, f"minimum_price reads {given.markdown.minimum_price!r}, not the file's")
    wanted = [(name, color, written(cents), tagged) for name, color, cents, tagged in items]
    if [(item.id, item.color, item.price, item.tagged) for item in output_value.items] != wanted:
        return result(False, "the items are not the file's, in its order")
    return result(True, "the store and the items are the file's", items=len(wanted), query_day=store["query_day"])
