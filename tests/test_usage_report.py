"""Unit tests for scripts/usage_report.py — the run-usage compute engine.

Driven by synthetic JSONL fixtures under tests/fixtures/, whose `message.usage`
blocks are copied field-for-field from a live Claude Code transcript so a
schema change fails here rather than silently reporting zeros.
"""

import json
import re
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
def metrics(session):
    """The RunMetrics the fixture session yields over the fixture window."""
    config_dir, session_id = session
    transcript = ur.resolve_transcript(session_id, config_dir)
    return ur.collect(transcript, transcript.parent / session_id / "subagents", START, END)


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
    def test_main_and_subagent_columns_split(self, metrics):
        assert metrics.main.output_tokens == 350
        assert metrics.main.requests == 3
        # 30 + 40 from the depth-1 agent, 20 from the depth-2 one
        assert metrics.subagents.output_tokens == 90
        assert metrics.subagents.requests == 3
        assert metrics.subagent_count == 2

    def test_totals_are_the_two_columns_summed(self, metrics):
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

    def test_timings_take_elapsed_from_main_and_request_time_from_both(self, metrics):
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

    def test_conversation_content_never_reaches_the_metrics(self, metrics):
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


# --- Stage 2: rendering and the log entry ----------------------------------

# Golden strings, compared whole. A substring check would silently tolerate a
# row-order drift away from the accepted grouped-columns mockup.
EXPECTED_MARKDOWN = """### Run usage

| metric | main | subagents | total |
|---|---:|---:|---:|
| **time** | | | |
| elapsed | — | — | 1m 00s |
| run time | — | — | 20s |
| **tokens** | | | |
| input_tokens | 16 | 6 | 22 |
| output_tokens | 350 | 90 | 440 |
| &nbsp;&nbsp;thinking_tokens | 120 | 30 | 150 |
| cache_write | 3,000 | 900 | 3,900 |
| &nbsp;&nbsp;ephemeral_1h | 2,500 | 500 | 3,000 |
| &nbsp;&nbsp;ephemeral_5m | 500 | 400 | 900 |
| cache_read | 12,000 | 2,500 | 14,500 |
| **requests** | | | |
| model | 3 | 3 | 6 |
| web_search | 1 | 0 | 1 |
| web_fetch | 2 | 0 | 2 |
| **throughput** | | | |
| output tok/s | — | — | 9.4 |

standard tier · standard speed · 2 subagents · outcome completed"""

EXPECTED_CHIP = '<span class="chip usage">1m 00s · 440 out · 9.4 tok/s</span>'

EXPECTED_TRACKER_TABLE = """<table class="usage">
<thead><tr><th>Metric</th><th>Main</th><th>Subagents</th><th>Total</th></tr></thead>
<tbody>
<tr class="grp"><td colspan="4">Time</td></tr>
<tr><td>elapsed</td><td>—</td><td>—</td><td>1m 00s</td></tr>
<tr><td>run time</td><td>—</td><td>—</td><td>20s</td></tr>
<tr class="grp"><td colspan="4">Tokens</td></tr>
<tr><td>input_tokens</td><td>16</td><td>6</td><td>22</td></tr>
<tr><td>output_tokens</td><td>350</td><td>90</td><td>440</td></tr>
<tr class="sub"><td>thinking_tokens</td><td>120</td><td>30</td><td>150</td></tr>
<tr><td>cache_write</td><td>3,000</td><td>900</td><td>3,900</td></tr>
<tr class="sub"><td>ephemeral_1h</td><td>2,500</td><td>500</td><td>3,000</td></tr>
<tr class="sub"><td>ephemeral_5m</td><td>500</td><td>400</td><td>900</td></tr>
<tr><td>cache_read</td><td>12,000</td><td>2,500</td><td>14,500</td></tr>
<tr class="grp"><td colspan="4">Requests</td></tr>
<tr><td>model</td><td>3</td><td>3</td><td>6</td></tr>
<tr><td>web_search</td><td>1</td><td>0</td><td>1</td></tr>
<tr><td>web_fetch</td><td>2</td><td>0</td><td>2</td></tr>
<tr class="grp"><td colspan="4">Throughput</td></tr>
<tr class="tp"><td>output tok/s</td><td>—</td><td>—</td><td>9.4</td></tr>
</tbody>
</table>"""

