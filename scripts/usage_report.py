"""Run-usage reporting for the dev-skills feature chain.

Reads Claude Code's own session transcripts — which already record a per-request
`usage` block and a timestamp on every assistant entry — and turns the slice
between a run's start marker and now into a token, timing and cost report. The
log of those reports then sums into one report per feature cycle.

Stdlib only, deliberately: this is invoked as the system `python3`, which is not
the project's uv-managed virtualenv, so a third-party import would pass under
`uv run pytest` and fail in production.

Everything above the argument parsing is pure except the functions whose names
say otherwise (`write_start`, `read_start`, `append_log`, `apply_tracker`,
`apply_cycle`).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from dataclasses import astuple, dataclass, fields
from itertools import zip_longest
from datetime import datetime, timezone
from html import escape
from pathlib import Path

# `slug` reaches a filename, so it is validated before any path is built with
# it. `session_id` comes from the environment and reaches the same filename.
SLUG_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
SESSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

# A gap longer than this that ends at a `user` entry is the user thinking, not
# the run working, so it comes out of `run time` but stays in `elapsed`.
USER_WAIT_SECONDS = 30

# The fields summed per column. Ordered as the report renders them.
NUMERIC_FIELDS = (
    "requests",
    "input_tokens",
    "output_tokens",
    "thinking_tokens",
    "cache_write",
    "ephemeral_1h",
    "ephemeral_5m",
    "cache_read",
    "web_search",
    "web_fetch",
)

# API list prices in USD per million tokens, pinned rather than fetched (the
# script makes no network calls); the date prints under every reported cost.
# Each row: input, cache write 5m, cache write 1h, cache read, output.
PRICING_AS_OF = "2026-11-10"

PRICES = {
    model: rates
    for models, rates in (
        (("claude-fable-5-2", "claude-mythos-5-2"), (8, 10, 16, 0.20, 40)),
        (("claude-fable-5-1", "claude-mythos-5-1"), (10, 12.50, 20, 0.25, 50)),
        (("claude-fable-5", "claude-mythos-5"), (10, 12.50, 20, 1, 50)),
        (("claude-opus-5-5",), (4, 5, 8, 0.20, 20)),
        (("claude-opus-5", "claude-opus-4-8", "claude-opus-4-7", "claude-opus-4-6",
          "claude-opus-4-5"), (5, 6.25, 10, 0.50, 25)),
        (("claude-opus-4-1", "claude-opus-4"), (15, 18.75, 30, 1.50, 75)),
        (("claude-sonnet-5-5",), (2, 2.50, 4, 0.10, 10)),
        (("claude-sonnet-5",), (2, 2.50, 4, 0.20, 10)),
        (("claude-sonnet-4-6", "claude-sonnet-4-5", "claude-sonnet-4"),
         (3, 3.75, 6, 0.30, 15)),
        (("claude-haiku-4-5",), (1, 1.25, 2, 0.10, 5)),
    )
    for model in models
}

# (threshold, rates for a prompt at or below it, rates above it), where a
# request's prompt is its input + cache write + cache read tokens.
TIERED_PRICES = {
    "claude-haiku-5-5": (
        100_000, (0.10, 0.125, 0.20, 0.01, 0.50), (0.50, 0.625, 1, 0.05, 2.50)
    ),
}

# Fast mode's (input, output) only: its cache rates keep the model's own
# multipliers over input, so they are derived rather than stored.
FAST_PRICES = {
    "claude-fable-5-2": (16, 80),
    "claude-mythos-5-2": (16, 80),
    "claude-opus-5-5": (8, 40),
    "claude-opus-5": (10, 50),
    "claude-opus-4-8": (10, 50),
}

WEB_SEARCH_USD = 0.01

# The harness's own placeholder entries, not API requests.
SYNTHETIC = "<synthetic>"


@dataclass(frozen=True)
class Cost:
    """USD by token type, for one request or a sum of them."""

    input: float = 0.0
    cache_write_5m: float = 0.0
    cache_write_1h: float = 0.0
    cache_read: float = 0.0
    output: float = 0.0
    web_search: float = 0.0

    def __add__(self, other: "Cost") -> "Cost":
        return Cost(*(a + b for a, b in zip(astuple(self), astuple(other))))

    @property
    def total(self) -> float:
        return sum(astuple(self))

    def as_log(self) -> dict:
        """Six-decimal parts, and a `total` summed from them so the line adds up."""
        parts = {f.name: round(getattr(self, f.name), 6) for f in fields(self)}
        parts["total"] = round(sum(parts.values()), 6)
        return parts


@dataclass(frozen=True)
class Usage:
    """One column's worth of aggregated usage."""

    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    cache_write: int = 0
    ephemeral_1h: int = 0
    ephemeral_5m: int = 0
    cache_read: int = 0
    web_search: int = 0
    web_fetch: int = 0
    models: tuple[str, ...] = ()
    service_tier: str | None = None
    speed: str | None = None
    cost: Cost = Cost()
    unpriced: tuple[tuple[str, int], ...] = ()  # (normalised model, requests)

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            models=tuple(sorted(set(self.models) | set(other.models))),
            service_tier=self.service_tier or other.service_tier,
            speed=self.speed or other.speed,
            cost=self.cost + other.cost,
            unpriced=_merge_tallies(self.unpriced, other.unpriced),
            **{f: getattr(self, f) + getattr(other, f) for f in NUMERIC_FIELDS},
        )


