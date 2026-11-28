"""Unit tests for scripts/run_progress.py — the one live progress file that
feature-storm, feature-design, feature-plan, feature-implement and bug-fix
all write, in every repo and every session.

The file lives outside the project, under the user's config dir, and is read
by whatever the user points at it (a status line, a pane, a dashboard), so the
shape, the arithmetic and the never-break-the-run rule are pinned here.
"""

import json
import sys
import threading
from datetime import datetime, timedelta, timezone

import pytest

from scripts import run_progress as rp

T0 = datetime(2026, 11, 27, 10, 0, 0, tzinfo=timezone.utc)
SKIP = "run-progress: skipped — "
SESSION = "CLAUDE_CODE_SESSION_ID"

# A small step plan, so the arithmetic below does not move when a real
# skill's estimates are retuned.
TEST_PLAN = (("1", "Capture", 2), ("2", "Resolve", 1), ("3", "Clarify", 10), ("4", "Write", 5))


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
    monkeypatch.delenv(SESSION, raising=False)
    return cfg


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(rp, "_now", c)
    return c


@pytest.fixture
def plan(monkeypatch):
    monkeypatch.setitem(rp.STEP_PLANS, "feature-design", TEST_PLAN)
    return TEST_PLAN


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "work" / "my-app"
    root.mkdir(parents=True)
    return root


def run(capsys, *argv):
    code = rp.main(list(argv))
    out = capsys.readouterr().out
    return code, out


def progress(config):
    return config / "dev-skills" / "progress" / "progress.json"


def load(config):
    return json.loads(progress(config).read_text())


def record(config, run_id):
    return next(r for r in load(config)["runs"] if r["id"] == run_id)


def _printed(out):
    """`run-progress: <run id> <path>` — the path may hold spaces."""
    assert out.startswith("run-progress: "), out
    run_id, path = out.split("run-progress: ", 1)[1].strip().split(" ", 1)
    return run_id, path


def _id_from(out):
    return _printed(out)[0]


def init(capsys, repo, stages=4, extra=(), subject="feature-v3-add-reminders"):
    args = [
        "init", "--skill", "feature-implement", "--repo-root", str(repo),
        "--subject", subject, "--branch", "main", *extra,
    ]
    for n in range(1, stages + 1):
        args += ["--stage", f"{n}=Stage title {n}"]
    code, out = run(capsys, *args)
    assert code == 0
    return _id_from(out)


def init_steps(capsys, repo, at="3", skill="feature-design", subject="feature-v3-add-reminders"):
    code, out = run(
        capsys, "init", "--skill", skill, "--repo-root", str(repo), "--subject", subject,
        "--at", at,
    )
    assert code == 0
    return _id_from(out)


def stage(capsys, run_id, spec, status, *extra):
    return run(capsys, "stage", "--run", run_id, "--stage", spec, "--status", status, *extra)


def enter(capsys, run_id, step):
    return run(capsys, "enter", "--run", run_id, "--step", step)


def finish(capsys, run_id, outcome, *extra):
    return run(capsys, "finish", "--run", run_id, "--outcome", outcome, *extra)


def step_history(config):
    path = config / "dev-skills" / "progress" / "step-history.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()]


# --- init: one file, every run ---------------------------------------------


