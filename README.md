# Thrift Markdown

A `nanoagent.plugin/v0001` plugin that asks an agent to price a thrift store's floor on one
store day, under two markdown rules that interact: an item's age, and the colour of the week.
Store days are plain integers counted from opening, so nothing here touches a calendar, a clock
or a timezone. Money is held as `Decimal` and written as a decimal string, never as a float. No
network: everything is read from a file in the workspace.

The inventory is **invented** and committed to the repository.

## Tools

| Name | Kind | Does | Code |
|---|---|---|---|
| `read_inventory` | tool | Reads the file in one call: the markdown rules, the rotation, the query day and every item | `src/plugin/pricing.py` |
| `report_prices` | tool | Merges the lines it is given into this run's report and returns the merged report | `src/plugin/report.py` |
| `price_key` | tool | Every item's status and price on the query day, and the week's colour | `src/plugin/pricing.py` |
| `age_markdown` | tool | Every item priced from the age schedule alone | `src/plugin/pricing.py` |
| `price-day` | task | Price the floor: runner `agent`, reference `price_key` | `verifier/task.py` |

The agent applies the pricing rules itself. No tool it can call prices an item the way the task
asks, and `age_markdown` is the distractor: it is honest about applying the age schedule and
never looking at the colour of the week, which makes its answer wrong for exactly the items
wearing that colour. On the committed inventory, copying it straight through scores **9 of 12**.

The prescribed path is four calls: `read_inventory`, then `report_prices` twice — at most six
items each — then `submit`. `report_prices` merges, so the halves accumulate into one report and
`complete` turns true on the second.

The split is not cosmetic. Pricing twelve items under two interacting rules costs more reasoning
than a modest output budget holds, and a model that overruns it returns a reply with no tool
call, which ends the run with nothing submitted — the harness has no retry for that, so extra
steps do not rescue it and only the per-step output budget does.

Measured against `deepseek/deepseek-v4-flash-0731` at the host's published plugin limits
(`max_steps` 6, `max_tokens` 2,048), over 40 runs across both inventory files:

| Plan | Runs | Submitted | Scored 1.00 |
|---|---|---|---|
| One `report_prices` for all twelve | 9 | 7 | 7 |
| Two calls, six items each | 40 | 39 | 38 |

The one run that did not submit, and both of the two under the single-call plan, failed the same
way: an empty reply at the step after `read_inventory`, before any report. The budget's cliff
sits well below production — 4 of 5 runs submitted at 1,536 tokens and 1 of 5 at 1,280 — so
2,048 leaves roughly a third of headroom. Reporting four items a call instead of six was tried
and did not help (2 of 6 at 1,280), because the model reasons about the whole inventory in the
step after reading it however many items that step goes on to report.

The run that scored 0.92 priced `t10` at $0.60 instead of the $0.50 floor: the task
discriminating, not the harness failing.

## The rules

1. **Age.** An item's age is `query day - tagged day`, in days. Its age markdown is **0%** for
   ages 0–13, **25%** for 14–27, **50%** for 28–41, and at age **42 or more** the item is
   `PULLED` and has no price at all.
2. **Colour of the week.** Weeks are numbered from opening: `week = (day - 1) // 7`, so days 1–7
   are week 0 and day 8 opens week 1. The colour of the week is
   `rotation[week % len(rotation)]`, and every item with that tag colour gets **50% off**.
3. **Discounts never stack.** An item gets the **larger** of its age markdown and the colour-of-
   the-week discount, never the sum. **If they are equal the status is `COLOR_OF_THE_WEEK`**, so
   `MARKED_DOWN` means the age alone took more off. A pulled item is pulled regardless of colour.
4. **Price.** The original price times `(1 - discount)`, **rounded half up to the cent**, with a
   minimum price of **$0.50**: a price that works out lower is reported as $0.50, but an item
   whose original price is already under $0.50 keeps that original price. The status still names
   the discount that was applied, even where the floor swallows it.
5. **An invalid inventory.** An item tagged **after** the query day, or with a tag colour the
   store does not stock, makes the file invalid. There is no status for such an item, so it
   fails the `sources` check and the run scores 0 rather than being priced some other way.

The age bands and the pull age are read from the file rather than fixed in code, and
`pull_age` must be **the day after the last band**: a gap would leave an age the schedule says
nothing about and the pull age has not reached, which no rule would price.

## A worked example

The committed `tests/fixtures/inventory.json`, cut to three items:

```text
rotation  blue, pink, yellow, green, orange        query day 49
week = (49 - 1) // 7 = 6      6 % 5 = 1      colour of the week = pink
bands: ages 0-13 -> 0%,  14-27 -> 25%,  28-41 -> 50%,  42+ -> pulled

item  colour  original  tagged  age   age%  colour%  taken   status             price
t07   pink      15.00      19    30    50%     50%     50%   COLOR_OF_THE_WEEK   7.50
t02   blue      12.00      35    14    25%      0%     25%   MARKED_DOWN         9.00
t06   pink      18.00       4    45      -      50%      -   PULLED              none
```

`t07` is the no-stacking tie: 50% off by age and 50% off by colour come to 50%, not 75%, and
rule 3 makes the status read `COLOR_OF_THE_WEEK`. `t06` wears the week's colour too and is still
pulled, because 42 days ends it whatever colour it is.

Two more from the same file carry the arithmetic: `t09` is $1.90 at 25% off, which is **1.4250
exactly** and rounds half up to **$1.43** (half even would give $1.42); `t10` is $0.80 at 50%
off, which works out to $0.40 and is reported at the **$0.50** floor.

`tests/fixtures/inventory_next.json` holds the same twelve items one day later, on day 49's
neighbour day 50. Day 49 ends week 6 and day 50 opens week 7, so the colour of the week moves
from pink to yellow and **seven of the twelve lines change**.

## The verdict

`verify_task` decides a `price-day` submission on 12 constraints, in order. A failure among the
first 9 scores 0; past them the score is **the share of items priced correctly**, where correct
means the status **and** the price are both right.

| # | Constraint | Holds when |
|---|---|---|
| 1 | `answer-key` | The answer key is for this task's inventory |
| 2 | `sources` | The inventory file is well formed |
| 3 | `answer-key-right` | The answer key's lines are the day's prices |
| 4 | `this-run` | The report names a run of this workspace |
| 5 | `read-inventory` | read_inventory read this task's inventory in this run |
| 6 | `report-saved` | report_prices saved this run's report for this task |
| 7 | `submitted-task` | The submitted report is for this task |
| 8 | `submitted-shape` | The submitted report is well formed |
| 9 | `submitted-as-saved` | The submitted report equals the saved report |
| 10 | `all-items` | Every item is priced exactly once |
| 11 | `status-exact` | Every item's status is the one the rules give |
| 12 | `price-exact` | Every item's price is the one the rules give, and null exactly when PULLED |

An item is right or wrong, never half: a line with the right price under the wrong status is
wrong. That is what makes the colour of the week worth getting right even on an item where it
changes no number — `t07` prices at $7.50 either way, and only the status says whether rule 3's
tie was read the right way round.

The verifier never runs a model. It reads the file itself in `verifier/rules.py`, which shares
no code with the plugin **and no number type either**: the plugin holds money as `Decimal` and
rounds with `ROUND_HALF_UP`, while the verifier works in whole cents and settles the rounding
with one integer comparison. A tool and the check of that tool therefore cannot be wrong in the
same way. `tests/test_verifier.py` runs the two against 1,000 random inventories and asserts
they agree, and another 500 against the rules' own invariants.

## Layout

```text
.
├── nanoagent.yaml   # manifest (a slimconfig ManifestConfig): id, runtime, permissions, tools, tasks
├── contract.py      # each tool's and task's typed input and output: slimconfig Output classes
├── README.md
├── LICENSE
├── pyproject.toml
├── uv.lock
├── .gitignore
├── .env             # environment variable NAMEs this plugin needs, never values
├── src/plugin/      # the MCP server: __main__.py, its IMPLEMENTATIONS, and the plugin's own modules
├── tests/           # the suite, with the invented inventories under fixtures/
├── ui/              # how the page draws the outputs: renderers.js and renderers.css
├── product/         # the product page a catalog shows: product.yaml and icon.svg
└── verifier/        # deterministic verifier package
```

`contract.py` is the one place a value's shape is declared. Its `Output` classes are the JSON
Schemas the server offers and the agent sees, and every input and output is built into its class
on the way in and out. A tool that fails raises; NanoAgent sees an MCP error.

The twelve committed items exist to carry one boundary each — age 13 against 14, age 41 against
42, age 0, the no-stacking tie, the colour beating a 25% age markdown, a pulled item of the
week's colour, a price that rounds at exactly half a cent, a discount that would fall below the
floor, and an item that starts below it. `tests/test_data.py` pins every expected status and
price in a table **derived on paper from the rules above**, so the two implementations and the
hand arithmetic all have to agree.

## Develop and run

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
```

Publishing checks every plugin rule: push the plugin to a public GitHub repository
and submit its URL on RUSH Lab.