def _merge_tallies(*tallies) -> tuple:
    """Sum (model, count) tallies — pairs or mappings — sorted by model."""
    merged = Counter()
    for tally in tallies:
        merged.update(dict(tally))
    return tuple(sorted(merged.items()))


@dataclass(frozen=True)
class Timings:
    elapsed_seconds: int = 0
    run_seconds: int = 0
    request_seconds: int = 0


@dataclass(frozen=True)
class RunMetrics:
    main: Usage
    subagents: Usage
    total: Usage
    timings: Timings
    subagent_count: int = 0

    @property
    def output_tokens_per_second(self):
        return throughput(self.total.output_tokens, self.timings.request_seconds)


def _parse_ts(value):
    """Parse a transcript timestamp, tolerating the trailing `Z` form.

    Python 3.10's `datetime.fromisoformat` rejects `2026-08-21T14:18:57.924Z`,
    which is exactly what the transcript writes, and 3.10 is this repo's floor.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _seconds(start, end) -> int:
    """Whole seconds from start to end, clamped at 0 if the clock went back."""
    return max(0, round((end - start).total_seconds()))


def _int(mapping, key) -> int:
    value = mapping.get(key) if isinstance(mapping, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _number(mapping, key) -> float:
    value = mapping.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return float(value)


def resolve_transcript(session_id: str, config_dir):
    """The main transcript for a session, or None.

    Globs rather than re-deriving the project directory's cwd encoding, which is
    undocumented and would be one more thing to keep in step with the harness.
    """
    matches = sorted(Path(config_dir).glob(f"projects/*/{session_id}.jsonl"))
    return matches[0] if matches else None


def iter_entries(path):
    """Stream a JSONL transcript, skipping lines that do not parse.

    Streamed rather than loaded: transcripts reach several megabytes.
    """
    try:
        handle = open(path, "r", encoding="utf-8", errors="replace")
    except OSError:
        return
    with handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if isinstance(entry, dict):
                yield entry


def window_entries(entries, start, end) -> list:
    """Entries whose timestamp falls in [start, end]. Both bounds inclusive."""
    kept = []
    for entry in entries:
        stamp = _parse_ts(entry.get("timestamp"))
        if stamp is not None and start <= stamp <= end:
            kept.append(entry)
    return kept


def _request_counts(usage: dict) -> dict:
    """One request's usage block, keyed like `NUMERIC_FIELDS` less `requests`."""
    creation = usage.get("cache_creation")
    tools = usage.get("server_tool_use")
    return {
        "input_tokens": _int(usage, "input_tokens"),
        "output_tokens": _int(usage, "output_tokens"),
        "thinking_tokens": _int(usage.get("output_tokens_details"), "thinking_tokens"),
        "cache_write": _int(usage, "cache_creation_input_tokens"),
        "ephemeral_1h": _int(creation, "ephemeral_1h_input_tokens"),
        "ephemeral_5m": _int(creation, "ephemeral_5m_input_tokens"),
        "cache_read": _int(usage, "cache_read_input_tokens"),
        "web_search": _int(tools, "web_search_requests"),
        "web_fetch": _int(tools, "web_fetch_requests"),
    }


def normalise_model(model: str) -> str:
    """One key per model: lower-case, no `[…]` suffix, no `-YYYYMMDD` date."""
    name = re.sub(r"\[[^\]]*\]$", "", model.strip().lower())
    return re.sub(r"-\d{8}$", "", name)


def price_request(model, usage: dict) -> Cost | None:
    """One request's cost, or None when it cannot be priced exactly.

    Unpriced rather than estimated: a model not in the table, fast mode on a
    model with no fast price, or cache-write tokens not fully attributed to the
    two lifetimes, which are priced differently.
    """
    if not isinstance(model, str):
        return None
    return _price(
        normalise_model(model), _request_counts(usage), usage.get("speed") == "fast"
    )


def _price(name: str, counts: dict, fast: bool) -> Cost | None:
    """`price_request` over counts keyed like `NUMERIC_FIELDS`, so a log line's
    totals price through the same rules as one request."""
    if counts["ephemeral_5m"] + counts["ephemeral_1h"] != counts["cache_write"]:
        return None

    if name in TIERED_PRICES:
        threshold, low, high = TIERED_PRICES[name]
        prompt = counts["input_tokens"] + counts["cache_write"] + counts["cache_read"]
        rates = low if prompt <= threshold else high
    elif name in PRICES:
        rates = PRICES[name]
    else:
        return None

    if fast:
        if name not in FAST_PRICES:
            return None
        fast_input, fast_output = FAST_PRICES[name]
        scale = fast_input / rates[0]
        rates = tuple(rate * scale for rate in rates[:4]) + (fast_output,)

    tokens = (counts["input_tokens"], counts["ephemeral_5m"], counts["ephemeral_1h"],
              counts["cache_read"], counts["output_tokens"])
    return Cost(
        *(count * rate / 1_000_000 for count, rate in zip(tokens, rates)),
        web_search=counts["web_search"] * WEB_SEARCH_USD,
    )


