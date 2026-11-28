"""Live progress file for the plugin's long-running skills.

One JSON document, `<config-dir>/dev-skills/progress/progress.json`, kept
outside every project and written by every run of feature-storm,
feature-design, feature-plan, feature-implement and bug-fix — in any repo, in
any session — so anything the user points at it (a status line, a pane, a
dashboard) reads one file to see which skill is running where, on which
feature or bug, how far it has got and how long it has left.

`runs` holds one record per run, live or finished, each naming its `skill`,
its `subject` (`kind` feature or bug), its repo and its session. `init`
creates a record and prints its id; every later call names that id with
`--run`, so sessions running at once never write each other's runs. A new run
retires every record of the same session or the same subject in the same repo
into `history` as a summary (an unfinished one as `abandoned`), so each
session and each subject has at most one live record. The script owns the
document's shape and every derived figure. Two kinds of run:

- **stage runs** (feature-implement): plan stages, recorded as they start and
  commit, with time left extrapolated from the stages this run completed
  (wall-clock throughput, so parallel batches count right);
- **step runs** (feature-storm, feature-design, feature-plan, bug-fix): the
  skill's own procedure steps, entered one after another. Steps differ in
  length, so each carries its own expected duration — the median of its last
  passes from `step-history.jsonl`, else the estimate in `STEP_PLANS` — and
  time left is the sum over the steps still to run.

Either kind can wrap a long-running command in `job`, which keeps that
command's own percent and time left current while it runs, from matched output
units, a stated expected duration, or the median of the same job's earlier
successful runs in the same repo.

Stdlib only: it runs as the system `python3`, not a project environment.
Every command except `job` always exits 0 and degrades to one
`run-progress: skipped — …` line. `job` exits with the wrapped command's
status, which tracking never changes: a broken progress file still runs the
command. The file never records a command line or command output — only the
label the caller chose — so nothing secret a command carries reaches it.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import signal
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX
    fcntl = None

SCHEMA = 2
FILE_NAME = "progress.json"
SKILLS = ("feature-storm", "feature-design", "feature-plan", "feature-implement", "bug-fix")
STAGE_SKILL = "feature-implement"
PHASES = ("readiness", "stages", "closing", "done")
STAGE_STATUSES = ("pending", "running", "done", "blocked", "failed")
OUTCOMES = ("completed", "halted")
JOB_STATUSES = ("running", "completed", "failed", "interrupted")
COUNTS = ("deviations", "pending_verification", "handed_forward")

# Each step skill's procedure steps, in order: (id, title, estimated minutes).
# An estimate is only the starting point: once a step has history, the median
# of its last runs replaces it. The ids are the skill's own `## Step` /
# `### Step` headings, which tests/test_static.py pins. A step left out here
# is never entered: a chain skill's final step, which closes the file before
# it hands over, and bug-fix Step 8, which only loops back.
STEP_PLANS = {
    "feature-storm": (
        ("1", "Establish requirements", 3),
        ("2", "Resolve the feature folder", 1),
        ("3a", "Generate ideas", 8),
        ("3b", "Converge", 6),
        ("4", "Summarise and approve", 3),
        ("5", "Write the brainstorm", 3),
        ("6", "Update the tracker", 1),
        ("7", "Capture lessons", 1),
        ("8", "Present highlights", 1),
    ),
    "feature-design": (
        ("1", "Capture requirements", 3),
        ("2", "Resolve the feature folder", 1),
        ("3", "Ground in the codebase", 6),
        ("4", "Clarify", 15),
        ("5", "Mock up the surface", 12),
        ("6", "Write the design", 8),
        ("7", "Self-review", 5),
        ("8", "Update the tracker", 2),
        ("9", "Capture lessons", 1),
        ("10", "Present highlights", 1),
    ),
    "feature-plan": (
        ("1", "Resolve the feature folder", 1),
        ("2", "Launch the planning subagent", 1),
        ("3", "Read the design", 2),
        ("4", "Ground in the codebase", 6),
        ("5", "Draft the plan", 8),
        ("6", "Planning decisions", 1),
        ("7", "Review the plan", 4),
        ("8", "Update the tracker", 1),
        ("9", "Capture lessons", 1),
        ("10", "Compose the summary", 1),
    ),
    "bug-fix": (
        ("0", "Select the bug", 1),
        ("1", "Confirm", 1),
        ("2", "Ground in the codebase", 4),
        ("3", "Clarify", 4),
        ("4", "Diagnose", 8),
        ("5", "Explain and approve", 3),
        ("6", "Implement test-first", 10),
        ("7", "Verify", 4),
        ("9", "Close and commit", 2),
        ("10", "Capture lessons", 1),
    ),
}

MAX_JOBS = 20
MAX_LIVE = 16
MAX_HISTORY = 50
HISTORY_WINDOW = 5
UNIT_WRITE_SECONDS = 1.0

FEATURE_SUBJECT = re.compile(r"^feature-v([1-9][0-9]{0,3})-([A-Za-z0-9][A-Za-z0-9._-]{0,119})$")
BUG_SUBJECT = re.compile(r"^bug-([1-9][0-9]{0,5})-([A-Za-z0-9][A-Za-z0-9._-]{0,119})$")
RUN_ID = re.compile(r"^[0-9a-f]{8}$")
SESSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SHA_PATTERN = re.compile(r"^[0-9a-f]{4,40}$")
STAGE_SPEC = re.compile(r"^(\d+)(?:-(\d+))?$")
STEP_ID = re.compile(r"^\d{1,2}[a-z]?$")
PREFIX = "run-progress: "
SKIP = PREFIX + "skipped — "
NOT_RUN = PREFIX + "job not run — "


# --- clock and formatting -------------------------------------------------


def _now():
    """The clock, as one seam so tests can pin it."""
    return datetime.now(timezone.utc)


def _stamp(moment) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _seconds(start, end) -> int:
    return max(0, round((end - start).total_seconds()))


def human(seconds) -> str:
    """`45s`, `11m`, `1h 05m`."""
    total = max(0, int(round(seconds)))
    if total < 60:
        return f"{total}s"
    minutes = total // 60
    if minutes < 60:
        return f"{minutes}m"
    return f"{minutes // 60}h {minutes % 60:02d}m"


def _clip(text, limit):
    return None if text is None else str(text)[:limit]


# --- paths -----------------------------------------------------------------


def _config_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def progress_dir() -> Path:
    return _config_dir() / "dev-skills" / "progress"


def progress_file() -> Path:
    """The one file every run writes."""
    return progress_dir() / FILE_NAME


def parse_subject(subject: str) -> tuple:
    """`feature-v3-add-reminders` → ("feature", 3, "add-reminders");
    `bug-12-login-crash` → ("bug", 12, "login-crash")."""
    for kind, pattern in (("feature", FEATURE_SUBJECT), ("bug", BUG_SUBJECT)):
        match = pattern.match(subject or "")
        if match and ".." not in subject:
            return kind, int(match.group(1)), match.group(2)
    raise ValueError(f"subject {subject!r} is not a feature-v<N>-<desc> or bug-<N>-<desc> folder name")


def _subject_for(skill: str, subject: str) -> tuple:
    """The parsed subject, refused when the skill does not work on its kind."""
    kind, number, description = parse_subject(subject)
    if (kind == "bug") != (skill == "bug-fix"):
        raise ValueError(f"{skill} does not work on a {kind}: {subject}")
    return kind, number, description


def _find_repo_root(start: Path) -> Path:
    """The nearest directory holding `.git` (a directory, or a worktree's
    file), else `start` itself."""
    start = start.resolve()
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    return start


def _branch(root: Path):
    """The checked-out branch read from HEAD, or None (detached, unreadable)."""
    try:
        git = root / ".git"
        if git.is_file():
            pointer = git.read_text(encoding="utf-8").strip()
            if not pointer.startswith("gitdir:"):
                return None
            git = (root / pointer.split(":", 1)[1].strip()).resolve()
        head = (git / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    prefix = "ref: refs/heads/"
    return _clip(head[len(prefix):], 200) if head.startswith(prefix) else None


def _job_history_path() -> Path:
    """One for every repo; each line names its repo, since a job's length
    follows the repo it runs in."""
    return progress_dir() / "job-history.jsonl"


def _step_history_path() -> Path:
    """One for every repo — a step's length follows the skill, not the repo."""
    return progress_dir() / "step-history.jsonl"