# The exact field set of design §5 Data model, in its documented order.
EXPECTED_LOG_FIELDS = [
    "repo_name", "timestamp", "slug", "feature_version", "outcome",
    "evals_included", "elapsed_seconds", "run_seconds", "request_seconds",
    "output_tokens_per_second", "subagent_count", "service_tier", "speed",
    "models", "requests", "output_tokens", "thinking_tokens", "input_tokens",
    "cache_write", "ephemeral_1h", "ephemeral_5m", "cache_read", "web_search",
    "web_fetch",
]


def context(**overrides):
    fields = dict(
        slug="feature-plan",
        repo_name="dev-skills",
        timestamp="2026-08-21T12:01:00Z",
        feature_version=1,
        outcome="completed",
        evals_included=False,
    )
    fields.update(overrides)
    return ur.RunContext(**fields)


def empty_metrics():
    return ur.RunMetrics(ur.Usage(), ur.Usage(), ur.Usage(), ur.Timings())


class TestRenderMarkdown:
    def test_matches_the_accepted_mockup(self, metrics):
        assert ur.render_markdown(metrics, context()) == EXPECTED_MARKDOWN

    def test_a_zero_request_run_renders_an_em_dash_rather_than_dividing_by_zero(self):
        table = ur.render_markdown(empty_metrics(), context())
        assert "| output tok/s | — | — | — |" in table

    def test_a_clamped_duration_renders_as_zero_seconds(self):
        table = ur.render_markdown(empty_metrics(), context())
        assert "| elapsed | — | — | 0s |" in table

    def test_the_outcome_comes_from_the_context(self, metrics):
        table = ur.render_markdown(metrics, context(outcome="halted"))
        assert table.endswith("· outcome halted")


class TestRenderTrackerHtml:
    def test_chip_matches_the_accepted_mockup(self, metrics):
        chip, _ = ur.render_tracker_html(metrics)
        assert chip == EXPECTED_CHIP

    def test_the_chip_is_never_mistakable_for_a_timestamp_chip(self, metrics):
        """feature-list derives last_activity from `Updated <date>` chips."""
        chip, _ = ur.render_tracker_html(metrics)
        assert re.search(r"Updated\s+\d", chip) is None

    def test_table_matches_the_accepted_mockup(self, metrics):
        _, table = ur.render_tracker_html(metrics)
        assert table == EXPECTED_TRACKER_TABLE

    def test_both_surfaces_carry_the_same_row_order(self, metrics):
        markdown = ur.render_markdown(metrics, context())
        _, table = ur.render_tracker_html(metrics)
        # [1:] drops the header row, which matches the same shape
        labels = re.findall(r"^\| (?:&nbsp;&nbsp;)?([a-z_ /]+) \|", markdown, re.MULTILINE)[1:]
        cells = re.findall(r"<tr[^>]*><td>([a-z_ /]+)</td>", table)
        assert labels == cells


