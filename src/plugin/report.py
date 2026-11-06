"""report_prices: merge this run's lines into its report file."""

from __future__ import annotations

import json
from pathlib import Path

from contract import Line, PricesOutput, ReportInput, ReportOutput, Status
from plugin.pricing import REPORTS, RUN, run_folder
from plugin.rules import RuleError, load_inventory

REPORT = "prices.json"


def report_path(run: str = RUN) -> str:
    return f"{REPORTS}/{run}/{REPORT}"


def report_prices(given: ReportInput, workspace: Path) -> ReportOutput:
    inventory, _ = load_inventory(Path(workspace), given.task.inventory)
    order = [item.id for item in inventory.items]
    named = [line.item for line in given.lines]
    unknown = [name for name in named if name not in set(order)]
    if unknown:
        raise RuleError(f"the inventory has no item {unknown[0]!r}")
    if len(set(named)) != len(named):
        raise RuleError("an item is priced twice in one call")
    for line in given.lines:
        pulled = line.status is Status.PULLED
        if pulled and line.price is not None:
            raise RuleError(f"{line.item}: a pulled item has no price, so price is null, not {line.price!r}")
        if not pulled and line.price is None:
            raise RuleError(f"{line.item}: only a pulled item has a null price")

    folder = run_folder(Path(workspace))
    path = folder / REPORT
    held = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"lines": {}}
    wanted = {"inventory": given.task.inventory}
    if held.get("task") not in (None, wanted):
        raise RuleError(f"{report_path()} is another task's report: start a new run")
    for line in given.lines:
        held["lines"][line.item] = {"status": line.status.value, "price": line.price}
    held["task"] = wanted
    path.write_text(json.dumps(held, indent=1), encoding="utf-8")

    lines = [
        Line(item=name, status=Status(held["lines"][name]["status"]), price=held["lines"][name]["price"])
        for name in order
        if name in held["lines"]
    ]
    report = PricesOutput(task=given.task, run=RUN, lines=lines)
    return ReportOutput(path=report_path(), covered=len(lines), complete=len(lines) == len(order), report=report)