class TestInit:
    def test_creates_the_one_file_under_the_config_dir(self, capsys, config, clock, repo):
        code, out = run(capsys, "init", "--skill", "feature-implement", "--repo-root", str(repo),
                        "--subject", "feature-v3-add-reminders", "--branch", "main",
                        *(f"--stage={n}=Stage title {n}" for n in range(1, 5)))
        run_id, path = _printed(out)
        assert rp.RUN_ID.match(run_id)
        assert path == str(progress(config))
        assert [p.name for p in progress(config).parent.glob("*.json")] == ["progress.json"]
        doc = load(config)
        assert doc["schema"] == 2
        assert doc["updated_at"] == "2026-11-27T10:00:00Z"
        assert doc["history"] == []
        [r] = doc["runs"]
        assert r["id"] == run_id
        assert r["skill"] == "feature-implement"
        assert r["unit"] == "stage"
        assert r["subject"] == {"kind": "feature", "name": "feature-v3-add-reminders",
                                "number": 3, "description": "add-reminders"}
        assert r["repo"] == {"name": "my-app", "path": str(repo.resolve()), "branch": "main"}
        assert r["session_id"] is None
        assert r["status"] == "running"
        assert r["phase"] == "readiness"
        assert r["started_at"] == "2026-11-27T10:00:00Z"
        assert [s["number"] for s in r["stages"]] == [1, 2, 3, 4]
        assert all(s["status"] == "pending" for s in r["stages"])
        assert r["progress"]["total"] == 4
        assert r["progress"]["done"] == 0
        assert r["progress"]["summary"].startswith("0 of 4 stages done")

    def test_a_run_records_the_files_it_works_on(self, capsys, config, clock, repo):
        run_id = init(capsys, repo, extra=("--plan", "/p.md", "--design", "/d.md",
                                           "--tracker", "/t.html"))
        assert record(config, run_id)["files"] == {
            "artefact": None, "tracker": "/t.html", "plan": "/p.md", "design": "/d.md"}

    def test_one_file_holds_every_skill_and_subject(
        self, capsys, config, clock, plan, tmp_path, monkeypatch
    ):
        roots = [tmp_path / name for name in ("web", "api", "cli")]
        for root in roots:
            root.mkdir()
        monkeypatch.setenv(SESSION, "sess-a")
        design = init_steps(capsys, roots[0])
        monkeypatch.setenv(SESSION, "sess-b")
        bug = init_steps(capsys, roots[1], at="2", skill="bug-fix", subject="bug-12-login-crash")
        monkeypatch.setenv(SESSION, "sess-c")
        build = init(capsys, roots[2])
        by_id = {r["id"]: r for r in load(config)["runs"]}
        assert set(by_id) == {design, bug, build}
        assert [(by_id[i]["skill"], by_id[i]["unit"], by_id[i]["subject"]["kind"],
                 by_id[i]["session_id"]) for i in (design, bug, build)] == [
            ("feature-design", "step", "feature", "sess-a"),
            ("bug-fix", "step", "bug", "sess-b"),
            ("feature-implement", "stage", "feature", "sess-c"),
        ]
        assert by_id[bug]["subject"] == {"kind": "bug", "name": "bug-12-login-crash",
                                         "number": 12, "description": "login-crash"}

    def test_a_new_run_on_the_subject_retires_the_last(
        self, capsys, config, clock, plan, repo, monkeypatch
    ):
        # A cleared-conversation handover: the next stage runs in a new session.
        monkeypatch.setenv(SESSION, "sess-a")
        design = init_steps(capsys, repo)
        clock.at(600)
        finish(capsys, design, "completed")
        monkeypatch.setenv(SESSION, "sess-b")
        clock.at(900)
        implement = init(capsys, repo)
        doc = load(config)
        assert [r["id"] for r in doc["runs"]] == [implement]
        [past] = doc["history"]
        assert past["id"] == design
        assert past["skill"] == "feature-design"
        assert past["session_id"] == "sess-a"
        assert past["subject"]["name"] == "feature-v3-add-reminders"
        assert past["status"] == "completed"
        assert past["finished_at"] == "2026-11-27T10:10:00Z"
        assert past["done"] == 3  # Step 4 was skipped
        assert past["total"] == 4
        assert past["elapsed_seconds"] == 600

    def test_a_new_run_in_the_session_retires_the_last(
        self, capsys, config, clock, plan, repo, monkeypatch
    ):
        monkeypatch.setenv(SESSION, "sess-a")
        design = init_steps(capsys, repo)
        bug = init_steps(capsys, repo, at="2", skill="bug-fix", subject="bug-12-login-crash")
        doc = load(config)
        assert [r["id"] for r in doc["runs"]] == [bug]
        assert doc["history"][0]["id"] == design
        # It never finished, so it is recorded as abandoned rather than running.
        assert doc["history"][0]["status"] == "abandoned"

    def test_runs_in_other_sessions_stay(self, capsys, config, clock, plan, repo, monkeypatch):
        monkeypatch.setenv(SESSION, "sess-a")
        first = init_steps(capsys, repo, subject="feature-v3-add-reminders")
        monkeypatch.setenv(SESSION, "sess-b")
        second = init_steps(capsys, repo, subject="feature-v4-export")
        assert [r["id"] for r in load(config)["runs"]] == [first, second]

    def test_without_a_session_only_the_subject_retires(self, capsys, config, clock, plan, repo):
        first = init_steps(capsys, repo, subject="feature-v3-add-reminders")
        second = init_steps(capsys, repo, subject="feature-v4-export")
        assert [r["id"] for r in load(config)["runs"]] == [first, second]

    def test_one_subject_in_two_checkouts_is_two_runs(self, capsys, config, clock, tmp_path):
        a = tmp_path / "a" / "app"
        b = tmp_path / "b" / "app"
        a.mkdir(parents=True)
        b.mkdir(parents=True)
        ids = [init(capsys, a), init(capsys, b)]
        assert [r["id"] for r in load(config)["runs"]] == ids

    def test_a_rerun_keeps_a_summary_of_the_previous_run(self, capsys, config, clock, repo):
        first = init(capsys, repo)
        stage(capsys, first, "1", "running")
        clock.at(300)
        stage(capsys, first, "1", "done", "--sha", "abc1234")
        clock.at(600)
        second = init(capsys, repo)
        doc = load(config)
        [r] = doc["runs"]
        assert r["id"] == second != first
        assert r["started_at"] == "2026-11-27T10:10:00Z"
        assert all(s["status"] == "pending" for s in r["stages"])
        [past] = doc["history"]
        assert past["status"] == "abandoned"
        assert past["skill"] == "feature-implement"
        assert past["done"] == 1
        assert past["total"] == 4

    def test_live_runs_and_history_are_capped(self, capsys, config, clock, repo, monkeypatch):
        monkeypatch.setattr(rp, "MAX_LIVE", 2)
        monkeypatch.setattr(rp, "MAX_HISTORY", 3)
        ids = []
        for n in range(1, 7):
            clock.at(60 * n)
            ids.append(init(capsys, repo, stages=1, subject=f"feature-v{n}-x"))
        doc = load(config)
        # The longest-idle live run is retired first; history keeps the newest.
        assert [r["id"] for r in doc["runs"]] == ids[4:]
        assert [h["id"] for h in doc["history"]] == ids[1:4]

    def test_a_path_with_spaces_is_printed_whole(self, capsys, tmp_path, monkeypatch, clock,
                                                 repo):
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "Mobile Documents" / "cfg"))
        code, out = run(capsys, "init", "--skill", "feature-implement", "--repo-root", str(repo),
                        "--subject", "feature-v3-x", "--stage", "1=x")
        assert _printed(out)[1] == str(tmp_path / "Mobile Documents" / "cfg" / "dev-skills"
                                       / "progress" / "progress.json")

    def test_a_corrupt_file_is_moved_aside(self, capsys, config, clock, repo):
        path = progress(config)
        path.parent.mkdir(parents=True)
        path.write_text("{not json")
        run_id = init(capsys, repo)
        assert [r["id"] for r in load(config)["runs"]] == [run_id]
        [aside] = list(path.parent.glob("progress.json.corrupt-*"))
        assert aside.read_text() == "{not json"

    def test_the_subject_must_suit_the_skill(self, capsys, config, clock, plan, repo):
        for skill, subject in (("bug-fix", "feature-v3-x"), ("feature-design", "bug-3-x")):
            code, out = run(capsys, "init", "--skill", skill, "--repo-root", str(repo),
                            "--subject", subject)
            assert out.startswith(SKIP), (skill, subject)
        assert not (config / "dev-skills").exists()

    def test_a_malformed_subject_is_refused(self, capsys, config, clock, repo):
        for subject in ("../evil", "feature-v3-a/b", "feature-v3-..x", "feature-3-x", "x", ""):
            code, out = run(
                capsys, "init", "--skill", "feature-implement", "--repo-root", str(repo),
                "--subject", subject, "--stage", "1=x",
            )
            assert code == 0
            assert out.startswith(SKIP), subject
        assert not (config / "dev-skills").exists()

    def test_an_unknown_skill_is_refused(self, capsys, config, clock, repo):
        code, out = run(capsys, "init", "--skill", "feature-launch", "--repo-root", str(repo),
                        "--subject", "feature-v1-x")
        assert code == 0
        assert out.startswith(SKIP)

    def test_stages_belong_to_implement_and_steps_to_the_rest(
        self, capsys, config, clock, plan, repo
    ):
        code, out = run(capsys, "init", "--skill", "feature-design", "--repo-root", str(repo),
                        "--subject", "feature-v1-x", "--stage", "1=x")
        assert out.startswith(SKIP)
        code, out = run(capsys, "init", "--skill", "feature-implement", "--repo-root",
                        str(repo), "--subject", "feature-v1-x", "--at", "1")
        assert out.startswith(SKIP)
        assert not (config / "dev-skills").exists()

    def test_repo_root_and_branch_default_to_the_enclosing_checkout(
        self, capsys, config, clock, plan, repo, monkeypatch
    ):
        (repo / ".git").mkdir()
        (repo / ".git" / "HEAD").write_text("ref: refs/heads/feat-x\n")
        inner = repo / "src" / "deep"
        inner.mkdir(parents=True)
        monkeypatch.chdir(inner)
        code, out = run(capsys, "init", "--skill", "feature-design",
                        "--subject", "feature-v3-add-reminders", "--at", "3")
        r = record(config, _id_from(out))
        assert r["repo"]["path"] == str(repo.resolve())
        assert r["repo"]["branch"] == "feat-x"