def aggregate(entries) -> Usage:
    """Sum the usage blocks of the assistant entries, one count per request.

    The transcript writes several snapshots per request with identical usage, so
    deduplication by `requestId` is mandatory — without it every figure inflates.
    Pricing happens here for the same reason.
    """
    seen = set()
    totals = dict.fromkeys(NUMERIC_FIELDS, 0)
    models = set()
    service_tier = speed = None
    cost = Cost()
    unpriced = Counter()

    for entry in entries:
        if entry.get("type") != "assistant":
            continue
        message = entry.get("message")
        usage = message.get("usage") if isinstance(message, dict) else None
        if not isinstance(usage, dict):
            continue
        key = entry.get("requestId") or entry.get("uuid") or object()
        if key in seen:
            continue
        seen.add(key)

        counts = _request_counts(usage)
        totals["requests"] += 1
        for field, value in counts.items():
            totals[field] += value

        model = message.get("model")
        if isinstance(model, str):
            models.add(model)
        service_tier = service_tier or usage.get("service_tier")
        speed = speed or usage.get("speed")

        if model == SYNTHETIC or not any(counts.values()):
            continue
        priced = price_request(model, usage)
        if priced is None:
            name = normalise_model(model) if isinstance(model, str) else ""
            unpriced[name or "unknown"] += 1
        else:
            cost += priced

    return Usage(
        models=tuple(sorted(models)),
        service_tier=service_tier,
        speed=speed,
        cost=cost,
        unpriced=_merge_tallies(unpriced),
        **totals,
    )


def timings(entries) -> Timings:
    """Wall clock, working time and summed per-request time over one transcript.

    `request_seconds` runs from the entry preceding a request to that request's
    last entry — the denominator throughput is defined against, because it
    excludes tool execution and file I/O the model did not spend generating.
    """
    stamped = []
    for entry in entries:
        stamp = _parse_ts(entry.get("timestamp"))
        if stamp is not None:
            stamped.append((stamp, entry))
    if not stamped:
        return Timings()

    elapsed = _seconds(stamped[0][0], stamped[-1][0])

    waits = 0
    for (previous, _), (stamp, entry) in zip(stamped, stamped[1:]):
        gap = _seconds(previous, stamp)
        if gap > USER_WAIT_SECONDS and entry.get("type") == "user":
            waits += gap

    opens, closes = {}, {}
    for index, (stamp, entry) in enumerate(stamped):
        if entry.get("type") != "assistant":
            continue
        key = entry.get("requestId")
        if key is None:
            continue
        opens.setdefault(key, index)
        closes[key] = stamp

    request_seconds = 0
    for key, index in opens.items():
        preceding = stamped[index - 1][0] if index > 0 else stamped[index][0]
        request_seconds += _seconds(preceding, closes[key])

    return Timings(elapsed, max(0, elapsed - waits), request_seconds)


def throughput(output_tokens: int, request_seconds: int):
    """Output tokens per second, or None when there is no request time."""
    if not request_seconds:
        return None
    return round(output_tokens / request_seconds, 1)


def collect(transcript, subagent_dir, start, end) -> RunMetrics:
    """Aggregate one run's window across the main transcript and its subagents.

    The subagents directory is flat — depth-2 agents sit beside depth-1 ones —
    so a time-window scan of the listing captures every depth with no traversal.
    """
    main_entries = window_entries(iter_entries(transcript), start, end)
    main_usage = aggregate(main_entries)
    main_timings = timings(main_entries)

    subagent_usage = Usage()
    subagent_request_seconds = 0
    subagent_count = 0
    for path in _subagent_files(subagent_dir):
        entries = window_entries(iter_entries(path), start, end)
        if not entries:
            continue
        subagent_count += 1
        subagent_usage = subagent_usage + aggregate(entries)
        subagent_request_seconds += timings(entries).request_seconds

    return RunMetrics(
        main=main_usage,
        subagents=subagent_usage,
        total=main_usage + subagent_usage,
        timings=Timings(
            elapsed_seconds=main_timings.elapsed_seconds,
            run_seconds=main_timings.run_seconds,
            request_seconds=main_timings.request_seconds + subagent_request_seconds,
        ),
        subagent_count=subagent_count,
    )


def _subagent_files(subagent_dir):
    if subagent_dir is None:
        return []
    try:
        return sorted(Path(subagent_dir).glob("agent-*.jsonl"))
    except OSError:
        return []


@dataclass(frozen=True)
class RunContext:
    """Everything the report needs that the transcript cannot supply."""

    slug: str
    repo_name: str = ""
    timestamp: str = ""
    feature_version: int | None = None
    outcome: str = "completed"
    evals_included: bool = False
    cwd: str | None = None


# Total-column-only rows. Their keys are deliberately not Usage field names, so
# a row's source is unambiguously one or the other.
_TOTAL_ONLY = {
    "elapsed": lambda m: _duration(m.timings.elapsed_seconds),
    "run": lambda m: _duration(m.timings.run_seconds),
    "tok/s": lambda m: _rate(m.output_tokens_per_second),
}

# The report's shape, from the accepted grouped-columns mockup: (group, rows),
# each row (label, source, indented). Both renderers walk this one spec, so the
# chat table and the tracker table cannot drift apart.
#
# The spec is two halves because the report renders them side by side — the
# small total-only groups on the left, the token breakdown on the right. Nine
# rows and eight rows zip into a nine-row table instead of a seventeen-row one.
_LEFT_GROUPS = (
    ("time", (
        ("elapsed", "elapsed", False),
        ("run time", "run", False),
    )),
    ("requests", (
        ("model", "requests", False),
        ("web_search", "web_search", False),
        ("web_fetch", "web_fetch", False),
    )),
    ("throughput", (
        ("output tok/s", "tok/s", False),
    )),
)