# --- file access -----------------------------------------------------------


@contextmanager
def _locked(path: Path):
    """Serialise read-modify-write across every session's main agent,
    subagents and job wrappers, which may all write the file at once."""
    with open(path.with_name(path.name + ".lock"), "a") as handle:
        if fcntl:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _write(path: Path, doc: dict) -> None:
    """Atomic replace, so a reader never sees half a document."""
    handle, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            json.dump(doc, out, indent=2, ensure_ascii=False)
            out.write("\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _append_lines(path: Path, entries) -> None:
    """Append JSONL entries in one write; a history problem never fails a run."""
    if not entries:
        return
    text = "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries)
    try:
        with open(path, "a", encoding="utf-8") as out:
            out.write(text)
    except OSError:
        pass


def _load(path: Path) -> dict:
    """The document, refused unless this script could have written it."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(doc, dict) or doc.get("schema") != SCHEMA
            or not isinstance(doc.get("runs"), list)
            or not isinstance(doc.get("history"), list)):
        raise ValueError(f"{path} is not a progress file this script writes")
    doc["runs"] = [r for r in doc["runs"] if isinstance(r, dict)]
    doc["history"] = [h for h in doc["history"] if isinstance(h, dict)]
    return doc


def _live(doc: dict, run_id: str) -> dict:
    for record in doc["runs"]:
        if record.get("id") == run_id:
            return record
    if any(h.get("id") == run_id for h in doc["history"]):
        raise ValueError(f"run {run_id} is no longer live: a later run in its session "
                         "or on its subject replaced it")
    raise ValueError(f"no run {run_id} in the progress file")


def update_run(run_id: str, change) -> dict:
    """Apply `change(record, now)` to one live run under the lock, re-derive,
    write. A change may return step-history entries, appended once the
    document is written."""
    path = progress_file()
    if not RUN_ID.match(run_id or ""):
        raise ValueError(f"{run_id!r} is not a run id")
    if not path.exists():
        raise ValueError(f"no progress file at {path}")
    with _locked(path):
        doc = _load(path)
        record = _live(doc, run_id)
        now = _now()
        entries = change(record, now)
        record["updated_at"] = doc["updated_at"] = _stamp(now)
        derive(record, now)
        _write(path, doc)
        _append_lines(_step_history_path(), entries)
    return record


# --- the document ----------------------------------------------------------


def _stage(number: int, title) -> dict:
    return {
        "number": number,
        "title": _clip(title, 300),
        "status": "pending",
        "prior": False,
        "sha": None,
        "executor": None,
        "batch": None,
        "mode": None,
        "started_at": None,
        "finished_at": None,
        "seconds": None,
        "note": None,
    }


def _step(step_id: str, title: str, minutes, past) -> dict:
    expected, runs = past if past else (minutes * 60, 0)
    return {
        "id": step_id,
        "title": title,
        "status": "pending",
        "prior": False,
        "expected_seconds": round(expected),
        "expected_basis": "history" if past else "estimate",
        "history_runs": runs,
        "passes": 0,
        "seconds": None,
        "started_at": None,
        "finished_at": None,
    }


def step_expectations(history, skill: str) -> dict:
    """{(step id, title): (median seconds, passes used)} over each step's last
    passes. Keyed by title too, so a renamed step starts afresh."""
    try:
        lines = Path(history).read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    samples = {}
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if (isinstance(entry, dict) and entry.get("skill") == skill
                and isinstance(entry.get("seconds"), (int, float))):
            samples.setdefault((entry.get("step"), entry.get("title")), []).append(
                entry["seconds"])
    result = {}
    for key, seconds in samples.items():
        recent = seconds[-HISTORY_WINDOW:]
        result[key] = (statistics.median(recent), len(recent))
    return result


def _unit(record) -> str:
    return record["unit"]


def _items(record) -> list:
    return record["stages"] if _unit(record) == "stage" else record["steps"]


def _summary(record) -> dict:
    """What `history` keeps of a run once a later one replaces it."""
    progress = record.get("progress") or {}
    status = record.get("status")
    return {
        "id": record.get("id"),
        "skill": record.get("skill"),
        "unit": record.get("unit"),
        "subject": record.get("subject"),
        "repo": record.get("repo"),
        "session_id": record.get("session_id"),
        # A run still marked running when it is replaced never finished.
        "status": "abandoned" if status == "running" else status,
        "started_at": record.get("started_at"),
        "finished_at": record.get("finished_at"),
        "done": progress.get("done"),
        "total": progress.get("total"),
        "elapsed_seconds": progress.get("elapsed_seconds"),
    }


def _replaces(new: dict, old: dict) -> bool:
    """A run replaces every earlier run of its session, and every earlier run
    on its subject in its repo — whichever skill ran it."""
    session = new.get("session_id")
    if session and old.get("session_id") == session:
        return True
    return ((old.get("repo") or {}).get("path") == new["repo"]["path"]
            and (old.get("subject") or {}).get("name") == new["subject"]["name"])


def add_run(doc: dict, record: dict) -> None:
    """Add a new run, retiring the runs it replaces and, past `MAX_LIVE`, the
    longest-idle others into `history`, which keeps the newest `MAX_HISTORY`."""
    live, retired = [], []
    for old in doc["runs"]:
        (retired if _replaces(record, old) else live).append(old)
    while len(live) >= MAX_LIVE:
        idle = min(live, key=lambda r: r.get("updated_at") or "")
        live.remove(idle)
        retired.append(idle)
    doc["runs"] = live + [record]
    doc["history"] = (doc["history"] + [_summary(r) for r in retired])[-MAX_HISTORY:]


def _new_id(doc: dict) -> str:
    taken = {r.get("id") for r in doc["runs"] + doc["history"]}
    while True:
        run_id = secrets.token_hex(4)
        if run_id not in taken:
            return run_id


def new_run(*, run_id, skill, repo_root, subject, branch=None, tracker=None, artefact=None,
            plan=None, design=None, stages=(), at=None, now) -> dict:
    kind, number, description = _subject_for(skill, subject)
    root = Path(repo_root).resolve()
    session = os.environ.get("CLAUDE_CODE_SESSION_ID") or ""
    unit = "stage" if skill == STAGE_SKILL else "step"
    record = {
        "id": run_id,
        "skill": skill,
        "unit": unit,
        "subject": {"kind": kind, "name": subject, "number": number,
                    "description": description},
        "repo": {"name": root.name, "path": str(root), "branch": branch},
        "files": {"artefact": artefact, "tracker": tracker, "plan": plan, "design": design},
        "session_id": session if SESSION_PATTERN.match(session) else None,
        "status": "running",
        "started_at": _stamp(now),
        "updated_at": _stamp(now),
        "finished_at": None,
        "note": None,
        "progress": {},
    }
    if unit == "stage":
        record.update(phase="readiness", loop_started_at=None, strategy=None,
                      counts={name: 0 for name in COUNTS},
                      stages=[_stage(n, title) for n, title in sorted(stages)])
    else:
        past = step_expectations(_step_history_path(), skill)
        steps = [_step(i, title, minutes, past.get((i, title)))
                 for i, title, minutes in STEP_PLANS[skill]]
        ids = [s["id"] for s in steps]
        entered = ids.index(at) if at in ids else 0
        for s in steps[:entered]:
            s.update(status="done", prior=True)
        steps[entered].update(status="running", started_at=_stamp(now))
        record.update(loops=0, steps=steps)
    record["jobs"] = []
    derive(record, now)
    return record


def derive(record: dict, now) -> None:
    """Recompute the run's `progress` block from its stages or steps and jobs."""
    started = _parse(record["started_at"]) or now
    finished = _parse(record.get("finished_at"))
    elapsed = _seconds(started, finished or now)
    live = record["status"] == "running"
    jobs = [j for j in record.get("jobs", []) if j.get("status") == "running"]
    if _unit(record) == "stage":
        progress, parts = _derive_stages(record, now, elapsed, live)
    else:
        progress, parts = _derive_steps(record, now, elapsed, live)
    for job in jobs:
        pct = job.get("percent")
        parts.append(f"{job['label']} {pct}%" if pct is not None else f"{job['label']} running")
    if not live:
        parts.append(record["status"])
    progress.update(jobs_running=len(jobs), summary=" · ".join(parts))
    record["progress"] = progress


def _derive_stages(run, now, elapsed, live):
    """Time left is the run's own throughput — wall-clock from the start of the
    stage loop to the latest completion, divided by the stages completed this
    run — projected over what remains. Stages committed before this run and
    blocked stages carry no timing and stay out of it."""
    stages = run["stages"]
    total = len(stages)
    done = [s for s in stages if s["status"] == "done"]
    done_run = [s for s in done if not s.get("prior") and _parse(s.get("finished_at"))]
    blocked = sum(1 for s in stages if s["status"] == "blocked")
    remaining = max(0, total - len(done) - blocked)

    per = left = eta = None
    if done_run:
        last = max(_parse(s["finished_at"]) for s in done_run)
        loop = _parse(run.get("loop_started_at")) or _parse(run["started_at"]) or now
        per = max(0.0, (last - loop).total_seconds()) / len(done_run)
    if remaining == 0:
        left = 0
    elif per is not None and live:
        moment = last + timedelta(seconds=per * remaining)
        left = max(0, round((moment - now).total_seconds()))
        eta = _stamp(moment)

    parts = [f"{len(done)} of {total} stages done"]
    if blocked:
        parts.append(f"{blocked} blocked")
    parts.append(f"{human(elapsed)} elapsed")
    if live and remaining:
        parts.append(f"~{human(left)} left" if left is not None
                     else "time left known after the first stage")
    progress = {
        "total": total,
        "done": len(done),
        "done_this_run": len(done_run),
        "remaining": remaining,
        "blocked": blocked,
        "running": [s["number"] for s in stages if s["status"] == "running"],
        "percent": round(100 * len(done) / total) if total else 0,
        "elapsed_seconds": elapsed,
        "seconds_per_stage": round(per) if per is not None else None,
        "remaining_seconds": left,
        "eta": eta,
        "estimate_basis": (
            f"{len(done_run)} {'stage' if len(done_run) == 1 else 'stages'} completed this run"
            if done_run
            else "none yet — estimated once a stage completes"
        ),
    }
    return progress, parts


def _derive_steps(run, now, elapsed, live):
    """Time left is each remaining step's own expected duration, summed — the
    running step counting only what is left of its expectation — because a
    skill's steps are nothing like one length. Percent is the share of the
    run's expected time already spent."""
    steps = run["steps"]
    total = len(steps)
    done = [s for s in steps if s["status"] == "done"]
    skipped = sum(1 for s in steps if s["status"] == "skipped")
    running = [s for s in steps if s["status"] == "running"]
    ahead = [s for s in steps if s["status"] in ("pending", "running")]

    left = eta = None
    over = []
    if not ahead:
        left = 0
    elif live and all(s.get("expected_seconds") is not None for s in ahead):
        rest = 0.0
        for s in ahead:
            if s["status"] == "running":
                begun = _parse(s.get("started_at")) or now
                spare = s["expected_seconds"] - (now - begun).total_seconds()
                if spare < 0:
                    over.append((s, -spare))
                rest += max(spare, 0.0)
            else:
                rest += s["expected_seconds"]
        left = round(rest)
        eta = _stamp(now + timedelta(seconds=left))

    if live and left is not None:
        percent = min(99, round(100 * elapsed / (elapsed + left))) if elapsed + left else 0
    elif not ahead:
        percent = 100
    else:
        percent = round(100 * len(done) / max(total - skipped, 1))

    history = sum(1 for s in ahead if s.get("expected_basis") == "history")
    if not ahead:
        basis = "nothing left to run"
    elif history == len(ahead):
        basis = "history for every remaining step"
    elif history == 0:
        basis = "per-step estimates — a step's history replaces its estimate once it has some"
    else:
        basis = f"history for {history} of {len(ahead)} remaining steps, estimates for the rest"

    current = running[-1] if running else None
    parts = [f"{len(done)} of {total} steps done"]
    if skipped:
        parts.append(f"{skipped} skipped")
    if current:
        parts.append(f"now Step {current['id']} — {current['title']}")
    parts.append(f"{human(elapsed)} elapsed")
    if live and ahead:
        if left is None:
            parts.append("time left unknown")
        elif left or not over:
            parts.append(f"~{human(left)} left")
    for s, seconds in over:
        parts.append(f"Step {s['id']} over by {human(seconds)}")
    progress = {
        "total": total,
        "done": len(done),
        "done_this_run": sum(1 for s in done if not s.get("prior")),
        "remaining": len(ahead),
        "skipped": skipped,
        "running": [s["id"] for s in running],
        "current": {"id": current["id"], "title": current["title"]} if current else None,
        "percent": percent,
        "elapsed_seconds": elapsed,
        "remaining_seconds": left,
        "eta": eta,
        "estimate_basis": basis,
    }
    return progress, parts


def parse_stage_list(spec: str) -> list:
    """`1-3,5` → [1, 2, 3, 5]."""
    numbers = []
    for part in (spec or "").split(","):
        match = STAGE_SPEC.match(part.strip())
        if not match:
            raise ValueError(f"stage spec {spec!r} is not like 1-3,5")
        low = int(match.group(1))
        high = int(match.group(2) or low)
        if low < 1 or high < low:
            raise ValueError(f"stage spec {spec!r} has an empty or zero range")
        numbers.extend(range(low, high + 1))
    return numbers


def _stage_title(text: str) -> tuple:
    number, sep, title = (text or "").partition("=")
    if not sep or not number.strip().isdigit() or int(number) < 1:
        raise ValueError(f"--stage {text!r} is not like 3=Stage title")
    return int(number), title.strip()


def _require_unit(run, unit, command):
    if _unit(run) != unit:
        other = "enter" if unit == "stage" else "stage"
        raise ValueError(f"{command} is for {unit} runs; this is a {_unit(run)} run "
                         f"(use {other})")


def set_stages(run, numbers, status, now, *, sha=None, prior=False, title=None,
               executor=None, batch=None, mode=None, note=None) -> None:
    _require_unit(run, "stage", "stage")
    by_number = {s["number"]: s for s in run["stages"]}
    for number in numbers:
        stage = by_number.get(number)
        if stage is None:
            stage = by_number[number] = _stage(number, title)
            run["stages"].append(stage)
        elif title:
            stage["title"] = _clip(title, 300)
        for key, value in (("sha", sha), ("executor", executor), ("batch", batch),
                           ("mode", mode), ("note", _clip(note, 500))):
            if value is not None:
                stage[key] = value
        if status == "done":
            if stage["status"] == "done":
                continue  # a landing or a back-fill: only the fields above move
            stage["status"] = "done"
            if prior:
                stage.update(prior=True, started_at=None, finished_at=None, seconds=None)
            else:
                stage["finished_at"] = _stamp(now)
                begun = _parse(stage.get("started_at"))
                stage["seconds"] = _seconds(begun, now) if begun else None
        elif status == "running":
            stage.update(status="running", prior=False, started_at=_stamp(now),
                         finished_at=None, seconds=None)
        elif status == "pending":
            stage.update(status="pending", prior=False, started_at=None,
                         finished_at=None, seconds=None)
        else:
            stage["status"] = status
    run["stages"].sort(key=lambda s: s["number"])
    if status == "running" or (status == "done" and not prior):
        if run["phase"] == "readiness":
            run["phase"] = "stages"
        if status == "running" and not run.get("loop_started_at"):
            run["loop_started_at"] = _stamp(now)


def _close_pass(run, step, now) -> list:
    """Mark the running step done and return its pass as a history entry."""
    begun = _parse(step.get("started_at"))
    step.update(status="done", finished_at=_stamp(now))
    if begun is None:
        return []
    seconds = _seconds(begun, now)
    step["seconds"] = (step.get("seconds") or 0) + seconds
    step["passes"] = step.get("passes", 0) + 1
    return [{"skill": run["skill"], "step": step["id"], "title": step["title"],
             "seconds": seconds, "finished_at": _stamp(now)}]


def enter_step(run, step_id: str, now) -> list:
    """Start `step_id`: close the running step, mark steps jumped over
    `skipped`, or — when the step is at or before one already done — loop back,
    returning the steps from there on to pending. Re-entering the running step
    changes nothing. Returns the passes closed, for the step history."""
    _require_unit(run, "step", "enter")
    steps = run["steps"]
    ids = [s["id"] for s in steps]
    if step_id not in ids:
        raise ValueError(f"step {step_id!r} is not one of this run's steps ({', '.join(ids)})")
    target = ids.index(step_id)
    running = [i for i, s in enumerate(steps) if s["status"] == "running"]
    if running == [target]:
        return []
    entries = []
    for i in running:
        entries += _close_pass(run, steps[i], now)
    reached = max((i for i, s in enumerate(steps) if s["status"] in ("done", "skipped")),
                  default=-1)
    if target <= reached:
        run["loops"] = run.get("loops", 0) + 1
        for s in steps[target:reached + 1]:
            if s["status"] in ("done", "skipped"):
                s.update(status="pending", prior=False, finished_at=None)
    else:
        for s in steps[reached + 1:target]:
            if s["status"] == "pending":
                s["status"] = "skipped"
    steps[target].update(status="running", prior=False, started_at=_stamp(now),
                         finished_at=None)
    return entries


def finish_run(run, outcome: str, note, now) -> list:
    """Close the run. A completed run closes its running step and skips what it
    never entered; a halted one stops the running step, which then never
    reaches the history, since its pass did not finish."""
    run.update(status=outcome, finished_at=_stamp(now))
    if _unit(run) == "stage":
        run["phase"] = "done"
    if note is not None:
        run["note"] = _clip(note, 1000)
    entries = []
    for item in _items(run):
        if item["status"] == "running":
            if _unit(run) == "step" and outcome == "completed":
                entries += _close_pass(run, item, now)
            else:
                item["status"] = "stopped"
        elif _unit(run) == "step" and outcome == "completed" and item["status"] == "pending":
            item["status"] = "skipped"
    return entries


# --- long-running jobs -----------------------------------------------------


def job_estimate(elapsed, units_done, units_total, expected, expected_basis) -> dict:
    """Percent and time left for a running job, by the best basis available:
    matched output units once one has landed, else an expected duration (given
    or from history), else nothing but elapsed time. Never reads 100% while
    the job is still running."""
    result = {"percent": None, "remaining_seconds": None, "overrun_seconds": None,
              "basis": "none — elapsed time only"}
    if units_total and units_done > 0:
        left_units = max(units_total - units_done, 0)
        result.update(
            percent=min(99, round(100 * units_done / units_total)),
            remaining_seconds=round(elapsed / units_done * left_units),
            basis=f"units {units_done}/{units_total}",
        )
    elif expected is not None:
        result["basis"] = expected_basis
        if expected > 0 and elapsed < expected:
            result.update(percent=min(99, round(100 * elapsed / expected)),
                          remaining_seconds=round(expected - elapsed))
        else:
            result.update(percent=99, overrun_seconds=round(elapsed - expected))
    elif units_total:
        result.update(percent=0, basis=f"units 0/{units_total}")
    return result


def history_expected(history: Path, label: str, repo: str):
    """(median seconds, runs used) over the label's last successful runs in
    the repo."""
    try:
        lines = Path(history).read_text().splitlines()
    except OSError:
        return None
    seconds = []
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if (isinstance(entry, dict) and entry.get("label") == label
                and entry.get("repo") == repo
                and isinstance(entry.get("seconds"), (int, float))):
            seconds.append(entry["seconds"])
    recent = seconds[-HISTORY_WINDOW:]
    return (statistics.median(recent), len(recent)) if recent else None


class _JobTracker:
    """The job's record in its run. A failure to write turns it off for the
    rest of the job — never the command."""

    def __init__(self, run_id, label, stage, step, total, err):
        self.run_id = run_id
        self.live = True
        self.repo = None
        self.label = label
        self.stage = stage
        self.step = step
        self.total = total
        self.err = err
        self.units = 0
        self.job_id = None
        self.expected = None
        self.expected_basis = None
        self.started = _now()
        self.t0 = time.monotonic()
        self.last_write = 0.0
        self.lock = threading.Lock()

    def _update(self, status="running", exit_code=None):
        if not self.live:
            return
        with self.lock:
            try:
                update_run(self.run_id, lambda run, now: self._fill(run, now, status, exit_code))
                self.last_write = time.monotonic()
            except Exception as problem:
                self.live = False
                self.err.write(f"{SKIP}{problem}\n")
                self.err.flush()

    def _fill(self, run, now, status, exit_code):
        jobs = run.setdefault("jobs", [])
        if self.job_id is None:
            self.job_id = max((j.get("id", 0) for j in jobs), default=0) + 1
            self.repo = (run.get("repo") or {}).get("path")
            if self.expected is None:
                self._expect_from_history()
        record = next((j for j in jobs if j.get("id") == self.job_id), None)
        if record is None:
            record = {"id": self.job_id, "label": self.label, "stage": self.stage,
                      "step": self.step, "started_at": _stamp(self.started), "finished_at": None,
                      "exit_code": None}
            jobs.append(record)
            del jobs[:-MAX_JOBS]
        elapsed = time.monotonic() - self.t0
        estimate = job_estimate(elapsed, self.units, self.total, self.expected,
                                self.expected_basis)
        if status == "completed":
            estimate.update(percent=100, remaining_seconds=0, overrun_seconds=None)
        elif status != "running":
            estimate["remaining_seconds"] = None
        left = estimate["remaining_seconds"]
        record.update(
            status=status,
            updated_at=_stamp(now),
            elapsed_seconds=round(elapsed),
            units_done=self.units,
            units_total=self.total,
            expected_seconds=self.expected,
            eta=_stamp(now + timedelta(seconds=left)) if status == "running" and left is not None else None,
            **estimate,
        )
        parts = [f"{self.label}: {status}"]
        if estimate["percent"] is not None:
            parts.append(f"{estimate['percent']}%")
        parts.append(f"{human(elapsed)} elapsed")
        if status == "running" and left is not None:
            parts.append(f"~{human(left)} left")
        elif status == "running" and estimate["overrun_seconds"] is not None:
            parts.append(f"{human(estimate['overrun_seconds'])} over")
        record["summary"] = " · ".join(parts)
        if status != "running":
            record.update(finished_at=_stamp(now), exit_code=exit_code)

    def _expect_from_history(self):
        past = history_expected(_job_history_path(), self.label, self.repo)
        if past:
            self.expected = past[0]
            runs = "run" if past[1] == 1 else "runs"
            self.expected_basis = f"history: median {human(past[0])} of {past[1]} {runs}"

    def begin(self, expect):
        if expect is not None:
            self.expected = expect
            self.expected_basis = f"expected {human(expect)}"
        self._update()

    def tick(self):
        self._update()

    def add_units(self, count):
        self.units += count
        if time.monotonic() - self.last_write >= UNIT_WRITE_SECONDS:
            self._update()

    def end(self, status, exit_code):
        self._update(status, exit_code)
        if status != "completed" or not self.live:
            return
        _append_lines(_job_history_path(), [{
            "label": self.label, "repo": self.repo,
            "seconds": round(time.monotonic() - self.t0, 1), "finished_at": _stamp(_now()),
        }])


def run_job(run_id, label, command, *, stage=None, step=None, expect=None, total=None,
            match=None, interval=15.0) -> int:
    """Run `command`, streaming its output through, and keep its record in the
    run current while it runs. Returns the command's exit status."""
    out, err = sys.stdout, sys.stderr
    tracker = _JobTracker(run_id, label, stage, step, total, err)
    tracker.begin(expect)

    try:
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, errors="replace")
    except OSError as problem:
        err.write(f"{NOT_RUN}{problem}\n")
        tracker.end("failed", 127)
        return 127

    signalled = []

    def forward(signum, _frame):
        signalled.append(signum)
        try:
            proc.send_signal(signum)
        except OSError:
            pass

    previous = {}
    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous[sig] = signal.signal(sig, forward)

    stop = threading.Event()

    def ticker():
        while not stop.wait(interval):
            tracker.tick()

    thread = threading.Thread(target=ticker, daemon=True)
    thread.start()
    try:
        for line in iter(proc.stdout.readline, ""):
            out.write(line)
            out.flush()
            if match is not None:
                found = len(match.findall(line))
                if found:
                    tracker.add_units(found)
        code = proc.wait()
    finally:
        stop.set()
        thread.join()
        for sig, handler in previous.items():
            signal.signal(sig, handler)

    if code == 0:
        status = "completed"
    elif signalled or code < 0:
        status = "interrupted"
    else:
        status = "failed"
    tracker.end(status, code)
    return code if code >= 0 else 128 - code