class TestLogEntry:
    def test_exact_field_set_in_order(self, metrics):
        assert list(ur.log_entry(metrics, context())) == EXPECTED_LOG_FIELDS

    def test_columns_carry_all_three_keys(self, metrics):
        entry = ur.log_entry(metrics, context())
        assert entry["output_tokens"] == {"main": 350, "subagents": 90, "total": 440}
        assert entry["requests"] == {"main": 3, "subagents": 3, "total": 6}

    def test_scalars_come_from_the_metrics_and_the_context(self, metrics):
        entry = ur.log_entry(metrics, context(evals_included=True))
        assert entry["elapsed_seconds"] == 60
        assert entry["run_seconds"] == 20
        assert entry["request_seconds"] == 47
        assert entry["output_tokens_per_second"] == 9.4
        assert entry["subagent_count"] == 2
        assert entry["models"] == ["claude-haiku-4-5", "claude-opus-5"]
        assert entry["evals_included"] is True

    def test_feature_version_is_null_when_unresolved(self, metrics):
        entry = ur.log_entry(metrics, context(feature_version=None))
        assert entry["feature_version"] is None
        assert json.loads(json.dumps(entry))["feature_version"] is None

    def test_evals_included_is_always_present(self, metrics):
        assert "evals_included" in ur.log_entry(metrics, context())

    def test_the_serialised_entry_stays_under_2048_bytes(self):
        """Below PIPE_BUF a single O_APPEND write of one line is atomic."""
        fat = ur.Usage(**{f: 999_999_999 for f in ur.NUMERIC_FIELDS},
                       models=("claude-opus-5", "claude-haiku-4-5"),
                       service_tier="standard", speed="standard")
        metrics = ur.RunMetrics(fat, fat, fat + fat, ur.Timings(999999, 999999, 999999), 99)
        entry = ur.log_entry(metrics, context(slug="feature-implement"))
        assert len(json.dumps(entry).encode()) < 2048


class TestNoConversationContentLeaks:
    def test_the_secret_reaches_neither_renderer_nor_the_log_entry(self, metrics):
        chip, table = ur.render_tracker_html(metrics)
        assert SECRET not in ur.render_markdown(metrics, context())
        assert SECRET not in chip
        assert SECRET not in table
        assert SECRET not in json.dumps(ur.log_entry(metrics, context()))


# --- Stage 3: CLI, start marker, log append, tracker application -----------