_RIGHT_GROUPS = (
    ("tokens", (
        ("input_tokens", "input_tokens", False),
        ("output_tokens", "output_tokens", False),
        ("thinking_tokens", "thinking_tokens", True),
        ("cache_write", "cache_write", False),
        ("ephemeral_1h", "ephemeral_1h", True),
        ("ephemeral_5m", "ephemeral_5m", True),
        ("cache_read", "cache_read", False),
    )),
)

# Marks a sub-total row in the chat table. A literal glyph rather than the
# `&nbsp;&nbsp;` this replaced: chat renders the table's markdown but not HTML
# entities, so the entity reached the terminal verbatim. The tracker has CSS
# for the job (`tr.sub`) and needs no glyph.
_SUB = "\u21b3 "

# The four cells of a blank row, used to pad the shorter half.
_BLANK = ("", "", "", "")


def _duration(seconds) -> str:
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{seconds}s"


def _rate(value) -> str:
    return "—" if value is None else f"{value:.1f}"


def _money(value: float, plus: bool = False) -> str:
    """`$6.78`, or `$6.78+` when unpriced requests are left out of the figure."""
    return f"${value:.2f}{'+' if plus else ''}"


def _spent(usage: Usage) -> str:
    return _money(usage.cost.total, bool(usage.unpriced))


def _plural(count: int, noun: str) -> str:
    return f"{count:,} {noun}{'' if count == 1 else 's'}"


def _cells(metrics: RunMetrics, source: str) -> tuple:
    """The three column cells for one row, already formatted."""
    if source in _TOTAL_ONLY:
        return ("—", "—", _TOTAL_ONLY[source](metrics))
    columns = (metrics.main, metrics.subagents, metrics.total)
    return tuple(f"{getattr(column, source):,}" for column in columns)


@dataclass(frozen=True)
class _Row:
    """One rendered table row: a stage table half's, or the cycle table's."""

    label: str
    cells: tuple  # all "" for a group heading
    kind: str  # "group" | "sub" | "rate" | "cost" | ""


def _half(metrics: RunMetrics, groups) -> list:
    """One column half's rows, group headings included, in render order."""
    rows = []
    for group, group_rows in groups:
        rows.append(_Row(group, ("", "", ""), "group"))
        for label, source, indented in group_rows:
            kind = "sub" if indented else "rate" if source == "tok/s" else ""
            rows.append(_Row(label, _cells(metrics, source), kind))
    return rows


def _md_cells(row: _Row) -> tuple:
    """A row's markdown cells: the metric name and its figures."""
    if row.kind == "group":
        return (f"**{row.label}**",) + row.cells
    if row.kind == "cost":
        return (f"**{row.label}**",) + row.cells[:-1] + (f"**{row.cells[-1]}**",)
    label = f"{_SUB}{row.label}" if row.kind == "sub" else row.label
    return (label,) + row.cells


def _md_row(cells) -> str:
    # An empty cell renders as `| |` rather than `|  |`, so a group
    # heading's row reads the same as it did when it spanned the table.
    return "|" + "".join(f" {cell} |" if cell else " |" for cell in cells)


def render_markdown(metrics: RunMetrics, footer: RunContext) -> str:
    """The chat table. Chat renders markdown tables natively, so this is one."""
    header = "| metric | main | subagents | total |"
    lines = [
        "### Run usage",
        "",
        header + header[1:],
        "|---|---:|---:|---:|---|---:|---:|---:|",
    ]
    halves = (_half(metrics, _LEFT_GROUPS), _half(metrics, _RIGHT_GROUPS))
    for left, right in zip_longest(*halves):
        lines.append(_md_row(
            (_md_cells(left) if left else _BLANK) + (_md_cells(right) if right else _BLANK)
        ))
    lines += ["", _footer_line(metrics, footer)]
    return "\n".join(lines)


def _footer_line(metrics: RunMetrics, footer: RunContext) -> str:
    tier = metrics.total.service_tier or "unknown"
    speed = metrics.total.speed or "unknown"
    return (
        f"{tier} tier · {speed} speed · {metrics.subagent_count} subagents "
        f"· outcome {footer.outcome}"
    )


def render_tracker_html(metrics: RunMetrics) -> tuple:
    """The tracker panel's headline chip and usage table, as a pair of strings.

    The chip must never read `Updated <date>`: feature-list derives a feature's
    last-activity date by matching that shape in the tracker's chips.
    """
    cost = f" · {_spent(metrics.total)}" if metrics.total.cost.total > 0 else ""
    chip = (
        '<span class="chip usage">'
        f"{_duration(metrics.timings.elapsed_seconds)} · "
        f"{metrics.total.output_tokens:,} out · "
        f"{_rate(metrics.output_tokens_per_second)} tok/s{cost}</span>"
    )

    halves = (_LEFT_GROUPS, _RIGHT_GROUPS)
    tables = "\n".join(_tracker_table(metrics, groups) for groups in halves)
    return chip, f'<div class="usage-pair">\n{tables}\n</div>'


def _tracker_table(metrics: RunMetrics, groups) -> str:
    """One half, as a table. The pair sits side by side in `.usage-pair`."""
    return _html_table(("Metric", "Main", "Subagents", "Total"), _half(metrics, groups))