# --- command line ----------------------------------------------------------


class _ArgError(Exception):
    """An argparse complaint, raised rather than exited on."""


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise _ArgError(message)


def _positive(kind):
    def convert(text):
        value = kind(text)
        if value <= 0:
            raise ValueError(f"{text} is not positive")
        return value
    convert.__name__ = kind.__name__
    return convert


def _step_id(text):
    if not STEP_ID.match(text or ""):
        raise ValueError(f"{text!r} is not a step id like 4 or 3a")
    return text


def _sha(text):
    if not SHA_PATTERN.match(text or ""):
        raise ValueError(f"{text!r} is not a commit sha")
    return text


def _parse_args(argv):
    parser = _Parser(prog="run_progress.py", add_help=False)
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init", add_help=False)
    init.add_argument("--skill", required=True, choices=SKILLS)
    init.add_argument("--subject", required=True)
    init.add_argument("--repo-root")
    init.add_argument("--branch")
    init.add_argument("--artefact")
    init.add_argument("--plan")
    init.add_argument("--design")
    init.add_argument("--tracker")
    init.add_argument("--stage", action="append", default=[], type=_stage_title)
    init.add_argument("--at", type=_step_id)

    stage = commands.add_parser("stage", add_help=False)
    stage.add_argument("--run", dest="run_id", required=True)
    stage.add_argument("--stage", dest="spec", required=True, type=parse_stage_list)
    stage.add_argument("--status", required=True, choices=STAGE_STATUSES)
    stage.add_argument("--sha", type=_sha)
    stage.add_argument("--prior", action="store_true")
    stage.add_argument("--title")
    stage.add_argument("--executor", choices=("main", "subagent"))
    stage.add_argument("--batch", type=_positive(int))
    stage.add_argument("--mode", choices=("serial", "parallel"))
    stage.add_argument("--note")

    enter = commands.add_parser("enter", add_help=False)
    enter.add_argument("--run", dest="run_id", required=True)
    enter.add_argument("--step", required=True, type=_step_id)

    update = commands.add_parser("update", add_help=False)
    update.add_argument("--run", dest="run_id", required=True)
    update.add_argument("--phase", choices=PHASES[:-1])
    update.add_argument("--strategy")
    update.add_argument("--note")
    for name in COUNTS:
        update.add_argument(f"--{name.replace('_', '-')}", dest=name, type=int)

    finish = commands.add_parser("finish", add_help=False)
    finish.add_argument("--run", dest="run_id", required=True)
    finish.add_argument("--outcome", required=True, choices=OUTCOMES)
    finish.add_argument("--note")

    args = parser.parse_args(argv)
    if args.command == "stage" and args.prior and args.status != "done":
        raise _ArgError("--prior goes only with --status done")
    if args.command == "init":
        numbers = [n for n, _ in args.stage]
        if len(numbers) != len(set(numbers)):
            raise _ArgError("a stage number appears twice")
        if args.skill == STAGE_SKILL and args.at:
            raise _ArgError(f"{STAGE_SKILL} records stages; --at is for step runs")
        if args.skill != STAGE_SKILL:
            if args.stage:
                raise _ArgError(f"{args.skill} records steps; --stage is for {STAGE_SKILL}")
            ids = [i for i, _, _ in STEP_PLANS[args.skill]]
            if args.at and args.at not in ids:
                raise _ArgError(f"--at {args.at} is not a {args.skill} step ({', '.join(ids)})")
    if args.command == "update" and any((getattr(args, n) or 0) < 0 for n in COUNTS):
        raise _ArgError("counts cannot be negative")
    return args


