"""The tools: read_inventory, price_key (the reference) and age_markdown (which applies the age
schedule and nothing else)."""

from __future__ import annotations

import json
import secrets
from pathlib import Path

from contract import AgeMarkdownOutput, InventoryOutput, KeyOutput, PriceInput
from plugin.rules import color_of_the_week, load_inventory, price_all, price_by_age

# One token per plugin process: every file a run writes lands under reports/<RUN>/.
RUN = secrets.token_hex(8)
REPORTS = "reports"
MARKER = "run.json"
RECEIPT = "task.json"


def run_folder(workspace: Path, run: str = RUN) -> Path:
    folder = Path(workspace) / REPORTS / run
    folder.mkdir(parents=True, exist_ok=True)
    marker = folder / MARKER
    if not marker.is_file():
        marker.write_text(json.dumps({"run": run}), encoding="utf-8")
    return folder


def read_inventory(given: PriceInput, workspace: Path) -> InventoryOutput:
    """The store's rules, its rotation, the query day and every item, in one call."""
    inventory, source = load_inventory(Path(workspace), given.inventory)
    receipt = {"run": RUN, "inventory": given.inventory, "sha256": source}
    (run_folder(Path(workspace)) / RECEIPT).write_text(json.dumps(receipt, indent=1), encoding="utf-8")
    return InventoryOutput(run=RUN, store=inventory.store, items=inventory.items, source_sha256=source)


def price_key(given: PriceInput, workspace: Path) -> KeyOutput:
    """Every item's price on the query day. The task's reference: the agent never sees it."""
    inventory, source = load_inventory(Path(workspace), given.inventory)
    return KeyOutput(
        source_sha256=source,
        color_of_the_week=color_of_the_week(inventory.store),
        lines=price_all(inventory),
    )


def age_markdown(given: PriceInput, workspace: Path) -> AgeMarkdownOutput:
    """Every item priced from the age schedule alone.

    Honest about what it does and not how the task is solved: it never looks at the colour of
    the week, so for every item wearing that colour it gives the wrong status, and the wrong
    price too whenever the colour would have taken more off than the item's age did.
    """
    inventory, _ = load_inventory(Path(workspace), given.inventory)
    return AgeMarkdownOutput(lines=price_by_age(inventory))