def _html_table(headers, rows) -> str:
    """A `table.usage` of rendered rows, shared by the stage and cycle tables."""
    lines = [
        '<table class="usage">',
        "<thead><tr>" + "".join(f"<th>{header}</th>" for header in headers)
        + "</tr></thead>",
        "<tbody>",
    ]
    for row in rows:
        if row.kind == "group":
            lines.append(
                f'<tr class="grp"><td colspan="{len(headers)}">'
                f"{escape(row.label.capitalize())}</td></tr>"
            )
            continue
        css = f' class="{"sub" if row.kind == "sub" else "tp"}"' if row.kind else ""
        cells = "".join(f"<td>{escape(cell)}</td>" for cell in row.cells)
        lines.append(f"<tr{css}><td>{escape(row.label)}</td>{cells}</tr>")
    lines += ["</tbody>", "</table>"]
    return "\n".join(lines)


def _columns(metrics: RunMetrics, field: str) -> dict:
    return {
        "main": getattr(metrics.main, field),
        "subagents": getattr(metrics.subagents, field),
        "total": getattr(metrics.total, field),
    }


def log_entry(metrics: RunMetrics, context: RunContext) -> dict:
    """The one JSONL line for this run.

    Built from an explicit field list rather than by copying and filtering an
    entry, so no conversation content can reach the log by omission (design §5
    Security).
    """
    entry = {
        "repo_name": context.repo_name,
        "timestamp": context.timestamp,
        "slug": context.slug,
        "feature_version": context.feature_version,
        "outcome": context.outcome,
        "evals_included": context.evals_included,
        "elapsed_seconds": metrics.timings.elapsed_seconds,
        "run_seconds": metrics.timings.run_seconds,
        "request_seconds": metrics.timings.request_seconds,
        "output_tokens_per_second": metrics.output_tokens_per_second,
        "subagent_count": metrics.subagent_count,
        "service_tier": metrics.total.service_tier,
        "speed": metrics.total.speed,
        "models": list(metrics.total.models),
    }
    for field in ("requests", "output_tokens", "thinking_tokens", "input_tokens",
                  "cache_write", "ephemeral_1h", "ephemeral_5m", "cache_read",
                  "web_search", "web_fetch"):
        entry[field] = _columns(metrics, field)
    entry["cwd"] = context.cwd
    entry["pricing_as_of"] = PRICING_AS_OF
    entry["cost"] = metrics.total.cost.as_log()
    entry["unpriced"] = dict(metrics.total.unpriced)
    return entry


# The tracker tokens this reporter owns, one (chip, table) pair per chain
# stage. Sole ownership is what makes the replace-on-re-run behaviour below
# safe; tests/test_static.py pins these names against the shipped template.
TRACKER_TOKENS = {
    "feature-storm": ("{{BRAINSTORMING_USAGE_CHIP}}", "{{BRAINSTORMING_USAGE}}"),
    "feature-design": ("{{DESIGN_USAGE_CHIP}}", "{{DESIGN_USAGE}}"),
    "feature-plan": ("{{PLAN_USAGE_CHIP}}", "{{PLAN_USAGE}}"),
    "feature-implement": ("{{IMPLEMENTATION_USAGE_CHIP}}", "{{IMPLEMENTATION_USAGE}}"),
}

# The Usage tab's whole body. Kept out of TRACKER_TOKENS, which is one
# (chip, table) pair per stage, but owned and replaced the same way.
CYCLE_TOKEN = "{{CYCLE_USAGE}}"


@dataclass(frozen=True)
class StageTotals:
    """One chain stage's logged runs summed; also the cycle's total column."""

    usage: Usage = Usage()
    runs: int = 0
    halted: int = 0
    elapsed_seconds: int = 0
    evals_included: bool = False

    def __add__(self, other: "StageTotals") -> "StageTotals":
        return StageTotals(
            usage=self.usage + other.usage,
            runs=self.runs + other.runs,
            halted=self.halted + other.halted,
            elapsed_seconds=self.elapsed_seconds + other.elapsed_seconds,
            evals_included=self.evals_included or other.evals_included,
        )


def select_cycle(entries, version, cwd) -> list:
    """Every log line of one feature version run in this directory, any outcome.

    Directories compare as real paths, so `/var` and `/private/var` or a
    symlinked checkout still match. A line logged before `cwd` was recorded
    falls back to the directory's name.
    """
    here = os.path.realpath(cwd)
    name = os.path.basename(here)
    chosen = []
    for entry in entries:
        if version is None or entry.get("feature_version") != version:
            continue
        logged = entry.get("cwd")
        if isinstance(logged, str) and logged:
            if os.path.realpath(logged) != here:
                continue
        elif entry.get("repo_name") != name:
            continue
        chosen.append(entry)
    return chosen


def _line_totals(entry) -> dict:
    """A log line's `total` column for each of `NUMERIC_FIELDS`."""
    return {field: _int(entry.get(field), "total") for field in NUMERIC_FIELDS}


def _line_models(entry) -> tuple:
    """A log line's models, normalised, less the harness's placeholder."""
    models = entry.get("models")
    names = {normalise_model(m) for m in models if isinstance(m, str)} \
        if isinstance(models, list) else set()
    names.discard(SYNTHETIC)
    return tuple(sorted(names))


