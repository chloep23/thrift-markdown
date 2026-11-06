"""Reading an inventory file, and the rules that price one item on one store day.

Store days are plain integers counted from opening, day 1 being opening day: there is no
calendar here, so nothing depends on a clock or a timezone. Money is held as ``Decimal``
throughout and never as a float -- every price in a file and in an output is a decimal string
with exactly two places, so what is read, what is worked out and what is reported are the same
number written the same way.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

from contract import Band, Item, Line, Markdown, Status, Store

MONEY = re.compile(r"(?:0|[1-9][0-9]*)\.[0-9]{2}")
CENT = Decimal("0.01")
MOST_DOLLARS = 7  # integer digits a price may hold: keeps every product inside the decimal context
DAYS_A_WEEK = 7
# A colour no store stocks, so no item ever matches it: colours are checked non-empty when read.
NO_COLOR = ""
ID = set("abcdefghijklmnopqrstuvwxyz0123456789_-")


class RuleError(ValueError):
    """An inventory file that does not follow the format."""


@dataclass(frozen=True)
class Inventory:
    store: Store
    items: list[Item]


def money(text: str, what: str) -> Decimal:
    """``text`` as a Decimal, or raise: a price is a decimal string with exactly two places."""
    if not isinstance(text, str) or not MONEY.fullmatch(text):
        raise RuleError(f"{what}: a price is a decimal string with two places, e.g. 12.00, not {text!r}")
    if len(text) - 3 > MOST_DOLLARS:
        raise RuleError(f"{what}: a price runs to at most {MOST_DOLLARS} digits before the point, not {text!r}")
    try:
        return Decimal(text)
    except InvalidOperation as error:  # unreachable: MONEY already fixes the form
        raise RuleError(f"{what}: {text!r} is not a price") from error


def written(value: Decimal) -> str:
    """A Decimal as the two-place decimal string every price is written as."""
    return str(value.quantize(CENT))


def whole_percent(value, what: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 100:
        raise RuleError(f"{what}: a markdown is whole percentage points from 0 to 100, not {value!r}")
    return value


def read_markdown_data(data) -> Markdown:
    if not isinstance(data, dict):
        raise RuleError("markdown is an object")
    bands = data.get("bands")
    if not isinstance(bands, list) or not bands:
        raise RuleError("markdown.bands holds at least one band")
    made, last = [], None
    for position, band in enumerate(bands):
        if not isinstance(band, dict):
            raise RuleError("every band is an object")
        top = band.get("max_age")
        if not isinstance(top, int) or isinstance(top, bool) or top < 0:
            raise RuleError(f"band {position}: max_age is an age in days, not {top!r}")
        if last is not None and top <= last:
            raise RuleError(f"band {position}: the bands rise, so max_age {top} cannot follow {last}")
        made.append(Band(max_age=top, percent=whole_percent(band.get("percent"), f"band {position}")))
        last = top
    pull = data.get("pull_age")
    # The day after the last band, so the schedule and the pull age cover every age between them:
    # a gap would leave an age with no markdown and no answer.
    if not isinstance(pull, int) or isinstance(pull, bool) or pull != made[-1].max_age + 1:
        raise RuleError(f"pull_age is the day after the last band, so {made[-1].max_age + 1}, not {pull!r}")
    return Markdown(
        bands=made,
        pull_age=pull,
        color_percent=whole_percent(data.get("color_percent"), "color_percent"),
        minimum_price=str(money(data.get("minimum_price"), "minimum_price")),
    )


def read_inventory_data(data) -> Inventory:
    """The ``Inventory`` a parsed inventory file states, or raise ``RuleError``."""
    if not isinstance(data, dict):
        raise RuleError("an inventory file holds an object")
    day = data.get("query_day")
    if not isinstance(day, int) or isinstance(day, bool) or day < 1:
        raise RuleError(f"query_day is a store day counted from opening, so at least 1, not {day!r}")
    colors = data.get("colors")
    if not isinstance(colors, list) or not colors or not all(isinstance(name, str) and name.strip() for name in colors):
        raise RuleError("colors holds at least one tag colour")
    if len(set(colors)) != len(colors):
        raise RuleError("colors lists a colour twice")
    rotation = data.get("rotation")
    if not isinstance(rotation, list) or not rotation:
        raise RuleError("rotation holds at least one colour")
    outside = [name for name in rotation if name not in set(colors)]
    if outside:
        raise RuleError(f"rotation names {outside[0]!r}, which the store does not stock")
    store = Store(colors=list(colors), rotation=list(rotation), markdown=read_markdown_data(data.get("markdown")), query_day=day)

    held = data.get("items")
    if not isinstance(held, list) or not held:
        raise RuleError("items holds at least one item")
    seen, items = set(), []
    for item in held:
        if not isinstance(item, dict):
            raise RuleError("every item is an object")
        name = item.get("id")
        if not isinstance(name, str) or not name or set(name) - ID:
            raise RuleError(f"every item's id is lower-case letters, digits, underscores and dashes, not {name!r}")
        if name in seen:
            raise RuleError(f"item {name!r} is listed twice")
        color = item.get("color")
        if color not in set(colors):
            raise RuleError(f"{name}: {color!r} is not a colour the store stocks")
        tagged = item.get("tagged")
        if not isinstance(tagged, int) or isinstance(tagged, bool) or tagged < 1:
            raise RuleError(f"{name}: tagged is a store day counted from opening, so at least 1, not {tagged!r}")
        if tagged > day:
            raise RuleError(f"{name}: tagged on day {tagged}, after the query day {day}")
        seen.add(name)
        items.append(Item(id=name, color=color, price=str(money(item.get("price"), name)), tagged=tagged))
    return Inventory(store=store, items=items)


def week_of(day: int) -> int:
    """The store week a day falls in, numbered from opening: days 1-7 are week 0."""
    return (day - 1) // DAYS_A_WEEK


def color_of_the_week(store: Store) -> str:
    """The rotation colour in force on the store's query day."""
    return store.rotation[week_of(store.query_day) % len(store.rotation)]