# --- naming a run -----------------------------------------------------------


class TestRunIds:
    def test_an_unknown_run_changes_nothing(self, capsys, config, clock, repo):
        init(capsys, repo)
        before = progress(config).read_text()
        code, out = stage(capsys, "0badc0de", "1", "done")
        assert code == 0
        assert out.startswith(SKIP)
        assert progress(config).read_text() == before

    def test_a_retired_run_takes_no_more_writes(self, capsys, config, clock, plan, repo):
        design = init_steps(capsys, repo)
        init(capsys, repo)
        before = progress(config).read_text()
        code, out = enter(capsys, design, "4")
        assert out.startswith(SKIP)
        assert "no longer live" in out
        assert progress(config).read_text() == before

    def test_a_malformed_run_id_is_refused(self, capsys, config, clock, repo):
        init(capsys, repo)
        before = progress(config).read_text()
        for bad in ("../x", "", "ABCDEF12", "abc", "0badc0de0"):
            code, out = stage(capsys, bad, "1", "done")
            assert code == 0
            assert out.startswith(SKIP), bad
        assert progress(config).read_text() == before

    def test_without_the_file_every_call_skips(self, capsys, config, clock):
        for argv in (("stage", "--run", "0badc0de", "--stage", "1", "--status", "done"),
                     ("enter", "--run", "0badc0de", "--step", "3"),
                     ("finish", "--run", "0badc0de", "--outcome", "halted")):
            code, out = run(capsys, *argv)
            assert code == 0
            assert out.startswith(SKIP)
        assert not progress(config).exists()


# --- stages and the throughput estimate -----------------------------------