def entry_cost(entry) -> tuple:
    """(Cost, unpriced tally) for one log line.

    A line written before costs were logged is priced from its totals only when
    that is exact: one flat-rate model at standard speed, with every cache-write
    token attributed to a lifetime. The Haiku 5.5 tier is decided per request,
    which totals cannot recover. Anything else counts its requests as unpriced
    under its models joined by `, ` (design §3 R25).
    """
    logged = entry.get("cost")
    if isinstance(logged, dict):
        tally = entry.get("unpriced")
        counts = {m: _int(tally, m) for m in tally} if isinstance(tally, dict) else {}
        return (
            Cost(*(_number(logged, part.name) for part in fields(Cost))),
            _merge_tallies({m: n for m, n in counts.items() if n}),
        )

    models, totals = _line_models(entry), _line_totals(entry)
    if len(models) == 1 and models[0] in PRICES and entry.get("speed") in (None, "standard"):
        priced = _price(models[0], totals, fast=False)
        if priced is not None:
            return priced, ()
    if not totals["requests"]:
        return Cost(), ()
    return Cost(), ((", ".join(models) or "unknown", totals["requests"]),)


def group_cycle(entries) -> dict:
    """The cycle's lines summed per chain stage, keyed in chain order."""
    stages = dict.fromkeys(TRACKER_TOKENS, StageTotals())
    for entry in entries:
        slug = entry.get("slug")
        if slug not in stages:
            continue
        cost, unpriced = entry_cost(entry)
        stages[slug] += StageTotals(
            usage=Usage(models=_line_models(entry), cost=cost, unpriced=unpriced,
                        **_line_totals(entry)),
            runs=1,
            halted=int(entry.get("outcome") == "halted"),
            elapsed_seconds=_int(entry, "elapsed_seconds"),
            evals_included=entry.get("evals_included") is True,
        )
    return stages


# The accepted stage-columns layout (design §5 The cycle report), walked by
# both cycle renderers so chat and tracker cannot drift apart. A token row's
# source is (Usage field, Cost part); thinking has no part, its cost being
# inside output's.
_CYCLE_ROWS = (
    ("tokens", "group", None),
    ("input", "", ("input_tokens", "input")),
    ("cache write 1h", "", ("ephemeral_1h", "cache_write_1h")),
    ("cache write 5m", "", ("ephemeral_5m", "cache_write_5m")),
    ("cache read", "", ("cache_read", "cache_read")),
    ("output", "", ("output_tokens", "output")),
    ("thinking", "sub", ("thinking_tokens", None)),
    ("web searches", "", ("web_search", "web_search")),
    ("cost", "cost", "cost"),
    ("run", "group", None),
    ("model", "", "model"),
    ("runs", "", "runs"),
    ("elapsed", "", "elapsed"),
)

# Rows whose total column stays empty: the stage costs' total is the cost
# column's to show, and models do not sum.
_STAGE_ONLY = ("cost", "model")


def _stage_name(slug: str) -> str:
    return slug.removeprefix("feature-")


def _short_model(model: str) -> str:
    return model.removeprefix("claude-")


def _cycle_figure(source, stage: StageTotals) -> str:
    """One stage cell, or a total-column cell, for a row source."""
    if isinstance(source, tuple):
        return f"{getattr(stage.usage, source[0]):,}"
    if source == "cost":
        return _spent(stage.usage)
    if source == "model":
        return " + ".join(map(_short_model, stage.usage.models))
    if source == "runs":
        return f"{stage.runs:,}"
    return _duration(stage.elapsed_seconds)


def _cycle_cost(source, total: StageTotals) -> str:
    """The cost column: each token type across the cycle, then the cycle."""
    if source == "cost":
        return _spent(total.usage)
    if not isinstance(source, tuple):
        return ""
    if source[1] is None:
        return "—"
    return _money(getattr(total.usage.cost, source[1]), bool(total.usage.unpriced))


def _cycle_rows(stages: dict, total: StageTotals) -> list:
    rows = []
    for label, kind, source in _CYCLE_ROWS:
        if kind == "group":
            rows.append(_Row(label, ("",) * (len(stages) + 2), kind))
            continue
        cells = [_cycle_figure(source, stage) if stage.runs else "—"
                 for stage in stages.values()]
        cells.append("" if source in _STAGE_ONLY else _cycle_figure(source, total))
        cells.append(_cycle_cost(source, total))
        rows.append(_Row(label, tuple(cells), kind))
    return rows


def _cycle_footnote(stages: dict, total: StageTotals) -> str:
    clauses = [f"API list prices as of {PRICING_AS_OF}, not subscription billing"]
    halted = [_stage_name(slug) for slug, stage in stages.items() if stage.halted]
    if halted:
        clauses.append(
            f"{_plural(total.halted, 'halted run')} included ({', '.join(halted)})"
        )
    evals = [_stage_name(slug) for slug, stage in stages.items() if stage.evals_included]
    if evals:
        clauses.append(f"evals included ({', '.join(evals)})")
    for models, count in total.usage.unpriced:
        names = ", ".join(map(_short_model, models.split(", ")))
        clauses.append(f"{names}: {_plural(count, 'request')} unpriced")
    return " · ".join(clauses)


def render_cycle_markdown(stages: dict, version, description=None) -> str:
    """The cycle report as chat prints it (design §5 The cycle report)."""
    total = sum(stages.values(), StageTotals())
    heading = f"### Cycle usage: v{version}" + (f" {description}" if description else "")
    lines = [
        heading,
        "",
        _md_row(("metric", *map(_stage_name, stages), "total", "cost")),
        "|---|" + "---:|" * (len(stages) + 2),
    ]
    lines += [_md_row(_md_cells(row)) for row in _cycle_rows(stages, total)]
    lines += ["", _cycle_footnote(stages, total)]
    return "\n".join(lines)


