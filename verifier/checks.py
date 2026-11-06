"""Checks shared by the tool verifiers: a result, the ordered constraint list a task verdict
carries, and the files a run leaves. Pure functions of their arguments and the files on disk."""

import json
import re
from pathlib import Path

REPORTS = "reports"
MARKER = "run.json"
RECEIPT = "task.json"
REPORT = "prices.json"
RUN_TOKEN = re.compile(r"[0-9a-f]{16}")
MOST = 10
MAX_FILE_BYTES = 4_000_000
PLAIN_WORD = re.compile(r"[a-z]+ ")


def result(valid, message, *, score=None, **details):
    return {"valid": valid, "score": float(valid) if score is None else score, "message": message, "details": details}


def compact(value):
    if isinstance(value, list) and len(value) > MOST:
        return value[:MOST] + [f"… {len(value) - MOST} more"]
    if isinstance(value, dict) and len(value) > MOST:
        return {**dict(list(value.items())[:MOST]), "…": f"{len(value) - MOST} more"}
    return value


def sentence(text):
    return text[0].upper() + text[1:] if PLAIN_WORD.match(text) else text


def constraint(identifier, text, ok, expected=None, actual=None, message=""):
    """One constraint's entry: ok is True (holds), False (fails) or None (not checked)."""
    return {
        "id": identifier,
        "constraint": text,
        "ok": ok,
        "expected": compact(expected),
        "actual": compact(actual),
        "message": "" if ok is True else sentence(message or text),
    }


def summary(constraints):
    failed = [entry for entry in constraints if entry["ok"] is False]
    first = failed[0] if failed else next(entry for entry in constraints if entry["ok"] is not True)
    return f"{first['id']}: {first['message'].removesuffix('.')}" + (f" (+{len(failed) - 1} more)" if len(failed) > 1 else "")


def shown(value):
    return f"{value!r}" if isinstance(value, str) else str(value)


def read_json(path):
    path = Path(path)
    if not path.is_file():
        return None, "missing"
    if path.stat().st_size > MAX_FILE_BYTES:
        return None, "too large"
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (ValueError, RecursionError):
        return None, "not JSON"


def run_folder(run):
    return f"{REPORTS}/{run}"


def run_problem(workspace, run):
    """What is wrong with ``run`` as a run of this workspace, or None."""
    if not isinstance(run, str) or not RUN_TOKEN.fullmatch(run):
        return f"{shown(run)} is not a run token (16 hex digits): submit the report that report_prices returned"
    where = f"{run_folder(run)}/{MARKER}"
    found, problem = read_json(Path(workspace) / where)
    if problem == "missing":
        return f"this workspace has no run {run} (no {where}): submit the report that report_prices returned"
    if problem:
        return f"{where} is not a run marker: {problem}"
    if not isinstance(found, dict) or found.get("run") != run:
        return f"{where} is not the marker of run {run}"
    return None


def inventory_problem(value):
    if not isinstance(value.inventory, str) or not value.inventory.strip():
        return "the inventory is named by its path in the workspace"
    return None


def verify_inventory_input(value):
    problem = inventory_problem(value)
    return result(False, problem) if problem else result(True, "input is valid")


def line_problem(line):
    """Why a reported line cannot stand on its own, or None: a pulled item has no price, and
    every other item has one."""
    pulled = line.status.value == "PULLED"
    if pulled and line.price is not None:
        return f"{line.item}: a pulled item has no price, so price is null, not {line.price!r}"
    if not pulled and line.price is None:
        return f"{line.item}: only a pulled item has a null price"
    return None