class TestStages:
    def test_time_left_is_extrapolated_from_completed_stages(self, capsys, config, clock, repo):
        rid = init(capsys, repo)
        clock.at(60)
        stage(capsys, rid, "1", "running", "--executor", "subagent")
        r = record(config, rid)
        assert r["phase"] == "stages"
        assert r["loop_started_at"] == "2026-11-27T10:01:00Z"
        assert r["progress"]["running"] == [1]
        assert r["progress"]["remaining_seconds"] is None

        clock.at(660)
        code, out = stage(capsys, rid, "1", "done", "--sha", "abc1234")
        assert code == 0
        r = record(config, rid)
        one = r["stages"][0]
        assert one["status"] == "done"
        assert one["sha"] == "abc1234"
        assert one["seconds"] == 600
        assert one["executor"] == "subagent"
        p = r["progress"]
        assert p["done"] == 1
        assert p["remaining"] == 3
        assert p["percent"] == 25
        assert p["elapsed_seconds"] == 660
        assert p["seconds_per_stage"] == 600
        assert p["remaining_seconds"] == 1800
        assert p["eta"] == "2026-11-27T10:41:00Z"
        assert p["summary"] == "1 of 4 stages done · 11m elapsed · ~30m left"
        assert p["summary"] in out
        assert r["updated_at"] == load(config)["updated_at"] == "2026-11-27T10:11:00Z"

    def test_remaining_shrinks_with_time_since_the_last_completion(
        self, capsys, config, clock, repo
    ):
        rid = init(capsys, repo)
        stage(capsys, rid, "1", "running")
        clock.at(600)
        stage(capsys, rid, "1", "done")
        clock.at(900)
        stage(capsys, rid, "2", "running")
        p = record(config, rid)["progress"]
        assert p["eta"] == "2026-11-27T10:40:00Z"
        assert p["remaining_seconds"] == 1500

    def test_stages_committed_before_this_run_do_not_feed_the_rate(
        self, capsys, config, clock, repo
    ):
        rid = init(capsys, repo, stages=5)
        stage(capsys, rid, "1-2", "done", "--prior")
        r = record(config, rid)
        assert r["stages"][0]["prior"] is True
        assert r["stages"][0]["seconds"] is None
        assert r["progress"]["seconds_per_stage"] is None
        assert r["phase"] == "readiness"

        stage(capsys, rid, "3", "running")
        clock.at(300)
        stage(capsys, rid, "3", "done")
        p = record(config, rid)["progress"]
        assert p["done"] == 3
        assert p["done_this_run"] == 1
        assert p["percent"] == 60
        assert p["seconds_per_stage"] == 300
        assert p["remaining_seconds"] == 600

    def test_parallel_stages_count_by_wall_clock(self, capsys, config, clock, repo):
        rid = init(capsys, repo)
        stage(capsys, rid, "1,2", "running", "--mode", "parallel", "--batch", "1")
        clock.at(600)
        stage(capsys, rid, "1", "done")
        stage(capsys, rid, "2", "done")
        p = record(config, rid)["progress"]
        assert p["seconds_per_stage"] == 300
        assert p["remaining_seconds"] == 600

    def test_recording_done_again_only_updates_the_sha(self, capsys, config, clock, repo):
        # A parallel stage is recorded done in its worktree, then again by the
        # main agent once the cherry-pick has landed it under a new sha.
        rid = init(capsys, repo)
        stage(capsys, rid, "1", "running")
        clock.at(300)
        stage(capsys, rid, "1", "done", "--sha", "aaaa111")
        clock.at(400)
        stage(capsys, rid, "1", "done", "--sha", "bbbb222")
        one = record(config, rid)["stages"][0]
        assert one["sha"] == "bbbb222"
        assert one["finished_at"] == "2026-11-27T10:05:00Z"
        assert one["seconds"] == 300

    def test_blocked_stages_leave_the_estimate(self, capsys, config, clock, repo):
        rid = init(capsys, repo)
        stage(capsys, rid, "3-4", "blocked", "--note", "needs staging deploy")
        stage(capsys, rid, "1", "running")
        clock.at(300)
        stage(capsys, rid, "1", "done")
        r = record(config, rid)
        assert r["stages"][2]["note"] == "needs staging deploy"
        p = r["progress"]
        assert p["blocked"] == 2
        assert p["remaining"] == 1
        assert p["remaining_seconds"] == 300
        assert "2 blocked" in p["summary"]

    def test_a_stage_the_plan_did_not_have_can_be_added(self, capsys, config, clock, repo):
        rid = init(capsys, repo)
        stage(capsys, rid, "5", "running", "--title", "Coverage gaps")
        r = record(config, rid)
        assert r["stages"][-1]["title"] == "Coverage gaps"
        assert r["progress"]["total"] == 5

    def test_a_bad_stage_spec_changes_nothing(self, capsys, config, clock, repo):
        rid = init(capsys, repo)
        before = progress(config).read_text()
        code, out = stage(capsys, rid, "two", "done")
        assert code == 0
        assert out.startswith(SKIP)
        assert progress(config).read_text() == before

    def test_stage_spec_parsing(self):
        assert rp.parse_stage_list("1-3,5") == [1, 2, 3, 5]
        assert rp.parse_stage_list("4") == [4]
        for bad in ("", "0", "3-1", "a", "1,,2"):
            with pytest.raises(ValueError):
                rp.parse_stage_list(bad)

    def test_enter_is_refused_on_a_stage_run(self, capsys, config, clock, repo):
        rid = init(capsys, repo)
        before = progress(config).read_text()
        code, out = enter(capsys, rid, "1")
        assert code == 0
        assert out.startswith(SKIP)
        assert progress(config).read_text() == before


