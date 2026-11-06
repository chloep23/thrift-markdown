"""Staging a workspace and running the prescribed path, as the host runs a price-day task."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from slimconfig import build_output, plain_output

import verifier
from contract import KeyOutput, PriceInput, PricesOutput, ReportInput
from plugin import price_key, read_inventory, report_prices

FIXTURES = Path(__file__).resolve().parent / "fixtures"
INVENTORY = "inventory.json"
NEXT_DAY = "inventory_next.json"
FUTURE = "inventory_future.json"
BAD_COLOR = "inventory_color.json"
# The committed inventory, read from the file so the tests and the data cannot drift apart.
# What it must hold is asserted in test_data.py.
ITEMS = json.loads((FIXTURES / INVENTORY).read_text())["items"]
IDS = [item["id"] for item in ITEMS]


def stage(workspace: Path, *names: str) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    for name in names:
        shutil.copy(FIXTURES / name, workspace / name)


class Run:
    """One task's workspace: the staged inventory, the tools, and the verdict on what was submitted."""

    def __init__(self, workspace: Path, inventory: str = INVENTORY) -> None:
        self.workspace = workspace
        self.task = {"inventory": inventory}
        stage(workspace, inventory)
        self.given = build_output(self.task, PriceInput)
        self.submitted: dict | None = None
        self.run = ""
        # The host pins the reference before the agent runs.
        self.key: KeyOutput = build_output(plain_output(price_key(self.given, workspace)), KeyOutput)

    def read(self):
        found = read_inventory(self.given, self.workspace)
        self.run = found.run
        return found

    def report(self, lines: list[dict]) -> dict:
        given = build_output({"task": self.task, "lines": lines}, ReportInput)
        self.submitted = plain_output(report_prices(given, self.workspace).report)
        return self.submitted

    def answer(self) -> list[dict]:
        """The answer key, in the shape report_prices takes."""
        return [{"item": line.item, "status": line.status.value, "price": line.price} for line in self.key.lines]

    def gold(self) -> dict:
        """The prescribed path, priced right: read the inventory, then one report call."""
        self.read()
        return self.report(self.answer())

    def verdict(self, report: dict | None = None, reference: KeyOutput | None = ...) -> dict:
        found = report if report is not None else self.submitted
        return verifier.verify_task(
            "price-day",
            self.given,
            build_output(found, PricesOutput),
            self.key if reference is ... else reference,
            str(self.workspace),
        )


def failed(verdict: dict) -> list[str]:
    return [entry["id"] for entry in verdict["details"]["constraints"] if entry["ok"] is False]


def unchecked(verdict: dict) -> list[str]:
    return [entry["id"] for entry in verdict["details"]["constraints"] if entry["ok"] is None]