def render_cycle_html(stages: dict) -> str:
    """The tracker's Usage tab: two chips, the table and its footnote.

    Neither chip may read `Updated <date>`, for the reason `render_tracker_html`
    gives.
    """
    total = sum(stages.values(), StageTotals())
    ran = sum(1 for stage in stages.values() if stage.runs)
    cost = f"{_spent(total.usage)} · " if total.usage.cost.total > 0 else ""
    headers = ("Metric", *(_stage_name(slug).capitalize() for slug in stages),
               "Total", "Cost")
    return "\n".join([
        f'<p class="section-timestamp">{ran} of {len(stages)} stages · '
        f'{_plural(total.runs, "run")}</p>',
        f'<span class="chip usage">{cost}{_duration(total.elapsed_seconds)} · '
        f"{total.usage.output_tokens:,} out</span>",
        '<article class="panel-section">',
        '<h2 class="section-label">Cycle usage</h2>',
        f'<div class="usage-scroll">{_html_table(headers, _cycle_rows(stages, total))}</div>',
        f'<p class="usage-note">{escape(_cycle_footnote(stages, total))}</p>',
        "</article>",
    ])


def _now():
    """The clock, as one seam so tests can pin it."""
    return datetime.now(timezone.utc)


def _stamp(moment) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _config_dir():
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def _usage_dir(config_dir):
    return Path(config_dir) / "dev-skills" / "usage"


def _checked(slug: str, session_id: str) -> None:
    if not SLUG_PATTERN.match(slug or ""):
        raise ValueError(f"slug {slug!r} is not a valid stage slug")
    if not SESSION_PATTERN.match(session_id or ""):
        raise ValueError("session id is not a valid identifier")


def _marker_path(slug, session_id, state_dir):
    _checked(slug, session_id)
    return Path(state_dir) / f"{session_id}-{slug}.json"


def write_start(slug, session_id, started, state_dir, cwd=None):
    """Record where a run began. Returns the marker's path."""
    path = _marker_path(slug, session_id, state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "slug": slug,
        "session_id": session_id,
        "started": _stamp(started),
        "cwd": cwd if cwd is not None else os.getcwd(),
    }))
    return path


def read_start(slug, session_id, state_dir):
    """The start marker for this run, or None if there isn't a readable one."""
    try:
        path = _marker_path(slug, session_id, state_dir)
        marker = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return marker if isinstance(marker, dict) else None


def append_log(entry, log_path) -> None:
    """Append one JSON line.

    A single O_APPEND write below PIPE_BUF is atomic on POSIX, so two herdr
    sessions finishing a stage together cannot lose each other's entry — which
    a read-modify-write JSON array would (design §5 Data model).
    """
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry, separators=(",", ":")) + "\n"
    handle = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        os.write(handle, line.encode("utf-8"))
    finally:
        os.close(handle)


def _anchored(token: str, html: str) -> str:
    """Rendered content wrapped in the anchors a later run replaces between."""
    name = token.strip("{}")
    return f"<!-- usage:{name} -->{html}<!-- /usage:{name} -->"


def _substitute(text: str, token: str, html: str) -> str:
    """Fill a token, whether it is still literal or already rendered.

    The first run replaces the literal `{{TOKEN}}`; every run after that
    replaces whatever sits between the anchors, so a re-run shows the new
    figures rather than a second table (design §3 R10). These nine tokens have
    exactly one owner, which is what makes overwriting safe here when the rest
    of the plugin substitutes only-if-literal.
    """
    replacement = _anchored(token, html)
    if token in text:
        return text.replace(token, replacement)
    name = re.escape(token.strip("{}"))
    pattern = re.compile(f"<!-- usage:{name} -->.*?<!-- /usage:{name} -->", re.DOTALL)
    return pattern.sub(lambda _: replacement, text)


def _split_doc_comment(text: str) -> tuple[str, str]:
    """(leading doc comment, rendered body).

    The tracker template opens with an HTML comment legending every token by
    name, so those names must survive as literal text. They are also the only
    place a substitution would be actively destructive: the anchors carry a
    `-->` that would close the doc comment early and spill the rest of the
    legend onto the page as visible markup.
    """
    opened = text.find("<!--")
    if opened == -1:
        return "", text
    closed = text.find("-->", opened)
    if closed == -1:
        return "", text
    end = closed + len("-->")
    return text[:end], text[end:]


def _rewrite_body(tracker_path, change) -> bool:
    """Apply `change` to the tracker's body, never its legend, and write the
    result if it differs. False, silently, when nothing was written."""
    try:
        original = Path(tracker_path).read_text(encoding="utf-8")
    except OSError:
        return False
    legend, body = _split_doc_comment(original)
    text = legend + change(body)
    if text == original:
        return False
    try:
        Path(tracker_path).write_text(text, encoding="utf-8")
    except OSError:
        return False
    return True


def apply_tracker(tracker_path, slug, chip_html, table_html) -> bool:
    """Write this stage's usage into the tracker. Silent no-op if it can't.

    Blanks the other stages' tokens, and the Usage tab's, to an empty anchored
    region rather than to nothing at all: a region that has nothing to show yet
    must render as empty now and still be fillable later.
    """
    if slug not in TRACKER_TOKENS:
        return False

    def change(text):
        for stage, (chip_token, table_token) in TRACKER_TOKENS.items():
            if stage == slug:
                text = _substitute(text, chip_token, chip_html)
                text = _substitute(text, table_token, table_html)
            else:
                # Only while still literal: an anchored region belongs to the
                # stage that owns it, whether it holds that stage's figures or
                # is empty pending its first run.
                text = text.replace(chip_token, _anchored(chip_token, ""))
                text = text.replace(table_token, _anchored(table_token, ""))
        return text.replace(CYCLE_TOKEN, _anchored(CYCLE_TOKEN, ""))

    return _rewrite_body(tracker_path, change)


