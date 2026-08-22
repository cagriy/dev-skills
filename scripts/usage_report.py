"""Run-usage reporting for the dev-skills feature chain.

Reads Claude Code's own session transcripts — which already record a per-request
`usage` block and a timestamp on every assistant entry — and turns the slice
between a run's start marker and now into a token/timing report.

Stdlib only, deliberately: this is invoked as the system `python3`, which is not
the project's uv-managed virtualenv, so a third-party import would pass under
`uv run pytest` and fail in production.

Everything above `main` is pure except the four functions whose names say
otherwise (`write_start`, `read_start`, `append_log`, `apply_tracker`).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from itertools import zip_longest
from datetime import datetime, timezone
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

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            models=tuple(sorted(set(self.models) | set(other.models))),
            service_tier=self.service_tier or other.service_tier,
            speed=self.speed or other.speed,
            **{f: getattr(self, f) + getattr(other, f) for f in NUMERIC_FIELDS},
        )


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


def aggregate(entries) -> Usage:
    """Sum the usage blocks of the assistant entries, one count per request.

    The transcript writes several snapshots per request with identical usage, so
    deduplication by `requestId` is mandatory — without it every figure inflates.
    """
    seen = set()
    totals = dict.fromkeys(NUMERIC_FIELDS, 0)
    models = set()
    service_tier = speed = None

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

        creation = usage.get("cache_creation")
        tools = usage.get("server_tool_use")
        totals["requests"] += 1
        totals["input_tokens"] += _int(usage, "input_tokens")
        totals["output_tokens"] += _int(usage, "output_tokens")
        totals["thinking_tokens"] += _int(
            usage.get("output_tokens_details"), "thinking_tokens"
        )
        totals["cache_write"] += _int(usage, "cache_creation_input_tokens")
        totals["ephemeral_1h"] += _int(creation, "ephemeral_1h_input_tokens")
        totals["ephemeral_5m"] += _int(creation, "ephemeral_5m_input_tokens")
        totals["cache_read"] += _int(usage, "cache_read_input_tokens")
        totals["web_search"] += _int(tools, "web_search_requests")
        totals["web_fetch"] += _int(tools, "web_fetch_requests")

        model = message.get("model")
        if isinstance(model, str):
            models.add(model)
        service_tier = service_tier or usage.get("service_tier")
        speed = speed or usage.get("speed")

    return Usage(
        models=tuple(sorted(models)),
        service_tier=service_tier,
        speed=speed,
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


def _cells(metrics: RunMetrics, source: str) -> tuple:
    """The three column cells for one row, already formatted."""
    if source in _TOTAL_ONLY:
        return ("—", "—", _TOTAL_ONLY[source](metrics))
    columns = (metrics.main, metrics.subagents, metrics.total)
    return tuple(f"{getattr(column, source):,}" for column in columns)


@dataclass(frozen=True)
class _Row:
    """One rendered row of one column half."""

    label: str
    cells: tuple  # ("", "", "") for a group heading
    kind: str  # "group" | "sub" | "rate" | ""


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
    """One half's four markdown cells: the metric name and its figures."""
    if row.kind == "group":
        return (f"**{row.label}**",) + row.cells
    label = f"{_SUB}{row.label}" if row.kind == "sub" else row.label
    return (label,) + row.cells


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
        cells = (_md_cells(left) if left else _BLANK) + (
            _md_cells(right) if right else _BLANK
        )
        # An empty cell renders as `| |` rather than `|  |`, so a group
        # heading's row reads the same as it did when it spanned the table.
        lines.append("|" + "".join(f" {cell} |" if cell else " |" for cell in cells))
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
    chip = (
        '<span class="chip usage">'
        f"{_duration(metrics.timings.elapsed_seconds)} · "
        f"{metrics.total.output_tokens:,} out · "
        f"{_rate(metrics.output_tokens_per_second)} tok/s</span>"
    )

    halves = (_LEFT_GROUPS, _RIGHT_GROUPS)
    tables = "\n".join(_tracker_table(metrics, groups) for groups in halves)
    return chip, f'<div class="usage-pair">\n{tables}\n</div>'


def _tracker_table(metrics: RunMetrics, groups) -> str:
    """One half, as a table. The pair sits side by side in `.usage-pair`."""
    rows = [
        '<table class="usage">',
        "<thead><tr><th>Metric</th><th>Main</th><th>Subagents</th>"
        "<th>Total</th></tr></thead>",
        "<tbody>",
    ]
    for row in _half(metrics, groups):
        if row.kind == "group":
            rows.append(
                f'<tr class="grp"><td colspan="4">{row.label.capitalize()}</td></tr>'
            )
            continue
        css = f' class="{"sub" if row.kind == "sub" else "tp"}"' if row.kind else ""
        cells = "".join(f"<td>{cell}</td>" for cell in row.cells)
        rows.append(f"<tr{css}><td>{row.label}</td>{cells}</tr>")
    rows += ["</tbody>", "</table>"]
    return "\n".join(rows)


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
    figures rather than a second table (design §3 R10). These eight tokens have
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


def apply_tracker(tracker_path, slug, chip_html, table_html) -> bool:
    """Write this stage's usage into the tracker. Silent no-op if it can't.

    Blanks the other stages' tokens to an empty anchored region rather than to
    nothing at all: a stage that has not run yet must render as empty now and
    still be fillable when it does run.
    """
    if slug not in TRACKER_TOKENS:
        return False
    try:
        original = Path(tracker_path).read_text(encoding="utf-8")
    except OSError:
        return False

    legend, text = _split_doc_comment(original)
    for stage, (chip_token, table_token) in TRACKER_TOKENS.items():
        if stage == slug:
            text = _substitute(text, chip_token, chip_html)
            text = _substitute(text, table_token, table_html)
        else:
            # Only while still literal: an anchored region belongs to the stage
            # that owns it, whether it holds that stage's figures or is empty
            # pending its first run.
            text = text.replace(chip_token, _anchored(chip_token, ""))
            text = text.replace(table_token, _anchored(table_token, ""))

    text = legend + text
    if text == original:
        return False
    try:
        Path(tracker_path).write_text(text, encoding="utf-8")
    except OSError:
        return False
    return True


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

    return parser.parse_args(argv)


def _run_start(args) -> None:
    session_id = os.environ.get("CLAUDE_CODE_SESSION_ID")
    if not session_id:
        return  # nothing to key a marker on; say nothing
    write_start(args.slug, session_id, _now(), _usage_dir(_config_dir()) / "state")


def _run_report(args) -> None:
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

    try:
        (_run_start if args.command == "start" else _run_report)(args)
    except Exception as problem:
        print(f"usage report skipped — {problem}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