def _parse_job(argv):
    parser = _Parser(prog="run_progress.py job", add_help=False)
    parser.add_argument("--run", dest="run_id", required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--stage", type=_positive(int))
    parser.add_argument("--step", type=_step_id)
    parser.add_argument("--expect", type=_positive(float))
    parser.add_argument("--total", type=_positive(int))
    parser.add_argument("--match")
    parser.add_argument("--interval", type=_positive(float), default=15.0)
    args = parser.parse_args(argv)
    if args.stage and args.step:
        raise _ArgError("a job belongs to a --stage or a --step, not both")
    if args.match and not args.total:
        raise _ArgError("--match needs --total")
    args.match = re.compile(args.match) if args.match else None
    args.label = _clip(args.label.strip(), 120)
    if not args.label:
        raise _ArgError("--label is empty")
    return args


def _run_init(args) -> None:
    root = Path(args.repo_root).resolve() if args.repo_root else _find_repo_root(Path.cwd())
    _subject_for(args.skill, args.subject)
    path = progress_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _locked(path):
        now = _now()
        try:
            doc = _load(path)
        except FileNotFoundError:
            doc = None
        except (OSError, ValueError):
            # Unreadable: kept aside for the user, never silently discarded.
            path.replace(path.with_name(f"{path.name}.corrupt-{now.strftime('%Y%m%dT%H%M%SZ')}"))
            doc = None
        doc = doc or {"schema": SCHEMA, "updated_at": None, "runs": [], "history": []}
        record = new_run(
            run_id=_new_id(doc), skill=args.skill, repo_root=root, subject=args.subject,
            branch=args.branch or _branch(root), tracker=args.tracker, artefact=args.artefact,
            plan=args.plan, design=args.design, stages=args.stage, at=args.at, now=now,
        )
        add_run(doc, record)
        doc["updated_at"] = _stamp(now)
        _write(path, doc)
    print(f"{PREFIX}{record['id']} {path}")


def _change(args, change) -> None:
    record = update_run(args.run_id, change)
    print(f"{PREFIX}{record['progress']['summary']}")


def _run_enter(args) -> None:
    _change(args, lambda run, now: enter_step(run, args.step, now))


def _run_stage(args) -> None:
    _change(args, lambda run, now: set_stages(
        run, args.spec, args.status, now, sha=args.sha, prior=args.prior,
        title=args.title, executor=args.executor, batch=args.batch, mode=args.mode,
        note=args.note,
    ))


def _run_update(args) -> None:
    def change(run, now):
        stage_only = [args.phase, args.strategy, *(getattr(args, n) for n in COUNTS)]
        if _unit(run) != "stage" and any(v is not None for v in stage_only):
            raise ValueError("phase, strategy and counts are for stage runs; "
                             "a step run takes --note only")
        if args.phase:
            run["phase"] = args.phase
            if args.phase == "stages" and not run.get("loop_started_at"):
                run["loop_started_at"] = _stamp(now)
        if args.strategy is not None:
            run["strategy"] = _clip(args.strategy, 1000)
        if args.note is not None:
            run["note"] = _clip(args.note, 1000)
        for name in COUNTS:
            if getattr(args, name) is not None:
                run.setdefault("counts", {})[name] = getattr(args, name)

    _change(args, change)


def _run_finish(args) -> None:
    _change(args, lambda run, now: finish_run(run, args.outcome, args.note, now))


def _main_job(argv) -> int:
    """Exit status is the command's. A wrapper problem that stops the command
    from running exits 2, never 0, so it is never mistaken for a success."""
    err = sys.stderr
    if "--" not in argv or not argv[argv.index("--") + 1:]:
        err.write(f"{NOT_RUN}no command after --\n")
        return 2
    split = argv.index("--")
    try:
        args = _parse_job(argv[:split])
    except (_ArgError, SystemExit, re.error, ValueError) as problem:
        err.write(f"{NOT_RUN}{problem}\n")
        return 2
    return run_job(args.run_id, args.label, argv[split + 1:], stage=args.stage,
                   step=args.step, expect=args.expect, total=args.total, match=args.match,
                   interval=args.interval)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["job"]:
        return _main_job(argv[1:])
    try:
        args = _parse_args(argv)
    except (_ArgError, SystemExit) as problem:
        print(f"{SKIP}{problem}")
        return 0
    runners = {"init": _run_init, "stage": _run_stage, "enter": _run_enter,
               "update": _run_update, "finish": _run_finish}
    try:
        runners[args.command](args)
    except Exception as problem:
        print(f"{SKIP}{problem}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
