"""Each tool's and task's typed input and output (see nanoagent.plugin.v0001.contract): declarations only."""

from dataclasses import dataclass
from enum import Enum
from typing import Annotated

from slimconfig import Output


class Tool(Enum):
    READ_INVENTORY = "read_inventory"
    REPORT_PRICES = "report_prices"
    PRICE_KEY = "price_key"
    AGE_MARKDOWN = "age_markdown"


class Task(Enum):
    PRICE_DAY = "price-day"


class Status(Enum):
    FULL_PRICE = "FULL_PRICE"
    MARKED_DOWN = "MARKED_DOWN"
    COLOR_OF_THE_WEEK = "COLOR_OF_THE_WEEK"
    PULLED = "PULLED"


INVENTORY = "The inventory file, relative to the workspace, e.g. inventory.json"
ITEM_ID = "The item's id, exactly as the inventory file writes it"
COLOR = "The item's tag colour, exactly as the inventory file writes it"
MONEY = "A price in dollars, as a decimal string with exactly two places, e.g. 12.00"
MONEY_OR_NONE = "The price on the query day, as a decimal string with exactly two places; null when the item is PULLED"
TAGGED = "The store day the item was tagged, counted from opening"
DAY = "The store day being priced, counted from opening (day 1 is opening day)"
RUN = "The run that read this task's inventory, as read_inventory returns it: copy it unchanged"
SOURCE_HASH = "sha256 over the inventory file the prices were worked out from"
STATUS = "FULL_PRICE, MARKED_DOWN, COLOR_OF_THE_WEEK or PULLED"
PERCENT = "A markdown as whole percentage points off, e.g. 25"


@dataclass
class Band(Output):
    max_age: Annotated[int, "This band covers every age up to and including max_age, in days"]
    percent: Annotated[int, PERCENT]


@dataclass
class Markdown(Output):
    bands: Annotated[list[Band], "The age schedule, by rising max_age; an age past the last band is pulled"]
    pull_age: Annotated[int, "At this age in days, and past it, the item is pulled from the floor"]
    color_percent: Annotated[int, "What the colour of the week takes off"]
    minimum_price: Annotated[str, MONEY]


@dataclass
class Store(Output):
    colors: Annotated[list[str], "Every tag colour the store uses"]
    rotation: Annotated[list[str], "The weekly colour rotation, from the store's first week"]
    markdown: Annotated[Markdown, "The store's markdown rules"]
    query_day: Annotated[int, DAY]


@dataclass
class Item(Output):
    id: Annotated[str, ITEM_ID]
    color: Annotated[str, COLOR]
    price: Annotated[str, MONEY]
    tagged: Annotated[int, TAGGED]


@dataclass
class Line(Output):
    item: Annotated[str, ITEM_ID]
    status: Annotated[Status, STATUS]
    price: Annotated[str | None, MONEY_OR_NONE]


@dataclass
class PriceInput(Output):
    inventory: Annotated[str, INVENTORY]


@dataclass
class InventoryOutput(Output):
    run: Annotated[str, RUN]
    store: Annotated[Store, "The store's rules, its colour rotation and the day being priced"]
    items: Annotated[list[Item], "Every item to price, in the inventory file's order"]
    source_sha256: Annotated[str, SOURCE_HASH]


@dataclass
class ReportInput(Output):
    task: Annotated[PriceInput, "The task input, exactly as given"]
    lines: Annotated[list[Line], "The lines this call reports; an earlier line for the same item is replaced"]


@dataclass
class PricesOutput(Output):
    task: Annotated[PriceInput, "The task input, exactly as given"]
    run: Annotated[str, RUN]
    lines: Annotated[list[Line], "One line per item, in the inventory file's order"]


@dataclass
class ReportOutput(Output):
    path: Annotated[str, "The report file, relative to the workspace: reports/<run>/prices.json"]
    covered: Annotated[int, "How many of the items the merged report prices so far"]
    complete: Annotated[bool, "Whether every item is priced: then submit the report"]
    report: Annotated[PricesOutput, "The merged report so far"]


@dataclass
class KeyOutput(Output):
    source_sha256: Annotated[str, SOURCE_HASH]
    color_of_the_week: Annotated[str, "The rotation colour in force on the query day"]
    lines: Annotated[list[Line], "Every item's price on the query day, in the inventory file's order"]


@dataclass
class AgeMarkdownOutput(Output):
    lines: Annotated[
        list[Line],
        "Every item priced from the age schedule alone, the colour of the week not looked at, in the file's order",
    ]


TOOLS = {
    Tool.READ_INVENTORY: (PriceInput, InventoryOutput),
    Tool.REPORT_PRICES: (ReportInput, ReportOutput),
    Tool.PRICE_KEY: (PriceInput, KeyOutput),
    Tool.AGE_MARKDOWN: (PriceInput, AgeMarkdownOutput),
}
TASKS = {Task.PRICE_DAY: (PriceInput, PricesOutput)}