# --- steps and the per-step estimate --------------------------------------


class TestSteps:
    def test_init_enters_the_named_step_and_counts_earlier_ones_done(
        self, capsys, config, clock, plan, repo
    ):
        rid = init_steps(capsys, repo, at="3")
        r = record(config, rid)
        assert r["unit"] == "step"
        assert r["subject"]["number"] == 3
        assert "stages" not in r
        by_id = {s["id"]: s for s in r["steps"]}
        assert [s["id"] for s in r["steps"]] == ["1", "2", "3", "4"]
        assert by_id["1"]["status"] == "done" and by_id["1"]["prior"] is True
        assert by_id["1"]["seconds"] is None
        assert by_id["3"]["status"] == "running"
        assert by_id["3"]["started_at"] == "2026-11-27T10:00:00Z"
        assert by_id["3"]["expected_seconds"] == 600
        assert by_id["3"]["expected_basis"] == "estimate"
        p = r["progress"]
        assert p["total"] == 4
        assert p["done"] == 2
        assert p["current"] == {"id": "3", "title": "Clarify"}
        # Steps differ in length: 10m left in Step 3, 5m for Step 4.
        assert p["remaining_seconds"] == 900
        assert p["summary"] == "2 of 4 steps done · now Step 3 — Clarify · 0s elapsed · ~15m left"

    def test_time_left_follows_each_steps_own_estimate(self, capsys, config, clock, plan, repo):
        rid = init_steps(capsys, repo, at="3")
        clock.at(240)
        # Any write re-derives the figures; re-entering the running step is one.
        enter(capsys, rid, "3")
        p = record(config, rid)["progress"]
        assert p["remaining_seconds"] == (600 - 240) + 300
        assert p["percent"] == round(100 * 240 / (240 + 660))
        assert p["eta"] == "2026-11-27T10:15:00Z"

    def test_entering_a_step_closes_the_one_before_and_logs_its_time(
        self, capsys, config, clock, plan, repo
    ):
        rid = init_steps(capsys, repo, at="3")
        clock.at(420)
        code, out = enter(capsys, rid, "4")
        assert code == 0
        r = record(config, rid)
        by_id = {s["id"]: s for s in r["steps"]}
        assert by_id["3"]["status"] == "done"
        assert by_id["3"]["seconds"] == 420
        assert by_id["3"]["passes"] == 1
        assert by_id["4"]["status"] == "running"
        assert r["progress"]["remaining_seconds"] == 300
        assert r["progress"]["summary"] in out
        history = step_history(config)
        assert len(history) == 1
        assert history[0]["skill"] == "feature-design"
        assert history[0]["step"] == "3"
        assert history[0]["title"] == "Clarify"
        assert history[0]["seconds"] == 420
        # Prior steps carry no timing, so they never reach the history.
        assert all(h["step"] != "1" for h in history)

    def test_an_overrunning_step_adds_nothing_and_says_so(self, capsys, config, clock, plan, repo):
        rid = init_steps(capsys, repo, at="4")
        clock.at(400)
        enter(capsys, rid, "4")
        p = record(config, rid)["progress"]
        assert p["remaining_seconds"] == 0
        assert p["percent"] == 99
        assert "Step 4 over by 1m" in p["summary"]

    def test_re_entering_the_running_step_changes_nothing(self, capsys, config, clock, plan, repo):
        rid = init_steps(capsys, repo, at="3")
        clock.at(100)
        enter(capsys, rid, "3")
        three = {s["id"]: s for s in record(config, rid)["steps"]}["3"]
        assert three["started_at"] == "2026-11-27T10:00:00Z"
        assert three["passes"] == 0
        assert step_history(config) == []

    def test_a_step_jumped_over_is_skipped(self, capsys, config, clock, plan, repo):
        rid = init_steps(capsys, repo, at="2")
        clock.at(60)
        enter(capsys, rid, "4")
        r = record(config, rid)
        by_id = {s["id"]: s for s in r["steps"]}
        assert by_id["3"]["status"] == "skipped"
        p = r["progress"]
        assert p["skipped"] == 1
        assert p["remaining_seconds"] == 300
        assert "1 skipped" in p["summary"]

    def test_entering_an_earlier_step_loops_back(self, capsys, config, clock, plan, repo):
        # bug-fix returns to diagnosis when a fix does not hold.
        rid = init_steps(capsys, repo, at="2")
        clock.at(60)
        enter(capsys, rid, "3")
        clock.at(360)
        enter(capsys, rid, "4")
        clock.at(480)
        enter(capsys, rid, "3")
        r = record(config, rid)
        by_id = {s["id"]: s for s in r["steps"]}
        assert r["loops"] == 1
        assert by_id["3"]["status"] == "running"
        assert by_id["3"]["passes"] == 1
        assert by_id["3"]["seconds"] == 300
        assert by_id["4"]["status"] == "pending"
        assert by_id["4"]["passes"] == 1
        assert by_id["2"]["status"] == "done"
        # Another full pass through Steps 3 and 4 is still to come.
        assert r["progress"]["remaining_seconds"] == 600 + 300
        clock.at(780)
        enter(capsys, rid, "4")
        three = {s["id"]: s for s in record(config, rid)["steps"]}["3"]
        assert three["seconds"] == 600
        assert three["passes"] == 2
        # Each pass is its own sample.
        assert [h["seconds"] for h in step_history(config) if h["step"] == "3"] == [300, 300]

    def test_an_unknown_step_changes_nothing(self, capsys, config, clock, plan, repo):
        rid = init_steps(capsys, repo, at="3")
        before = progress(config).read_text()
        code, out = enter(capsys, rid, "9")
        assert code == 0
        assert out.startswith(SKIP)
        assert progress(config).read_text() == before

    def test_stage_is_refused_on_a_step_run(self, capsys, config, clock, plan, repo):
        rid = init_steps(capsys, repo, at="3")
        before = progress(config).read_text()
        code, out = stage(capsys, rid, "1", "done")
        assert out.startswith(SKIP)
        assert progress(config).read_text() == before

    def test_history_replaces_the_estimate(self, capsys, config, clock, plan, repo):
        history = config / "dev-skills" / "progress" / "step-history.jsonl"
        history.parent.mkdir(parents=True)
        lines = [{"skill": "feature-design", "step": "3", "title": "Clarify", "seconds": s}
                 for s in (100, 300, 200)]
        lines += [
            {"skill": "feature-design", "step": "3", "title": "Old title", "seconds": 9999},
            {"skill": "feature-storm", "step": "3", "title": "Clarify", "seconds": 9999},
        ]
        history.write_text("".join(json.dumps(l) + "\n" for l in lines) + "not json\n")
        rid = init_steps(capsys, repo, at="3")
        r = record(config, rid)
        three = {s["id"]: s for s in r["steps"]}["3"]
        assert three["expected_seconds"] == 200
        assert three["expected_basis"] == "history"
        assert three["history_runs"] == 3
        assert r["progress"]["remaining_seconds"] == 200 + 300
        assert r["progress"]["estimate_basis"] == (
            "history for 1 of 2 remaining steps, estimates for the rest"
        )

    def test_history_uses_the_last_five_passes(self, tmp_path):
        history = tmp_path / "step-history.jsonl"
        seconds = (100, 900, 300, 500, 700, 200)
        history.write_text("".join(
            json.dumps({"skill": "bug-fix", "step": "4", "title": "Diagnose", "seconds": s}) + "\n"
            for s in seconds
        ))
        assert rp.step_expectations(history, "bug-fix") == {("4", "Diagnose"): (500, 5)}
        assert rp.step_expectations(tmp_path / "absent.jsonl", "bug-fix") == {}

    def test_finish_completed_closes_the_step_and_skips_the_rest(
        self, capsys, config, clock, plan, repo
    ):
        rid = init_steps(capsys, repo, at="3")
        clock.at(300)
        finish(capsys, rid, "completed")
        r = record(config, rid)
        by_id = {s["id"]: s for s in r["steps"]}
        assert by_id["3"]["status"] == "done"
        assert by_id["4"]["status"] == "skipped"
        p = r["progress"]
        assert p["percent"] == 100
        assert p["remaining_seconds"] == 0
        assert p["current"] is None
        assert [h["step"] for h in step_history(config)] == ["3"]

    def test_finish_halted_stops_the_step_without_logging_it(
        self, capsys, config, clock, plan, repo
    ):
        rid = init_steps(capsys, repo, at="3")
        clock.at(300)
        finish(capsys, rid, "halted", "--note", "Stop")
        r = record(config, rid)
        by_id = {s["id"]: s for s in r["steps"]}
        assert by_id["3"]["status"] == "stopped"
        assert by_id["4"]["status"] == "pending"
        assert r["status"] == "halted"
        assert r["note"] == "Stop"
        assert r["progress"]["remaining_seconds"] is None
        assert step_history(config) == []

    def test_every_step_skill_has_a_plan(self):
        assert set(rp.STEP_PLANS) == set(rp.SKILLS) - {"feature-implement"}
        for skill, steps in rp.STEP_PLANS.items():
            ids = [s[0] for s in steps]
            assert len(ids) == len(set(ids)), skill
            for step_id, title, minutes in steps:
                assert rp.STEP_ID.match(step_id), (skill, step_id)
                assert title and minutes > 0, (skill, step_id)


