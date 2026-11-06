"""The inventory, read again from the file, and the prices worked out again from the rules.

This is the verifier's own reading and its own arithmetic. It shares no code with the plugin,
and it does not share a number type either: the plugin holds money as ``Decimal`` and rounds
with ROUND_HALF_UP, while this works in whole cents and decides the rounding with a comparison
of integers. A tool and the check of that tool therefore cannot be wrong in the same way.

It also enforces what makes the items comparable -- ids are unique, every colour is one the
store stocks, nothing is tagged after the query day, and the age bands rise with pull_age past
the last of them -- so a file that would make the task ill-posed fails as a source rather than
quietly changing the answer.
"""

import hashlib
import json
import re
from pathlib import Path

MONEY = re.compile(r"(?:0|[1-9][0-9]*)\.[0-9]{2}")
MOST_DOLLARS = 7
DAYS_A_WEEK = 7
CENTS = 100
ID = set("abcdefghijklmnopqrstuvwxyz0123456789_-")
STATUSES = ("FULL_PRICE", "MARKED_DOWN", "COLOR_OF_THE_WEEK", "PULLED")
# A colour no store stocks: colours are checked non-empty when read, so no item matches it.
NO_COLOR = ""


def whole(value):
    """Whether ``value`` is a plain integer (True and False are not)."""
    return isinstance(value, int) and not isinstance(value, bool)


def cents_of(text):
    """(the price in whole cents, None) or (None, what is wrong with it as a price)."""
    if not isinstance(text, str) or not MONEY.fullmatch(text):
        return None, f"a price is a decimal string with two places, e.g. 12.00, not {text!r}"
    if len(text) - 3 > MOST_DOLLARS:
        return None, f"a price runs to at most {MOST_DOLLARS} digits before the point, not {text!r}"
    dollars, pennies = text.split(".")
    return int(dollars) * CENTS + int(pennies), None


def written(cents):
    """Whole cents as the two-place decimal string every price is written as."""
    return f"{cents // CENTS}.{cents % CENTS:02d}"


def percent_of(value, what):
    if not whole(value) or not 0 <= value <= CENTS:
        return None, f"{what}: a markdown is whole percentage points from 0 to 100, not {value!r}"
    return value, None


def parse_markdown(data):
    """(the markdown rules as plain values, None) or (None, what is wrong)."""
    if not isinstance(data, dict):
        return None, "markdown is an object"
    bands = data.get("bands")
    if not isinstance(bands, list) or not bands:
        return None, "markdown.bands holds at least one band"
    made, last = [], None
    for position, band in enumerate(bands):
        if not isinstance(band, dict):
            return None, "every band is an object"
        top = band.get("max_age")
        if not whole(top) or top < 0:
            return None, f"band {position}: max_age is an age in days, not {top!r}"
        if last is not None and top <= last:
            return None, f"band {position}: the bands rise, so max_age {top} cannot follow {last}"
        percent, problem = percent_of(band.get("percent"), f"band {position}")
        if problem:
            return None, problem
        made.append((top, percent))
        last = top
    pull = data.get("pull_age")
    # The day after the last band, so the schedule and the pull age cover every age between them.
    if not whole(pull) or pull != made[-1][0] + 1:
        return None, f"pull_age is the day after the last band, so {made[-1][0] + 1}, not {pull!r}"
    color_percent, problem = percent_of(data.get("color_percent"), "color_percent")
    if problem:
        return None, problem
    floor, problem = cents_of(data.get("minimum_price"))
    if problem:
        return None, f"minimum_price: {problem}"
    return {"bands": made, "pull_age": pull, "color_percent": color_percent, "minimum_price": floor}, None