STARTED = datetime(2026, 8, 21, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def tracker(tmp_path):
    """A fresh copy of the minimal tracker, so each test edits its own."""
    path = tmp_path / "feature-v1-tracker.html"
    path.write_bytes((FIXTURES / "usage-tracker-min.html").read_bytes())
    return path


@pytest.fixture
def cli(session, monkeypatch):
    """The environment `main` reads: config dir, session id and a fixed clock."""
    config_dir, session_id = session
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", session_id)
    monkeypatch.setattr(ur, "_now", lambda: END)
    return config_dir, session_id


def runs_log(config_dir):
    path = config_dir / "dev-skills" / "usage" / "runs.jsonl"
    return path.read_text().splitlines() if path.exists() else []


def seed_marker(config_dir, session_id, slug="feature-plan"):
    return ur.write_start(
        slug, session_id, STARTED, config_dir / "dev-skills" / "usage" / "state",
        cwd="/Users/someone/Git/dev-skills",
    )


class TestStartMarker:
    def test_round_trips_through_the_state_dir(self, tmp_path):
        ur.write_start("feature-design", "sess-1", STARTED, tmp_path, cwd="/tmp/repo")
        marker = ur.read_start("feature-design", "sess-1", tmp_path)
        assert marker["slug"] == "feature-design"
        assert marker["session_id"] == "sess-1"
        assert marker["cwd"] == "/tmp/repo"
        assert ur._parse_ts(marker["started"]) == STARTED

    def test_an_absent_marker_reads_as_none(self, tmp_path):
        assert ur.read_start("feature-design", "sess-1", tmp_path) is None

    def test_markers_are_keyed_on_session_and_slug(self, tmp_path):
        ur.write_start("feature-storm", "sess-1", STARTED, tmp_path)
        ur.write_start("feature-design", "sess-1", STARTED, tmp_path)
        ur.write_start("feature-storm", "sess-2", STARTED, tmp_path)
        assert len(list(tmp_path.iterdir())) == 3

    @pytest.mark.parametrize("slug", ["../escape", "Feature-Plan", "9lives", "", "a" * 65])
    def test_an_invalid_slug_is_rejected_before_it_reaches_a_filename(self, tmp_path, slug):
        with pytest.raises(ValueError):
            ur.write_start(slug, "sess-1", STARTED, tmp_path)
        assert list(tmp_path.glob("*")) == []

    def test_an_invalid_session_id_is_rejected(self, tmp_path):
        with pytest.raises(ValueError):
            ur.write_start("feature-plan", "../../etc/passwd", STARTED, tmp_path)
        assert list(tmp_path.glob("*")) == []


class TestAppendLog:
    def test_interleaved_appends_both_survive(self, tmp_path):
        log = tmp_path / "usage" / "runs.jsonl"
        ur.append_log({"slug": "feature-storm"}, log)
        ur.append_log({"slug": "feature-design"}, log)
        lines = log.read_text().splitlines()
        assert [json.loads(line)["slug"] for line in lines] == [
            "feature-storm", "feature-design"
        ]

    def test_a_pre_existing_file_is_not_truncated(self, tmp_path):
        log = tmp_path / "runs.jsonl"
        log.write_text('{"slug":"earlier"}\n')
        ur.append_log({"slug": "later"}, log)
        assert log.read_text().splitlines()[0] == '{"slug":"earlier"}'

    def test_one_entry_is_exactly_one_line(self, tmp_path):
        log = tmp_path / "runs.jsonl"
        ur.append_log({"note": "no\nnewlines\nplease"}, log)
        assert len(log.read_text().splitlines()) == 1


class TestApplyTracker:
    def test_fills_its_own_two_tokens(self, tracker):
        ur.apply_tracker(tracker, "feature-plan", "<span>CHIP</span>", "<table>T</table>")
        text = tracker.read_text()
        assert "{{PLAN_USAGE_CHIP}}" not in text
        assert "<span>CHIP</span>" in text
        assert "<table>T</table>" in text

    def test_blanks_the_other_six_while_they_are_still_literal(self, tracker):
        ur.apply_tracker(tracker, "feature-plan", "<span>CHIP</span>", "<table>T</table>")
        text = tracker.read_text()
        for token in ("{{DESIGN_USAGE}}", "{{BRAINSTORMING_USAGE_CHIP}}",
                      "{{IMPLEMENTATION_USAGE}}"):
            assert token not in text

    def test_it_leaves_the_other_panels_own_tokens_alone(self, tracker):
        ur.apply_tracker(tracker, "feature-plan", "<span>CHIP</span>", "<table>T</table>")
        assert "{{PLAN_BULLETS}}" in tracker.read_text()

    def test_a_second_run_replaces_the_previous_figures(self, tracker):
        """R10: re-running a stage shows the new run, not a second table."""
        ur.apply_tracker(tracker, "feature-plan", "<span>OLD</span>", "<table>OLD</table>")
        ur.apply_tracker(tracker, "feature-plan", "<span>NEW</span>", "<table>NEW</table>")
        text = tracker.read_text()
        assert "OLD" not in text
        assert text.count("<span>NEW</span>") == 1
        assert text.count("<table>NEW</table>") == 1

    def test_a_stage_can_still_fill_after_another_stage_blanked_it(self, tracker):
        ur.apply_tracker(tracker, "feature-storm", "<span>S</span>", "<table>S</table>")
        ur.apply_tracker(tracker, "feature-design", "<span>D</span>", "<table>D</table>")
        text = tracker.read_text()
        assert "<span>S</span>" in text and "<span>D</span>" in text

    def test_a_missing_tracker_is_a_silent_no_op(self, tmp_path, capsys):
        assert ur.apply_tracker(tmp_path / "absent.html", "feature-plan", "c", "t") is False
        assert capsys.readouterr().out == ""

    def test_an_unknown_slug_is_a_no_op(self, tracker):
        before = tracker.read_text()
        assert ur.apply_tracker(tracker, "bug-fix", "c", "t") is False
        assert tracker.read_text() == before


class TestMainStart:
    def test_start_writes_a_marker(self, cli, capsys):
        config_dir, session_id = cli
        assert ur.main(["start", "--slug", "feature-plan"]) == 0
        assert ur.read_start(
            "feature-plan", session_id, config_dir / "dev-skills" / "usage" / "state"
        ) is not None
        assert capsys.readouterr().out == ""

    def test_start_is_a_silent_no_op_without_a_session_id(self, cli, capsys, monkeypatch):
        config_dir, _ = cli
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID")
        assert ur.main(["start", "--slug", "feature-plan"]) == 0
        assert capsys.readouterr().out == ""
        assert not (config_dir / "dev-skills").exists()

    def test_an_invalid_slug_degrades_to_one_line(self, cli, capsys):
        assert ur.main(["start", "--slug", "../escape"]) == 0
        assert len(capsys.readouterr().out.strip().splitlines()) == 1


class TestMainReport:
    def test_prints_the_table_appends_one_line_and_clears_the_marker(self, cli, capsys):
        config_dir, session_id = cli
        marker = seed_marker(config_dir, session_id)
        assert ur.main(["report", "--slug", "feature-plan", "--feature-version", "1"]) == 0

        out = capsys.readouterr().out
        assert out.startswith("### Run usage")
        assert "outcome completed" in out

        lines = runs_log(config_dir)
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["slug"] == "feature-plan"
        assert entry["feature_version"] == 1
        assert entry["repo_name"] == "dev-skills"
        assert entry["evals_included"] is False
        assert not marker.exists()

    def test_halted_outcome_and_evals_included_reach_the_log(self, cli, capsys):
        config_dir, session_id = cli
        seed_marker(config_dir, session_id)
        ur.main(["report", "--slug", "feature-plan", "--outcome", "halted",
                 "--evals-included"])
        capsys.readouterr()
        entry = json.loads(runs_log(config_dir)[0])
        assert entry["outcome"] == "halted"
        assert entry["evals_included"] is True

    def test_an_unresolved_feature_version_logs_null(self, cli, capsys):
        config_dir, session_id = cli
        seed_marker(config_dir, session_id)
        ur.main(["report", "--slug", "feature-plan"])
        capsys.readouterr()
        assert json.loads(runs_log(config_dir)[0])["feature_version"] is None

    def test_it_applies_the_tracker_when_one_is_given(self, cli, capsys, tracker):
        config_dir, session_id = cli
        seed_marker(config_dir, session_id)
        ur.main(["report", "--slug", "feature-plan", "--tracker", str(tracker)])
        capsys.readouterr()
        text = tracker.read_text()
        assert '<span class="chip usage">' in text
        assert '<table class="usage">' in text

    def test_no_conversation_content_reaches_stdout_or_the_log(self, cli, capsys):
        config_dir, session_id = cli
        seed_marker(config_dir, session_id)
        ur.main(["report", "--slug", "feature-plan"])
        assert SECRET not in capsys.readouterr().out
        assert SECRET not in "".join(runs_log(config_dir))


class TestMainNeverFailsTheCaller:
    """R13: every failure prints at most one line and still exits 0."""

    def one_line(self, capsys):
        out = capsys.readouterr().out.strip().splitlines()
        assert len(out) == 1, out
        assert out[0].startswith("usage report skipped — ")

    def test_no_start_marker(self, cli, capsys):
        assert ur.main(["report", "--slug", "feature-plan"]) == 0
        self.one_line(capsys)

    def test_no_session_id(self, cli, capsys, monkeypatch):
        config_dir, _ = cli
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID")
        assert ur.main(["report", "--slug", "feature-plan"]) == 0
        self.one_line(capsys)
        assert runs_log(config_dir) == []

    def test_missing_transcript(self, cli, capsys):
        config_dir, session_id = cli
        seed_marker(config_dir, session_id)
        for path in (config_dir / "projects" / "-tmp-fixture-repo").glob("*.jsonl"):
            path.unlink()
        assert ur.main(["report", "--slug", "feature-plan"]) == 0
        self.one_line(capsys)

    def test_a_bad_argument(self, cli, capsys):
        assert ur.main(["report", "--slug", "feature-plan", "--outcome", "sideways"]) == 0
        self.one_line(capsys)

    def test_an_unknown_command(self, cli, capsys):
        assert ur.main(["explode"]) == 0
        self.one_line(capsys)

    def test_an_unexpected_exception(self, cli, capsys, monkeypatch):
        config_dir, session_id = cli
        seed_marker(config_dir, session_id)
        monkeypatch.setattr(ur, "collect", _boom)
        assert ur.main(["report", "--slug", "feature-plan"]) == 0
        self.one_line(capsys)

    def test_a_failed_log_write_still_prints_the_table(self, cli, capsys, monkeypatch):
        config_dir, session_id = cli
        seed_marker(config_dir, session_id)
        monkeypatch.setattr(ur, "append_log", _boom)
        assert ur.main(["report", "--slug", "feature-plan"]) == 0
        out = capsys.readouterr().out
        assert out.startswith("### Run usage")
        assert "log write failed: disk full" in out

    def test_an_unwritable_tracker_leaves_the_table_and_log_intact(self, cli, capsys, tmp_path):
        config_dir, session_id = cli
        seed_marker(config_dir, session_id)
        assert ur.main(["report", "--slug", "feature-plan",
                        "--tracker", str(tmp_path / "absent.html")]) == 0
        assert capsys.readouterr().out.startswith("### Run usage")
        assert len(runs_log(config_dir)) == 1


def _boom(*args, **kwargs):
    raise RuntimeError("disk full")


def test_the_config_dir_honours_the_environment(tmp_path, monkeypatch):
    """This machine's config dir is an iCloud path, not ~/.claude."""
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    assert ur._config_dir() == tmp_path
    monkeypatch.delenv("CLAUDE_CONFIG_DIR")
    assert ur._config_dir().name == ".claude"


class TestApplyTrackerAgainstTheShippedTemplate:
    """The real template, not the minimal fixture.

    `templates/feature-tracker.html` opens with an HTML doc comment that
    legends every token by name — including the eight usage ones. A whole-file
    substitution therefore rewrites the legend as well as the panel, and the
    anchor comments it writes carry a `-->` that closes the doc comment early,
    spilling the rest of the legend onto the page as visible markup. Nothing in
    the minimal fixture has a legend, which is why this only shows up here.
    """

    TEMPLATE = REPO / "templates" / "feature-tracker.html"

    def rendered(self, tmp_path, slug="feature-plan"):
        tracker = tmp_path / "tracker.html"
        tracker.write_text(self.TEMPLATE.read_text(), encoding="utf-8")
        assert ur.apply_tracker(
            tracker, slug, '<span class="chip usage">1m · 2 out</span>',
            '<table class="usage"><tr><td>x</td></tr></table>',
        )
        return tracker.read_text(encoding="utf-8")

    def doc_comment_end(self, text):
        """Offset just past the leading doc comment's terminator."""
        opened = text.index("<!--")
        return text.index("-->", opened) + len("-->")

    def test_the_doc_comment_is_not_reopened_or_closed_early(self, tmp_path):
        original, rendered = self.TEMPLATE.read_text(), self.rendered(tmp_path)
        assert rendered.count("<!--", 0, self.doc_comment_end(original)) == \
            original.count("<!--", 0, self.doc_comment_end(original)), (
            "apply_tracker wrote comment markers into the template's doc "
            "comment; the first `-->` closes it early and the rest of the "
            "legend renders as visible HTML"
        )

    def test_the_legend_keeps_its_literal_token_names(self, tmp_path):
        rendered = self.rendered(tmp_path)
        legend = rendered[: self.doc_comment_end(rendered)]
        for chip_token, table_token in ur.TRACKER_TOKENS.values():
            for token in (chip_token, table_token):
                assert token in legend, (
                    f"{token} was substituted inside the doc-comment legend, "
                    f"which documents the token rather than rendering it"
                )

    def test_the_panel_is_still_filled(self, tmp_path):
        # The guard must not cost the substitution it exists to protect.
        rendered = self.rendered(tmp_path)
        body = rendered[self.doc_comment_end(rendered) :]
        assert body.count('<span class="chip usage">') == 1
        assert body.count('<table class="usage">') == 1
        assert not re.search(r"\{\{[A-Z_]*USAGE[A-Z_]*\}\}", body), (
            "literal usage tokens left in the rendered body"
        )