def age_of(item: Item, store: Store) -> int:
    return store.query_day - item.tagged


def age_percent(markdown: Markdown, age: int) -> int | None:
    """What the age schedule takes off at ``age``, or None when the item is pulled."""
    if age >= markdown.pull_age:
        return None
    for band in markdown.bands:
        if age <= band.max_age:
            return band.percent
    # Unreachable: pull_age sits past the last band, so any age reaching here is already pulled.
    raise RuleError(f"no band covers age {age}")


def marked(original: Decimal, percent: int, floor: Decimal) -> Decimal:
    """``original`` with ``percent`` off, rounded half up to the cent, never under ``floor``.

    An item whose original price is already under the floor keeps that price: the floor is a
    floor on marking down, not a price the store raises anything to.
    """
    # scaleb, not a division: moving the exponent is exact, so the only rounding is the one below.
    cut = (original * (100 - percent)).scaleb(-2).quantize(CENT, rounding=ROUND_HALF_UP)
    if original < floor:
        return original
    return max(cut, floor)


def price_item(item: Item, store: Store, color: str) -> Line:
    """One item's line on the query day: its status, and its price unless it is pulled.

    Discounts never stack. The item takes the larger of its age markdown and the colour of the
    week, and when the two are equal the colour is what the line says: a tie reads
    COLOR_OF_THE_WEEK, so MARKED_DOWN means the age alone took more off.
    """
    schedule = age_percent(store.markdown, age_of(item, store))
    if schedule is None:
        return Line(item=item.id, status=Status.PULLED, price=None)
    of_the_week = store.markdown.color_percent if item.color == color else 0
    if of_the_week >= schedule and of_the_week > 0:
        status = Status.COLOR_OF_THE_WEEK
    elif schedule > 0:
        status = Status.MARKED_DOWN
    else:
        status = Status.FULL_PRICE
    floor = Decimal(store.markdown.minimum_price)
    return Line(item=item.id, status=status, price=written(marked(Decimal(item.price), max(schedule, of_the_week), floor)))


def price_all(inventory: Inventory) -> list[Line]:
    """Every item's line, in the inventory file's order."""
    color = color_of_the_week(inventory.store)
    return [price_item(item, inventory.store, color) for item in inventory.items]


def price_by_age(inventory: Inventory) -> list[Line]:
    """Every item priced from the age schedule alone, the colour of the week not looked at.

    This is what age_markdown returns, and it is wrong for exactly the items wearing the week's
    colour: it can never say COLOR_OF_THE_WEEK, and an item the colour saves more than its age
    does comes back at the age's price.
    """
    return [price_item(item, inventory.store, NO_COLOR) for item in inventory.items]


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def inside(workspace: Path, name: str) -> Path:
    relative = Path(name)
    root = Path(workspace).resolve()
    path = (root / relative).resolve()
    if relative.is_absolute() or ".." in relative.parts or not path.is_relative_to(root) or path == root:
        raise RuleError(f"{name!r} must name a file inside the workspace")
    return path


def read_text(workspace: Path, name: str) -> str:
    path = inside(workspace, name)
    if not path.is_file():
        raise RuleError(f"no file at {name}")
    return path.read_text(encoding="utf-8")


def load_inventory(workspace: Path, name: str) -> tuple[Inventory, str]:
    """(the inventory the file states, the hash of the file's text), or raise ``RuleError``."""
    text = read_text(workspace, name)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise RuleError(f"{name} is not JSON: {error}") from error
    return read_inventory_data(data), sha256_text(text)
