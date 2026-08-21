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

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

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