def apply_cycle(tracker_path, html) -> bool:
    """Rewrite the tracker's Usage tab. A tracker seeded before the tab existed
    has neither the token nor its anchors and is left untouched."""
    return _rewrite_body(tracker_path, lambda body: _substitute(body, CYCLE_TOKEN, html))


class _ArgError(Exception):
    """An argparse complaint, raised rather than exited on."""


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise _ArgError(message)


def _parse_args(argv):
    parser = _Parser(prog="usage_report.py", add_help=False)
    commands = parser.add_subparsers(dest="command", required=True)

    start = commands.add_parser("start", add_help=False)
    start.add_argument("--slug", required=True)

    report = commands.add_parser("report", add_help=False)
    report.add_argument("--slug", required=True)
    report.add_argument("--tracker")
    report.add_argument("--feature-version", type=int, default=None)
    report.add_argument("--outcome", choices=("completed", "halted"), default="completed")
    report.add_argument("--evals-included", action="store_true")
    report.add_argument("--cycle", action="store_true")

    cycle = commands.add_parser("cycle", add_help=False)
    cycle.add_argument("--feature-version", type=int, required=True)
    cycle.add_argument("--tracker")

    return parser.parse_args(argv)


def _run_start(args) -> None:
    session_id = os.environ.get("CLAUDE_CODE_SESSION_ID")
    if not session_id:
        return  # nothing to key a marker on; say nothing
    write_start(args.slug, session_id, _now(), _usage_dir(_config_dir()) / "state")


def _run_report(args) -> None:
    """The stage's own report, then the Usage tab and, with `--cycle`, the cycle.

    The cycle part runs even when the stage could not be measured: the chain
    has still stopped here, and the log holds every earlier run.
    """
    _report_stage(args)
    if args.feature_version is None:
        if args.cycle:
            print("usage report skipped — no feature version to report a cycle for")
        return
    if args.cycle or args.tracker:
        cycle = _cycle_report(args.feature_version, args.tracker)
        if args.cycle:
            print(cycle)


def _run_cycle(args) -> None:
    print(_cycle_report(args.feature_version, args.tracker))


def _cycle_report(version: int, tracker) -> str:
    """This directory's cycle report for a version, or its skip line. Rewrites
    the tracker's Usage tab on the way when one is given."""
    log = _usage_dir(_config_dir()) / "runs.jsonl"
    stages = group_cycle(select_cycle(iter_entries(log), version, os.getcwd()))
    if not any(stage.runs for stage in stages.values()):
        return f"usage report skipped — no logged runs for v{version} in this repo"
    if tracker:
        apply_cycle(tracker, render_cycle_html(stages))
    return render_cycle_markdown(stages, version, _description_from_tracker(tracker))


def _description_from_tracker(tracker) -> str | None:
    """`add-reminders`, from `…/feature-v7-add-reminders/feature-v7-tracker.html`."""
    if not tracker:
        return None
    match = re.match(r"feature-v\d+-(.+)$", Path(tracker).parent.name)
    return match.group(1) if match else None


def _report_stage(args) -> None:
    """Measure the run, print its table, log it and fill its stage tokens; or
    print one skip line."""
    session_id = os.environ.get("CLAUDE_CODE_SESSION_ID")
    if not session_id:
        print("usage report skipped — CLAUDE_CODE_SESSION_ID is not set")
        return

    config_dir = _config_dir()
    usage_dir = _usage_dir(config_dir)
    marker = read_start(args.slug, session_id, usage_dir / "state")
    if marker is None:
        print(
            "usage report skipped — no start marker for this run "
            "(cleared session, resumed run, or start never fired)"
        )
        return

    # Never guess a start time: a fabricated window gives a plausible wrong
    # number, which is worse than no number.
    start = _parse_ts(marker.get("started"))
    if start is None:
        print("usage report skipped — the start marker has no readable timestamp")
        return

    transcript = resolve_transcript(session_id, config_dir)
    if transcript is None:
        print("usage report skipped — no transcript for this session")
        return

    end = _now()
    metrics = collect(
        transcript, transcript.parent / session_id / "subagents", start, end
    )
    context = RunContext(
        slug=args.slug,
        repo_name=Path(marker.get("cwd") or ".").name,
        timestamp=_stamp(end),
        feature_version=args.feature_version,
        outcome=args.outcome,
        evals_included=args.evals_included,
        cwd=marker.get("cwd"),
    )

    print(render_markdown(metrics, context))

    try:
        append_log(log_entry(metrics, context), usage_dir / "runs.jsonl")
    except Exception as problem:
        print(f"usage report skipped — log write failed: {problem}")

    if args.tracker:
        apply_tracker(args.tracker, args.slug, *render_tracker_html(metrics))

    _marker_path(args.slug, session_id, usage_dir / "state").unlink(missing_ok=True)


def main(argv=None) -> int:
    """Always returns 0. Reporting must never fail the caller (design §3 R13)."""
    try:
        args = _parse_args(argv)
    except (_ArgError, SystemExit) as problem:
        print(f"usage report skipped — {problem}")
        return 0

    runners = {"start": _run_start, "report": _run_report, "cycle": _run_cycle}
    try:
        runners[args.command](args)
    except Exception as problem:
        print(f"usage report skipped — {problem}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
