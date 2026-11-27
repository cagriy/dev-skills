"""Unit tests for scripts/implement_progress.py — feature-implement's live
progress file.

The file lives outside the project, under the user's config dir, and is read
by whatever the user points at it (a status line, a pane, a dashboard), so the
shape, the arithmetic and the never-break-the-run rule are pinned here.
"""

import json
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts import implement_progress as ip

T0 = datetime(2026, 11, 27, 10, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now

    def at(self, seconds):
        self.now = T0 + timedelta(seconds=seconds)


@pytest.fixture
def config(tmp_path, monkeypatch):
    cfg = tmp_path / "config"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    return cfg


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(ip, "_now", c)
    return c


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "work" / "my-app"
    root.mkdir(parents=True)
    return root


def run(capsys, *argv):
    code = ip.main(list(argv))
    out = capsys.readouterr().out
    return code, out


def init(capsys, repo, stages=4, extra=()):
    args = [
        "init", "--repo-root", str(repo), "--feature-version", "3",
        "--description", "add-reminders", "--branch", "main",
        *extra,
    ]
    for n in range(1, stages + 1):
        args += ["--stage", f"{n}=Stage title {n}"]
    code, out = run(capsys, *args)
    assert code == 0
    assert out.startswith("implement-progress: "), out
    return Path(out.split("implement-progress: ", 1)[1].strip())


def load(path):
    return json.loads(Path(path).read_text())


def stage(capsys, path, spec, status, *extra):
    return run(capsys, "stage", "--file", str(path), "--stage", spec, "--status", status, *extra)


# --- init ----------------------------------------------------------------


class TestInit:
    def test_creates_the_file_under_the_config_dir(self, capsys, config, clock, repo):
        path = init(capsys, repo)
        base = config / "dev-skills" / "progress"
        assert path.parent.parent == base
        assert path.parent.name.startswith("my-app-")
        assert path.name == "feature-v3-add-reminders.json"
        doc = load(path)
        assert doc["schema"] == ip.SCHEMA
        assert doc["repo"]["name"] == "my-app"
        assert doc["repo"]["branch"] == "main"
        assert doc["feature"]["version"] == 3
        assert doc["run"]["status"] == "running"
        assert doc["run"]["phase"] == "readiness"
        assert doc["run"]["started_at"] == "2026-11-27T10:00:00Z"
        assert [s["number"] for s in doc["stages"]] == [1, 2, 3, 4]
        assert all(s["status"] == "pending" for s in doc["stages"])
        assert doc["progress"]["stages_total"] == 4
        assert doc["progress"]["stages_done"] == 0
        assert doc["progress"]["summary"].startswith("0 of 4 stages done")

    def test_two_repos_with_one_name_do_not_collide(self, capsys, config, clock, tmp_path):
        a = tmp_path / "a" / "app"
        b = tmp_path / "b" / "app"
        a.mkdir(parents=True)
        b.mkdir(parents=True)
        assert init(capsys, a).parent != init(capsys, b).parent

    def test_a_description_that_could_escape_the_directory_is_refused(
        self, capsys, config, clock, repo
    ):
        code, out = run(
            capsys, "init", "--repo-root", str(repo), "--feature-version", "3",
            "--description", "../evil", "--stage", "1=x",
        )
        assert code == 0
        assert out.startswith("implement-progress: skipped — ")
        assert not (config / "dev-skills").exists()

    def test_a_rerun_keeps_a_summary_of_the_previous_run(self, capsys, config, clock, repo):
        path = init(capsys, repo)
        stage(capsys, path, "1", "running")
        clock.at(300)
        stage(capsys, path, "1", "done", "--sha", "abc1234")
        clock.at(600)
        init(capsys, repo)
        doc = load(path)
        assert doc["run"]["started_at"] == "2026-11-27T10:10:00Z"
        assert all(s["status"] == "pending" for s in doc["stages"])
        assert len(doc["runs"]) == 1
        previous = doc["runs"][0]
        # It never finished, so it is recorded as abandoned rather than running.
        assert previous["status"] == "abandoned"
        assert previous["stages_done"] == 1


# --- stages and the estimate --------------------------------------------


class TestStages:
    def test_time_left_is_extrapolated_from_completed_stages(self, capsys, config, clock, repo):
        path = init(capsys, repo)
        clock.at(60)
        stage(capsys, path, "1", "running", "--executor", "subagent")
        doc = load(path)
        assert doc["run"]["phase"] == "stages"
        assert doc["run"]["loop_started_at"] == "2026-11-27T10:01:00Z"
        assert doc["progress"]["running"] == [1]
        assert doc["progress"]["remaining_seconds"] is None

        clock.at(660)
        code, out = stage(capsys, path, "1", "done", "--sha", "abc1234")
        assert code == 0
        doc = load(path)
        one = doc["stages"][0]
        assert one["status"] == "done"
        assert one["sha"] == "abc1234"
        assert one["seconds"] == 600
        assert one["executor"] == "subagent"
        p = doc["progress"]
        assert p["stages_done"] == 1
        assert p["stages_remaining"] == 3
        assert p["percent"] == 25
        assert p["elapsed_seconds"] == 660
        assert p["seconds_per_stage"] == 600
        assert p["remaining_seconds"] == 1800
        assert p["eta"] == "2026-11-27T10:41:00Z"
        assert p["summary"] == "1 of 4 stages done · 11m elapsed · ~30m left"
        assert p["summary"] in out

    def test_remaining_shrinks_with_time_since_the_last_completion(
        self, capsys, config, clock, repo
    ):
        path = init(capsys, repo)
        stage(capsys, path, "1", "running")
        clock.at(600)
        stage(capsys, path, "1", "done")
        clock.at(900)
        stage(capsys, path, "2", "running")
        p = load(path)["progress"]
        assert p["eta"] == "2026-11-27T10:40:00Z"
        assert p["remaining_seconds"] == 1500

    def test_stages_committed_before_this_run_do_not_feed_the_rate(
        self, capsys, config, clock, repo
    ):
        path = init(capsys, repo, stages=5)
        stage(capsys, path, "1-2", "done", "--prior")
        doc = load(path)
        assert doc["stages"][0]["prior"] is True
        assert doc["stages"][0]["seconds"] is None
        assert doc["progress"]["seconds_per_stage"] is None
        assert doc["run"]["phase"] == "readiness"

        stage(capsys, path, "3", "running")
        clock.at(300)
        stage(capsys, path, "3", "done")
        p = load(path)["progress"]
        assert p["stages_done"] == 3
        assert p["stages_done_this_run"] == 1
        assert p["percent"] == 60
        assert p["seconds_per_stage"] == 300
        assert p["remaining_seconds"] == 600

    def test_parallel_stages_count_by_wall_clock(self, capsys, config, clock, repo):
        path = init(capsys, repo)
        stage(capsys, path, "1,2", "running", "--mode", "parallel", "--batch", "1")
        clock.at(600)
        stage(capsys, path, "1", "done")
        stage(capsys, path, "2", "done")
        p = load(path)["progress"]
        assert p["seconds_per_stage"] == 300
        assert p["remaining_seconds"] == 600

    def test_recording_done_again_only_updates_the_sha(self, capsys, config, clock, repo):
        # A parallel stage is recorded done in its worktree, then again by the
        # main agent once the cherry-pick has landed it under a new sha.
        path = init(capsys, repo)
        stage(capsys, path, "1", "running")
        clock.at(300)
        stage(capsys, path, "1", "done", "--sha", "aaaa111")
        clock.at(400)
        stage(capsys, path, "1", "done", "--sha", "bbbb222")
        one = load(path)["stages"][0]
        assert one["sha"] == "bbbb222"
        assert one["finished_at"] == "2026-11-27T10:05:00Z"
        assert one["seconds"] == 300

    def test_blocked_stages_leave_the_estimate(self, capsys, config, clock, repo):
        path = init(capsys, repo)
        stage(capsys, path, "3-4", "blocked", "--note", "needs staging deploy")
        stage(capsys, path, "1", "running")
        clock.at(300)
        stage(capsys, path, "1", "done")
        doc = load(path)
        assert doc["stages"][2]["note"] == "needs staging deploy"
        p = doc["progress"]
        assert p["stages_blocked"] == 2
        assert p["stages_remaining"] == 1
        assert p["remaining_seconds"] == 300
        assert "2 blocked" in p["summary"]

    def test_a_stage_the_plan_did_not_have_can_be_added(self, capsys, config, clock, repo):
        path = init(capsys, repo)
        stage(capsys, path, "5", "running", "--title", "Coverage gaps")
        doc = load(path)
        assert doc["stages"][-1]["title"] == "Coverage gaps"
        assert doc["progress"]["stages_total"] == 5

    def test_a_bad_stage_spec_changes_nothing(self, capsys, config, clock, repo):
        path = init(capsys, repo)
        before = path.read_text()
        code, out = stage(capsys, path, "two", "done")
        assert code == 0
        assert out.startswith("implement-progress: skipped — ")
        assert path.read_text() == before

    def test_stage_spec_parsing(self):
        assert ip.parse_stage_list("1-3,5") == [1, 2, 3, 5]
        assert ip.parse_stage_list("4") == [4]
        for bad in ("", "0", "3-1", "a", "1,,2"):
            with pytest.raises(ValueError):
                ip.parse_stage_list(bad)


# --- update and finish ---------------------------------------------------


class TestUpdateAndFinish:
    def test_update_records_phase_strategy_and_counts(self, capsys, config, clock, repo):
        path = init(capsys, repo)
        code, _ = run(
            capsys, "update", "--file", str(path), "--phase", "stages",
            "--strategy", "4 stages remaining → [1–3] one unit, [4] serial",
            "--deviations", "1", "--pending-verification", "2", "--handed-forward", "0",
        )
        assert code == 0
        doc = load(path)
        assert doc["run"]["phase"] == "stages"
        assert doc["run"]["strategy"].startswith("4 stages remaining")
        assert doc["counts"] == {"deviations": 1, "pending_verification": 2, "handed_forward": 0}

    def test_finish_halted_stops_running_stages(self, capsys, config, clock, repo):
        path = init(capsys, repo)
        stage(capsys, path, "1", "running")
        clock.at(120)
        code, _ = run(capsys, "finish", "--file", str(path), "--outcome", "halted",
                      "--note", "Step 6: undiagnosable failure")
        assert code == 0
        doc = load(path)
        assert doc["run"]["status"] == "halted"
        assert doc["run"]["phase"] == "done"
        assert doc["run"]["finished_at"] == "2026-11-27T10:02:00Z"
        assert doc["stages"][0]["status"] == "stopped"
        assert doc["progress"]["remaining_seconds"] is None
        assert doc["progress"]["eta"] is None

    def test_elapsed_stops_at_finish(self, capsys, config, clock, repo):
        path = init(capsys, repo, stages=1)
        stage(capsys, path, "1", "running")
        clock.at(300)
        stage(capsys, path, "1", "done")
        run(capsys, "finish", "--file", str(path), "--outcome", "completed")
        clock.at(9000)
        stage(capsys, path, "1", "done", "--sha", "ccc3333")
        p = load(path)["progress"]
        assert p["elapsed_seconds"] == 300
        assert p["remaining_seconds"] == 0


# --- safety ---------------------------------------------------------------


class TestSafety:
    def test_a_file_outside_the_progress_dir_is_refused(self, capsys, config, clock, tmp_path):
        target = tmp_path / "elsewhere.json"
        target.write_text(json.dumps({"schema": ip.SCHEMA}))
        before = target.read_text()
        code, out = stage(capsys, target, "1", "done")
        assert code == 0
        assert out.startswith("implement-progress: skipped — ")
        assert target.read_text() == before

    def test_a_missing_file_is_a_skip_not_an_error(self, capsys, config, clock):
        missing = config / "dev-skills" / "progress" / "x-00000000" / "feature-v1-x.json"
        code, out = stage(capsys, missing, "1", "done")
        assert code == 0
        assert out.startswith("implement-progress: skipped — ")
        assert not missing.exists()

    def test_garbage_arguments_never_raise(self, capsys, config, clock):
        for argv in ([], ["nope"], ["stage"], ["finish", "--file"], ["update", "--phase", "x"]):
            code, out = run(capsys, *argv)
            assert code == 0
            assert out.startswith("implement-progress: skipped — ")

    def test_concurrent_writers_lose_no_update(self, capsys, config, clock, repo):
        path = init(capsys, repo, stages=12)
        threads = [
            threading.Thread(target=ip.main, args=(["stage", "--file", str(path),
                                                    "--stage", str(n), "--status", "done"],))
            for n in range(1, 13)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        capsys.readouterr()
        assert load(path)["progress"]["stages_done"] == 12


# --- long-running jobs ----------------------------------------------------


class TestJobEstimate:
    def test_units_take_precedence_once_one_has_landed(self):
        e = ip.job_estimate(elapsed=120, units_done=10, units_total=40, expected=None,
                            expected_basis=None)
        assert e["percent"] == 25
        assert e["remaining_seconds"] == 360
        assert e["basis"] == "units 10/40"

    def test_expected_duration(self):
        e = ip.job_estimate(elapsed=300, units_done=0, units_total=None, expected=900,
                            expected_basis="expected 15m")
        assert e["percent"] == 33
        assert e["remaining_seconds"] == 600
        assert e["basis"] == "expected 15m"
        assert e["overrun_seconds"] is None

    def test_an_overrun_has_no_time_left_and_never_reads_done(self):
        e = ip.job_estimate(elapsed=1000, units_done=0, units_total=None, expected=900,
                            expected_basis="expected 15m")
        assert e["percent"] == 99
        assert e["remaining_seconds"] is None
        assert e["overrun_seconds"] == 100

    def test_nothing_to_go_on(self):
        e = ip.job_estimate(elapsed=30, units_done=0, units_total=None, expected=None,
                            expected_basis=None)
        assert e["percent"] is None
        assert e["remaining_seconds"] is None
        assert e["basis"] == "none — elapsed time only"

    def test_history_median_of_recent_successes(self, tmp_path):
        history = tmp_path / "job-history.jsonl"
        lines = [{"label": "deploy", "seconds": s} for s in (100, 900, 300, 500, 700, 200)]
        lines.append({"label": "other", "seconds": 5})
        history.write_text("".join(json.dumps(l) + "\n" for l in lines) + "not json\n")
        # The last five deploys: 900, 300, 500, 700, 200 → median 500.
        assert ip.history_expected(history, "deploy") == (500, 5)
        assert ip.history_expected(history, "missing") is None
        assert ip.history_expected(tmp_path / "absent.jsonl", "deploy") is None


def py(code):
    return [sys.executable, "-c", code]


class TestJob:
    def job(self, capsys, path, *opts, command):
        argv = ["job", "--file", str(path), *opts, "--", *command]
        code = ip.main(argv)
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    def test_passes_output_and_exit_code_through(self, capsys, config, repo):
        path = init(capsys, repo)
        code, out, _ = self.job(capsys, path, "--label", "build",
                                command=py("print('hello'); raise SystemExit(3)"))
        assert code == 3
        assert "hello" in out
        record = load(path)["jobs"][-1]
        assert record["label"] == "build"
        assert record["status"] == "failed"
        assert record["exit_code"] == 3

    def test_updates_the_file_while_the_job_runs(self, capsys, config, repo):
        path = init(capsys, repo)
        reader = (
            "import json, sys, time\n"
            "print('UNIT a'); print('UNIT b', flush=True)\n"
            "time.sleep(0.6)\n"
            "job = json.load(open(sys.argv[1]))['jobs'][-1]\n"
            "print('seen', job['status'], job['units_done'], job['percent'])\n"
        )
        code, out, _ = self.job(
            capsys, path, "--label", "provision env", "--stage", "2",
            "--total", "4", "--match", "^UNIT", "--interval", "0.1",
            command=[sys.executable, "-c", reader, str(path)],
        )
        assert code == 0
        assert "seen running 2 50" in out
        record = load(path)["jobs"][-1]
        assert record["status"] == "completed"
        assert record["stage"] == 2
        assert record["percent"] == 100
        assert record["remaining_seconds"] == 0

    def test_a_success_feeds_the_next_runs_estimate(self, capsys, config, repo):
        path = init(capsys, repo)
        self.job(capsys, path, "--label", "deploy", command=py("pass"))
        history = path.parent / "job-history.jsonl"
        assert history.exists()
        assert json.loads(history.read_text().splitlines()[-1])["label"] == "deploy"
        reader = (
            "import json, sys, time\n"
            "time.sleep(0.4)\n"
            "print(json.load(open(sys.argv[1]))['jobs'][-1]['basis'])\n"
        )
        _, out, _ = self.job(capsys, path, "--label", "deploy", "--interval", "0.1",
                             command=[sys.executable, "-c", reader, str(path)])
        assert "history" in out

    def test_never_records_the_command_line(self, capsys, config, repo):
        path = init(capsys, repo)
        self.job(capsys, path, "--label", "deploy",
                 command=py("x = 'hunter2-not-a-real-secret'"))
        assert "hunter2" not in path.read_text()
        assert "hunter2" not in (path.parent / "job-history.jsonl").read_text()

    def test_a_missing_progress_file_still_runs_the_command(self, capsys, config, tmp_path):
        missing = config / "dev-skills" / "progress" / "x-00000000" / "feature-v1-x.json"
        code, out, err = self.job(capsys, missing, "--label", "build",
                                  command=py("print('ran'); raise SystemExit(4)"))
        assert code == 4
        assert "ran" in out
        assert "implement-progress: skipped — " in err

    def test_no_command_is_a_failure_not_a_success(self, capsys, config, repo):
        path = init(capsys, repo)
        code = ip.main(["job", "--file", str(path), "--label", "build"])
        err = capsys.readouterr().err
        assert code != 0
        assert "implement-progress: job not run — " in err

    def test_an_unlaunchable_command_fails(self, capsys, config, repo):
        path = init(capsys, repo)
        code, _, err = self.job(capsys, path, "--label", "build",
                                command=["/nonexistent/definitely-not-here"])
        assert code == 127
        assert load(path)["jobs"][-1]["status"] == "failed"
