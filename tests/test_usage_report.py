"""Unit tests for scripts/usage_report.py — the run-usage compute engine.

Driven by synthetic JSONL fixtures under tests/fixtures/, whose `message.usage`
blocks are copied field-for-field from a live Claude Code transcript so a
schema change fails here rather than silently reporting zeros.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest
from helpers import REPO

from scripts import usage_report as ur

FIXTURES = REPO / "tests" / "fixtures"

# The window the fixtures are built around. usage-main.jsonl has one entry
# before it (11:59:00) and one after it (12:01:30); both boundary instants
# themselves carry an entry, so inclusivity is observable.
START = datetime(2026, 8, 21, 12, 0, 0, tzinfo=timezone.utc)
END = datetime(2026, 8, 21, 12, 1, 0, tzinfo=timezone.utc)

# Present in the main fixture's conversation content and nowhere else. Fake.
SECRET = "sk-ant-fixture-not-a-real-secret-000"


def ts(minute, second):
    return f"2026-08-21T12:{minute:02d}:{second:02d}.000Z"


def assistant(stamp, request_id, output_tokens=0, **usage):
    """A minimal in-memory assistant entry, for cases no fixture pins."""
    block = {"input_tokens": 0, "output_tokens": output_tokens}
    block.update(usage)
    return {
        "type": "assistant",
        "requestId": request_id,
        "timestamp": stamp,
        "message": {"model": "claude-opus-5", "usage": block},
    }


def user(stamp):
    return {"type": "user", "timestamp": stamp, "message": {"role": "user"}}


def main_entries():
    return list(ur.iter_entries(FIXTURES / "usage-main.jsonl"))


def windowed_main():
    return ur.window_entries(main_entries(), START, END)


@pytest.fixture
def session(tmp_path):
    """A config dir laid out the way Claude Code lays one out.

    Returns (config_dir, session_id). The subagents directory is flat and holds
    both a depth-1 and a depth-2 agent, which is why a time-window scan needs no
    traversal.
    """
    session_id = "1111aaaa-2222-bbbb-3333-cccccccccccc"
    project = tmp_path / "projects" / "-tmp-fixture-repo"
    subagents = project / session_id / "subagents"
    subagents.mkdir(parents=True)
    (project / f"{session_id}.jsonl").write_bytes(
        (FIXTURES / "usage-main.jsonl").read_bytes()
    )
    (subagents / "agent-depth1.jsonl").write_bytes(
        (FIXTURES / "usage-subagent.jsonl").read_bytes()
    )
    (subagents / "agent-depth2.jsonl").write_bytes(
        (FIXTURES / "usage-subagent-depth2.jsonl").read_bytes()
    )
    return tmp_path, session_id


class TestIterEntries:
    def test_a_malformed_line_is_skipped_and_its_neighbours_still_parse(self):
        entries = list(ur.iter_entries(FIXTURES / "usage-malformed.jsonl"))
        assert [e["timestamp"] for e in entries] == [ts(0, 0), ts(0, 2)]

    def test_a_missing_file_yields_nothing(self, tmp_path):
        assert list(ur.iter_entries(tmp_path / "absent.jsonl")) == []


class TestWindowEntries:
    def test_boundary_timestamps_are_inclusive(self):
        stamps = [e["timestamp"] for e in windowed_main()]
        assert stamps[0] == ts(0, 0)
        assert stamps[-1] == ts(1, 0)

    def test_entries_outside_the_window_are_excluded(self):
        stamps = {e["timestamp"] for e in windowed_main()}
        assert "2026-08-21T11:59:00.000Z" not in stamps
        assert ts(1, 30) not in stamps

    def test_an_unparseable_timestamp_is_excluded(self):
        entries = [{"type": "user", "timestamp": "not a date"}, user(ts(0, 30))]
        assert ur.window_entries(entries, START, END) == [entries[1]]


class TestAggregate:
    def test_repeated_snapshots_of_one_request_count_once(self):
        """R12: the transcript writes several snapshots per request."""
        snapshots = [assistant(ts(0, s), "req_A", output_tokens=100) for s in (5, 6, 7, 8)]
        assert ur.aggregate(snapshots).output_tokens == 100
        assert ur.aggregate(snapshots).requests == 1

    def test_absent_optional_fields_default_to_zero(self):
        only = [e for e in windowed_main() if e.get("requestId") == "req_C"]
        usage = ur.aggregate(only)
        assert (usage.thinking_tokens, usage.cache_write, usage.ephemeral_1h) == (0, 0, 0)
        assert (usage.ephemeral_5m, usage.web_search, usage.web_fetch) == (0, 0, 0)
        assert (usage.input_tokens, usage.output_tokens) == (1, 50)

    def test_main_column_totals(self):
        usage = ur.aggregate(windowed_main())
        assert usage.requests == 3
        assert usage.input_tokens == 16
        assert usage.output_tokens == 350
        assert usage.thinking_tokens == 120
        assert usage.cache_write == 3000
        assert usage.ephemeral_1h == 2500
        assert usage.ephemeral_5m == 500
        assert usage.cache_read == 12000
        assert usage.web_search == 1
        assert usage.web_fetch == 2

    def test_models_tier_and_speed_come_from_the_entries(self):
        usage = ur.aggregate(windowed_main())
        assert usage.models == ("claude-opus-5",)
        assert usage.service_tier == "standard"
        assert usage.speed == "standard"

    def test_no_entries_aggregates_to_zero(self):
        usage = ur.aggregate([])
        assert usage.requests == 0
        assert usage.output_tokens == 0
        assert usage.models == ()


class TestTimings:
    def test_a_user_wait_is_excluded_from_run_time_but_not_elapsed(self):
        t = ur.timings(windowed_main())
        assert t.elapsed_seconds == 60
        assert t.run_seconds == 20  # 60 less the 40s gap that ends at a user entry

    def test_a_long_gap_not_ending_at_a_user_entry_is_not_a_wait(self):
        entries = [user(ts(0, 0)), assistant(ts(5, 0), "req_A")]
        t = ur.timings(entries)
        assert t.elapsed_seconds == 300
        assert t.run_seconds == 300

    def test_request_seconds_span_from_the_entry_preceding_each_request(self):
        # req_A 12:00:00→12:00:08, req_B 12:00:09→12:00:14, req_C 12:00:54→12:00:58
        assert ur.timings(windowed_main()).request_seconds == 17

    def test_a_backwards_clock_clamps_to_zero(self):
        entries = [assistant(ts(5, 0), "req_A"), user(ts(1, 0))]
        t = ur.timings(entries)
        assert t.elapsed_seconds == 0
        assert t.run_seconds == 0
        assert t.request_seconds == 0

    def test_no_entries_gives_zero_timings(self):
        t = ur.timings([])
        assert (t.elapsed_seconds, t.run_seconds, t.request_seconds) == (0, 0, 0)


class TestThroughput:
    def test_returns_none_at_zero_request_time(self):
        assert ur.throughput(1000, 0) is None

    def test_rounds_to_one_decimal(self):
        assert ur.throughput(440, 87) == 5.1


class TestCollect:
    def test_main_and_subagent_columns_split(self, session):
        config_dir, session_id = session
        transcript = ur.resolve_transcript(session_id, config_dir)
        metrics = ur.collect(transcript, transcript.parent / session_id / "subagents", START, END)

        assert metrics.main.output_tokens == 350
        assert metrics.main.requests == 3
        # 30 + 40 from the depth-1 agent, 20 from the depth-2 one
        assert metrics.subagents.output_tokens == 90
        assert metrics.subagents.requests == 3
        assert metrics.subagent_count == 2

    def test_totals_are_the_two_columns_summed(self, session):
        config_dir, session_id = session
        transcript = ur.resolve_transcript(session_id, config_dir)
        metrics = ur.collect(transcript, transcript.parent / session_id / "subagents", START, END)

        assert metrics.total.input_tokens == 22
        assert metrics.total.output_tokens == 440
        assert metrics.total.thinking_tokens == 150
        assert metrics.total.cache_write == 3900
        assert metrics.total.ephemeral_1h == 3000
        assert metrics.total.ephemeral_5m == 900
        assert metrics.total.cache_read == 14500
        assert metrics.total.web_search == 1
        assert metrics.total.web_fetch == 2
        assert metrics.total.requests == 6
        assert metrics.total.models == ("claude-haiku-4-5", "claude-opus-5")

    def test_timings_take_elapsed_from_main_and_request_time_from_both(self, session):
        config_dir, session_id = session
        transcript = ur.resolve_transcript(session_id, config_dir)
        metrics = ur.collect(transcript, transcript.parent / session_id / "subagents", START, END)

        assert metrics.timings.elapsed_seconds == 60
        assert metrics.timings.run_seconds == 20
        assert metrics.timings.request_seconds == 47  # 17 main + 24 + 6 subagent
        assert metrics.output_tokens_per_second == 9.4

    def test_an_absent_subagent_dir_leaves_the_columns_at_zero(self, session, tmp_path):
        config_dir, session_id = session
        transcript = ur.resolve_transcript(session_id, config_dir)
        metrics = ur.collect(transcript, tmp_path / "nope", START, END)

        assert metrics.subagents.output_tokens == 0
        assert metrics.subagent_count == 0
        assert metrics.total.output_tokens == 350

    def test_conversation_content_never_reaches_the_metrics(self, session):
        config_dir, session_id = session
        transcript = ur.resolve_transcript(session_id, config_dir)
        metrics = ur.collect(transcript, transcript.parent / session_id / "subagents", START, END)
        assert SECRET not in json.dumps(metrics, default=repr)


class TestResolveTranscript:
    def test_finds_the_session_transcript(self, session):
        config_dir, session_id = session
        found = ur.resolve_transcript(session_id, config_dir)
        assert found is not None and found.name == f"{session_id}.jsonl"

    def test_returns_none_when_absent(self, tmp_path):
        assert ur.resolve_transcript("no-such-session", tmp_path) is None


def test_the_module_imports_nothing_outside_the_standard_library():
    """It runs under the system python3, which is not the project venv."""
    source = (REPO / "scripts" / "usage_report.py").read_text()
    imported = set()
    for line in source.splitlines():
        line = line.strip()
        if line.startswith("import "):
            imported.add(line[len("import ") :].split(".")[0].split(" ")[0])
        elif line.startswith("from "):
            imported.add(line[len("from ") :].split(".")[0].split(" ")[0])
    assert imported <= set(__import__("sys").stdlib_module_names) | {"__future__"}, imported


def test_the_fixture_window_is_the_one_the_tests_assume():
    """Guards the fixtures against an edit that silently moves the boundaries."""
    stamps = [e["timestamp"] for e in main_entries()]
    assert stamps[0] == "2026-08-21T11:59:00.000Z"
    assert stamps[-1] == ts(1, 30)
    assert END - START == timedelta(minutes=1)