def parse_inventory(data):
    """((the store, the items as (id, colour, cents, tagged) tuples), None) or (None, what is wrong)."""
    if not isinstance(data, dict):
        return None, "an inventory file holds an object"
    day = data.get("query_day")
    if not whole(day) or day < 1:
        return None, f"query_day is a store day counted from opening, so at least 1, not {day!r}"
    colors = data.get("colors")
    if not isinstance(colors, list) or not colors or not all(isinstance(name, str) and name.strip() for name in colors):
        return None, "colors holds at least one tag colour"
    if len(set(colors)) != len(colors):
        return None, "colors lists a colour twice"
    rotation = data.get("rotation")
    if not isinstance(rotation, list) or not rotation:
        return None, "rotation holds at least one colour"
    outside = [name for name in rotation if name not in set(colors)]
    if outside:
        return None, f"rotation names {outside[0]!r}, which the store does not stock"
    markdown, problem = parse_markdown(data.get("markdown"))
    if problem:
        return None, problem

    held = data.get("items")
    if not isinstance(held, list) or not held:
        return None, "items holds at least one item"
    seen, items = set(), []
    for item in held:
        if not isinstance(item, dict):
            return None, "every item is an object"
        name = item.get("id")
        if not isinstance(name, str) or not name or set(name) - ID:
            return None, f"every item's id is lower-case letters, digits, underscores and dashes, not {name!r}"
        if name in seen:
            return None, f"item {name!r} is listed twice"
        color = item.get("color")
        if color not in set(colors):
            return None, f"{name}: {color!r} is not a colour the store stocks"
        tagged = item.get("tagged")
        if not whole(tagged) or tagged < 1:
            return None, f"{name}: tagged is a store day counted from opening, so at least 1, not {tagged!r}"
        if tagged > day:
            return None, f"{name}: tagged on day {tagged}, after the query day {day}"
        cents, problem = cents_of(item.get("price"))
        if problem:
            return None, f"{name}: {problem}"
        seen.add(name)
        items.append((name, color, cents, tagged))
    store = {"colors": list(colors), "rotation": list(rotation), "markdown": markdown, "query_day": day}
    return (store, items), None


def week_of(day):
    """The store week a day falls in, numbered from opening: days 1-7 are week 0."""
    return (day - 1) // DAYS_A_WEEK


def color_of_the_week(store):
    rotation = store["rotation"]
    return rotation[week_of(store["query_day"]) % len(rotation)]


def age_percent(markdown, age):
    """What the age schedule takes off at ``age``, or None when the item is pulled."""
    if age >= markdown["pull_age"]:
        return None
    for top, percent in markdown["bands"]:
        if age <= top:
            return percent
    return None  # unreachable: pull_age sits past the last band


def marked(cents, percent, floor):
    """``cents`` with ``percent`` off, rounded half up to the cent, never under ``floor``.

    Whole-cent arithmetic: the product is exact and the rounding is one integer comparison, so
    nothing here depends on a decimal context. An item already under the floor keeps its price.
    """
    kept, rest = divmod(cents * (CENTS - percent), CENTS)
    if 2 * rest >= CENTS:
        kept += 1
    if cents < floor:
        return cents
    return max(kept, floor)


def price_line(item, store, color):
    """One item's (id, status, price) on the query day; the price is None when it is pulled."""
    name, own, cents, tagged = item
    markdown = store["markdown"]
    schedule = age_percent(markdown, store["query_day"] - tagged)
    if schedule is None:
        return name, "PULLED", None
    of_the_week = markdown["color_percent"] if own == color else 0
    if of_the_week >= schedule and of_the_week > 0:
        status = "COLOR_OF_THE_WEEK"
    elif schedule > 0:
        status = "MARKED_DOWN"
    else:
        status = "FULL_PRICE"
    return name, status, written(marked(cents, max(schedule, of_the_week), markdown["minimum_price"]))


def price_lines(store, items):
    """Every item's line, in the inventory file's order."""
    color = color_of_the_week(store)
    return [price_line(item, store, color) for item in items]


def price_lines_by_age(store, items):
    """Every item priced from the age schedule alone, the colour of the week not looked at."""
    return [price_line(item, store, NO_COLOR) for item in items]


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_text(workspace, name):
    if not isinstance(name, str) or not name:
        return None, f"{name!r} is not a file name"
    relative = Path(name)
    root = Path(workspace).resolve()
    path = (root / relative).resolve()
    if relative.is_absolute() or ".." in relative.parts or not path.is_relative_to(root) or path == root:
        return None, f"{name!r} must name a file inside the workspace"
    if not path.is_file():
        return None, f"no file at {name}"
    if path.stat().st_size > 4_000_000:
        return None, f"{name} is too large to read"
    return path.read_text(encoding="utf-8"), None


def load(workspace, name):
    """(the store, the items, the file's hash, None) or (None, None, None, what is wrong)."""
    text, problem = read_text(workspace, name)
    if problem:
        return None, None, None, problem
    try:
        data = json.loads(text)
    except (ValueError, RecursionError) as error:
        return None, None, None, f"{name} is not JSON: {error}"
    read, problem = parse_inventory(data)
    if problem:
        return None, None, None, f"{name}: {problem}"
    store, items = read
    return store, items, sha256_text(text), None