# --- update and finish ---------------------------------------------------


class TestUpdateAndFinish:
    def test_update_records_phase_strategy_and_counts(self, capsys, config, clock, repo):
        rid = init(capsys, repo)
        code, _ = run(
            capsys, "update", "--run", rid, "--phase", "stages",
            "--strategy", "4 stages remaining → [1–3] one unit, [4] serial",
            "--deviations", "1", "--pending-verification", "2", "--handed-forward", "0",
        )
        assert code == 0
        r = record(config, rid)
        assert r["phase"] == "stages"
        assert r["strategy"].startswith("4 stages remaining")
        assert r["counts"] == {"deviations": 1, "pending_verification": 2, "handed_forward": 0}

    def test_a_step_run_takes_a_note_only(self, capsys, config, clock, plan, repo):
        rid = init_steps(capsys, repo)
        before = progress(config).read_text()
        code, out = run(capsys, "update", "--run", rid, "--phase", "closing")
        assert out.startswith(SKIP)
        assert progress(config).read_text() == before
        run(capsys, "update", "--run", rid, "--note", "waiting on the mockup")
        assert record(config, rid)["note"] == "waiting on the mockup"

    def test_finish_halted_stops_running_stages(self, capsys, config, clock, repo):
        rid = init(capsys, repo)
        stage(capsys, rid, "1", "running")
        clock.at(120)
        code, _ = finish(capsys, rid, "halted", "--note", "Step 6: undiagnosable failure")
        assert code == 0
        r = record(config, rid)
        assert r["status"] == "halted"
        assert r["phase"] == "done"
        assert r["finished_at"] == "2026-11-27T10:02:00Z"
        assert r["stages"][0]["status"] == "stopped"
        assert r["progress"]["remaining_seconds"] is None
        assert r["progress"]["eta"] is None

    def test_a_finished_run_stays_live_until_replaced(self, capsys, config, clock, repo):
        # A reader shows the session's last run, finished or not.
        rid = init(capsys, repo, stages=1)
        finish(capsys, rid, "completed")
        assert [r["id"] for r in load(config)["runs"]] == [rid]

    def test_elapsed_stops_at_finish(self, capsys, config, clock, repo):
        rid = init(capsys, repo, stages=1)
        stage(capsys, rid, "1", "running")
        clock.at(300)
        stage(capsys, rid, "1", "done")
        finish(capsys, rid, "completed")
        clock.at(9000)
        stage(capsys, rid, "1", "done", "--sha", "ccc3333")
        p = record(config, rid)["progress"]
        assert p["elapsed_seconds"] == 300
        assert p["remaining_seconds"] == 0


