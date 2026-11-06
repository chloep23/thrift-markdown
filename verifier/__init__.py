"""The deterministic verifier: each tool's checks live in its own module, on contract instances."""

from contract import Task, Tool

from . import aged, inventory, key, report, task

TOOLS = {
    Tool.READ_INVENTORY: inventory,
    Tool.REPORT_PRICES: report,
    Tool.PRICE_KEY: key,
    Tool.AGE_MARKDOWN: aged,
}
TASKS = dict.fromkeys(Task, task.verify_task)


def verify_input(tool, value):
    return TOOLS[Tool(tool)].verify_input(value)


def verify_output(tool, input_value, output_value, workspace):
    return TOOLS[Tool(tool)].verify_output(input_value, output_value, workspace)


def verify_task(task, arguments, output, reference, workspace):
    return TASKS[Task(task)](arguments, output, reference, workspace)