# --- safety ---------------------------------------------------------------


class TestSafety:
    def test_garbage_arguments_never_raise(self, capsys, config, clock):
        for argv in ([], ["nope"], ["stage"], ["enter"], ["finish", "--run"],
                     ["update", "--phase", "x"], ["stage", "--file", "x.json"]):
            code, out = run(capsys, *argv)
            assert code == 0
            assert out.startswith(SKIP)

    def test_concurrent_writers_lose_no_update(self, capsys, config, clock, repo):
        # Main agents, subagents and job wrappers in several sessions all
        # write the one file.
        ids = [init(capsys, repo, stages=6, subject=f"feature-v{n}-x") for n in (1, 2)]
        threads = [
            threading.Thread(target=rp.main, args=(["stage", "--run", rid,
                                                    "--stage", str(n), "--status", "done"],))
            for rid in ids for n in range(1, 7)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        capsys.readouterr()
        assert [record(config, rid)["progress"]["done"] for rid in ids] == [6, 6]


# --- long-running jobs ----------------------------------------------------


class TestJobEstimate:
    def test_units_take_precedence_once_one_has_landed(self):
        e = rp.job_estimate(elapsed=120, units_done=10, units_total=40, expected=None,
                            expected_basis=None)
        assert e["percent"] == 25
        assert e["remaining_seconds"] == 360
        assert e["basis"] == "units 10/40"

    def test_expected_duration(self):
        e = rp.job_estimate(elapsed=300, units_done=0, units_total=None, expected=900,
                            expected_basis="expected 15m")
        assert e["percent"] == 33
        assert e["remaining_seconds"] == 600
        assert e["basis"] == "expected 15m"
        assert e["overrun_seconds"] is None

    def test_an_overrun_has_no_time_left_and_never_reads_done(self):
        e = rp.job_estimate(elapsed=1000, units_done=0, units_total=None, expected=900,
                            expected_basis="expected 15m")
        assert e["percent"] == 99
        assert e["remaining_seconds"] is None
        assert e["overrun_seconds"] == 100

    def test_nothing_to_go_on(self):
        e = rp.job_estimate(elapsed=30, units_done=0, units_total=None, expected=None,
                            expected_basis=None)
        assert e["percent"] is None
        assert e["remaining_seconds"] is None
        assert e["basis"] == "none — elapsed time only"

    def test_history_median_of_recent_successes_in_the_repo(self, tmp_path):
        history = tmp_path / "job-history.jsonl"
        lines = [{"label": "deploy", "repo": "/r", "seconds": s}
                 for s in (100, 900, 300, 500, 700, 200)]
        lines.append({"label": "other", "repo": "/r", "seconds": 5})
        lines.append({"label": "deploy", "repo": "/elsewhere", "seconds": 5})
        history.write_text("".join(json.dumps(l) + "\n" for l in lines) + "not json\n")
        # The last five deploys here: 900, 300, 500, 700, 200 → median 500.
        assert rp.history_expected(history, "deploy", "/r") == (500, 5)
        assert rp.history_expected(history, "missing", "/r") is None
        assert rp.history_expected(history, "deploy", "/nowhere") is None
        assert rp.history_expected(tmp_path / "absent.jsonl", "deploy", "/r") is None


def py(code):
    return [sys.executable, "-c", code]


# Reads its own run's latest job from the progress file while it runs.
JOB_READER = (
    "import json, sys, time\n"
    "time.sleep(float(sys.argv[3]))\n"
    "doc = json.load(open(sys.argv[1]))\n"
    "job = next(r for r in doc['runs'] if r['id'] == sys.argv[2])['jobs'][-1]\n"
)


class TestJob:
    def job(self, capsys, run_id, *opts, command):
        argv = ["job", "--run", run_id, *opts, "--", *command]
        code = rp.main(argv)
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    def reader(self, config, run_id, delay, then):
        return [sys.executable, "-c", JOB_READER + then, str(progress(config)), run_id,
                str(delay)]

    def test_passes_output_and_exit_code_through(self, capsys, config, repo):
        rid = init(capsys, repo)
        code, out, _ = self.job(capsys, rid, "--label", "build",
                                command=py("print('hello'); raise SystemExit(3)"))
        assert code == 3
        assert "hello" in out
        job = record(config, rid)["jobs"][-1]
        assert job["label"] == "build"
        assert job["status"] == "failed"
        assert job["exit_code"] == 3

    def test_updates_the_file_while_the_job_runs(self, capsys, config, repo):
        rid = init(capsys, repo)
        then = (
            "print('seen', job['status'], job['units_done'], job['percent'])\n"
        )
        command = [sys.executable, "-c",
                   "import subprocess, sys\n"
                   "print('UNIT a'); print('UNIT b', flush=True)\n"
                   "subprocess.run(sys.argv[1:])\n",
                   *self.reader(config, rid, 0.6, then)]
        code, out, _ = self.job(
            capsys, rid, "--label", "provision env", "--stage", "2",
            "--total", "4", "--match", "^UNIT", "--interval", "0.1", command=command,
        )
        assert code == 0
        assert "seen running 2 50" in out
        job = record(config, rid)["jobs"][-1]
        assert job["status"] == "completed"
        assert job["stage"] == 2
        assert job["percent"] == 100
        assert job["remaining_seconds"] == 0

    def test_a_job_in_a_step_run_names_its_step(self, capsys, config, clock, plan, repo):
        rid = init_steps(capsys, repo, at="3")
        code, _, _ = self.job(capsys, rid, "--label", "test suite", "--step", "3",
                              command=py("pass"))
        assert code == 0
        job = record(config, rid)["jobs"][-1]
        assert job["step"] == "3"
        assert job["stage"] is None

    def test_a_success_feeds_the_next_runs_estimate(self, capsys, config, repo):
        rid = init(capsys, repo)
        self.job(capsys, rid, "--label", "deploy", command=py("pass"))
        history = progress(config).parent / "job-history.jsonl"
        last = json.loads(history.read_text().splitlines()[-1])
        assert last["label"] == "deploy"
        assert last["repo"] == str(repo.resolve())
        _, out, _ = self.job(capsys, rid, "--label", "deploy", "--interval", "0.1",
                             command=self.reader(config, rid, 0.4, "print(job['basis'])\n"))
        assert "history" in out

    def test_job_history_is_kept_per_repo(self, capsys, config, repo, tmp_path):
        rid = init(capsys, repo)
        self.job(capsys, rid, "--label", "deploy", command=py("pass"))
        other = tmp_path / "elsewhere"
        other.mkdir()
        elsewhere = init(capsys, other)
        _, out, _ = self.job(capsys, elsewhere, "--label", "deploy", "--interval", "0.1",
                             command=self.reader(config, elsewhere, 0.4,
                                                 "print(job['basis'])\n"))
        assert "history" not in out

    def test_never_records_the_command_line(self, capsys, config, repo):
        rid = init(capsys, repo)
        self.job(capsys, rid, "--label", "deploy",
                 command=py("x = 'hunter2-not-a-real-secret'"))
        assert "hunter2" not in progress(config).read_text()
        assert "hunter2" not in (progress(config).parent / "job-history.jsonl").read_text()

    def test_an_unknown_run_still_runs_the_command(self, capsys, config, tmp_path):
        code, out, err = self.job(capsys, "0badc0de", "--label", "build",
                                  command=py("print('ran'); raise SystemExit(4)"))
        assert code == 4
        assert "ran" in out
        assert SKIP in err

    def test_no_command_is_a_failure_not_a_success(self, capsys, config, repo):
        rid = init(capsys, repo)
        code = rp.main(["job", "--run", rid, "--label", "build"])
        err = capsys.readouterr().err
        assert code != 0
        assert "run-progress: job not run — " in err

    def test_an_unlaunchable_command_fails(self, capsys, config, repo):
        rid = init(capsys, repo)
        code, _, err = self.job(capsys, rid, "--label", "build",
                                command=["/nonexistent/definitely-not-here"])
        assert code == 127
        assert record(config, rid)["jobs"][-1]["status"] == "failed"
