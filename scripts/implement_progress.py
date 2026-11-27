"""Live progress file for feature-implement runs.

One JSON document per feature version, kept outside the project under
`<config-dir>/dev-skills/progress/<repo>-<hash>/feature-v<N>-<desc>.json`, so
anything the user points at it (a status line, a pane, a dashboard) can show
how far a run has got and how long it has left. The skill calls this script at
its milestones; the script owns the file's shape and every derived figure:

- stage counts, elapsed time, and the time left extrapolated from the stages
  this run completed (wall-clock throughput, so parallel batches count right);
- for a long-running command run through `job`, its own percent and time left,
  from matched output units, a stated expected duration, or the median of the
  same job's earlier successful runs — refreshed while the command runs.

Stdlib only: it runs as the system `python3`, not a project environment.
Every command except `job` always exits 0 and degrades to one
`implement-progress: skipped — …` line. `job` exits with the wrapped command's
status, which tracking never changes: a broken progress file still runs the
command. The file never records a command line or command output — only the
label the caller chose — so nothing secret a command carries reaches it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
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

SCHEMA = 1
PHASES = ("readiness", "stages", "closing", "done")
STAGE_STATUSES = ("pending", "running", "done", "blocked", "failed")
OUTCOMES = ("completed", "halted")
JOB_STATUSES = ("running", "completed", "failed", "interrupted")
COUNTS = ("deviations", "pending_verification", "handed_forward")

MAX_JOBS = 20
MAX_RUNS = 10
HISTORY_WINDOW = 5
UNIT_WRITE_SECONDS = 1.0

DESCRIPTION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")
SESSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SHA_PATTERN = re.compile(r"^[0-9a-f]{4,40}$")
STAGE_SPEC = re.compile(r"^(\d+)(?:-(\d+))?$")
PREFIX = "implement-progress: "
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


def progress_path(repo_root, version: int, description: str) -> Path:
    """`<progress dir>/<repo>-<8 hex of its real path>/feature-v<N>-<desc>.json`.

    The hash keeps two checkouts that share a directory name apart."""
    if not DESCRIPTION_PATTERN.match(description or "") or ".." in description:
        raise ValueError(f"description {description!r} is not a feature description")
    if version < 1:
        raise ValueError("feature version must be a positive integer")
    root = Path(repo_root).resolve()
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", root.name).strip("-.") or "repo"
    digest = hashlib.sha1(str(root).encode("utf-8")).hexdigest()[:8]
    return progress_dir() / f"{name}-{digest}" / f"feature-v{version}-{description}.json"


def _checked_file(path) -> Path:
    """The progress file, refused unless it sits under the progress dir."""
    resolved = Path(path).resolve()
    base = progress_dir().resolve()
    if base not in resolved.parents or resolved.suffix != ".json":
        raise ValueError(f"{path} is not a progress file under {base}")
    return resolved


def _history_path(path: Path) -> Path:
    return path.parent / "job-history.jsonl"


# --- file access -----------------------------------------------------------


@contextmanager
def _locked(path: Path):
    """Serialise read-modify-write across the main agent, stage subagents and
    job wrappers, which may all write one file at the same moment."""
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


def update_file(path: Path, change) -> dict:
    """Apply `change(doc, now)` under the lock, re-derive, write. Returns doc."""
    with _locked(path):
        doc = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
            raise ValueError(f"{path} is not a schema-{SCHEMA} progress file")
        now = _now()
        change(doc, now)
        doc["run"]["updated_at"] = _stamp(now)
        derive(doc, now)
        _write(path, doc)
    return doc


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


def _previous_run(previous) -> list:
    if not isinstance(previous, dict) or previous.get("schema") != SCHEMA:
        return []
    runs = [r for r in previous.get("runs") or [] if isinstance(r, dict)]
    run = previous.get("run") or {}
    progress = previous.get("progress") or {}
    status = run.get("status")
    runs.append({
        "id": run.get("id"),
        "started_at": run.get("started_at"),
        "finished_at": run.get("finished_at"),
        # A run still marked running when the next one starts never finished.
        "status": "abandoned" if status == "running" else status,
        "stages_done": progress.get("stages_done"),
        "stages_total": progress.get("stages_total"),
        "elapsed_seconds": progress.get("elapsed_seconds"),
    })
    return runs[-MAX_RUNS:]


def new_document(previous, *, repo_root, version, description, branch, plan, design,
                 tracker, stages, now) -> dict:
    root = Path(repo_root).resolve()
    session = os.environ.get("CLAUDE_CODE_SESSION_ID") or ""
    doc = {
        "schema": SCHEMA,
        "repo": {"name": root.name, "path": str(root), "branch": branch},
        "feature": {
            "version": version,
            "description": description,
            "plan": plan,
            "design": design,
            "tracker": tracker,
        },
        "run": {
            "id": now.strftime("%Y%m%dT%H%M%SZ"),
            "session_id": session if SESSION_PATTERN.match(session) else None,
            "status": "running",
            "phase": "readiness",
            "started_at": _stamp(now),
            "updated_at": _stamp(now),
            "loop_started_at": None,
            "finished_at": None,
            "strategy": None,
            "note": None,
        },
        "progress": {},
        "counts": {name: 0 for name in COUNTS},
        "stages": [_stage(n, title) for n, title in sorted(stages)],
        "jobs": [],
        "runs": _previous_run(previous),
    }
    derive(doc, now)
    return doc


def derive(doc: dict, now) -> None:
    """Recompute the `progress` block from the stages and jobs.

    Time left is the run's own throughput — wall-clock from the start of the
    stage loop to the latest completion, divided by the stages completed this
    run — projected over what remains. Stages committed before this run and
    blocked stages carry no timing and stay out of it."""
    run = doc["run"]
    stages = doc["stages"]
    total = len(stages)
    done = [s for s in stages if s["status"] == "done"]
    done_run = [s for s in done if not s.get("prior") and _parse(s.get("finished_at"))]
    blocked = sum(1 for s in stages if s["status"] == "blocked")
    remaining = max(0, total - len(done) - blocked)
    started = _parse(run["started_at"]) or now
    finished = _parse(run.get("finished_at"))
    elapsed = _seconds(started, finished or now)
    live = run["status"] == "running"

    per = left = eta = None
    if done_run:
        last = max(_parse(s["finished_at"]) for s in done_run)
        loop = _parse(run.get("loop_started_at")) or started
        per = max(0.0, (last - loop).total_seconds()) / len(done_run)
    if remaining == 0:
        left = 0
    elif per is not None and live:
        moment = last + timedelta(seconds=per * remaining)
        left = max(0, round((moment - now).total_seconds()))
        eta = _stamp(moment)

    jobs = [j for j in doc.get("jobs", []) if j.get("status") == "running"]
    parts = [f"{len(done)} of {total} stages done"]
    if blocked:
        parts.append(f"{blocked} blocked")
    parts.append(f"{human(elapsed)} elapsed")
    if live and remaining:
        parts.append(f"~{human(left)} left" if left is not None
                     else "time left known after the first stage")
    for job in jobs:
        pct = job.get("percent")
        parts.append(f"{job['label']} {pct}%" if pct is not None else f"{job['label']} running")
    if not live:
        parts.append(run["status"])

    doc["progress"] = {
        "stages_total": total,
        "stages_done": len(done),
        "stages_done_this_run": len(done_run),
        "stages_remaining": remaining,
        "stages_blocked": blocked,
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
        "jobs_running": len(jobs),
        "summary": " · ".join(parts),
    }


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


def set_stages(doc, numbers, status, now, *, sha=None, prior=False, title=None,
               executor=None, batch=None, mode=None, note=None) -> None:
    run = doc["run"]
    by_number = {s["number"]: s for s in doc["stages"]}
    for number in numbers:
        stage = by_number.get(number)
        if stage is None:
            stage = by_number[number] = _stage(number, title)
            doc["stages"].append(stage)
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
    doc["stages"].sort(key=lambda s: s["number"])
    if status == "running" or (status == "done" and not prior):
        if run["phase"] == "readiness":
            run["phase"] = "stages"
        if status == "running" and not run.get("loop_started_at"):
            run["loop_started_at"] = _stamp(now)


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


def history_expected(history: Path, label: str):
    """(median seconds, runs used) over the label's last successful runs."""
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
        if isinstance(entry, dict) and entry.get("label") == label and isinstance(
            entry.get("seconds"), (int, float)
        ):
            seconds.append(entry["seconds"])
    recent = seconds[-HISTORY_WINDOW:]
    return (statistics.median(recent), len(recent)) if recent else None


class _JobTracker:
    """The job's record in the progress file. A failure to write turns it off
    for the rest of the job — never the command."""

    def __init__(self, path, label, stage, total, err):
        self.path = path
        self.label = label
        self.stage = stage
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
        if self.path is None:
            return
        with self.lock:
            try:
                update_file(self.path, lambda doc, now: self._fill(doc, now, status, exit_code))
                self.last_write = time.monotonic()
            except Exception as problem:
                self.path = None
                self.err.write(f"{SKIP}{problem}\n")
                self.err.flush()

    def _fill(self, doc, now, status, exit_code):
        jobs = doc.setdefault("jobs", [])
        if self.job_id is None:
            self.job_id = max((j.get("id", 0) for j in jobs), default=0) + 1
        record = next((j for j in jobs if j.get("id") == self.job_id), None)
        if record is None:
            record = {"id": self.job_id, "label": self.label, "stage": self.stage,
                      "started_at": _stamp(self.started), "finished_at": None,
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

    def begin(self, expect):
        if self.path is not None and expect is None:
            past = history_expected(_history_path(self.path), self.label)
            if past:
                self.expected = past[0]
                runs = "run" if past[1] == 1 else "runs"
                self.expected_basis = f"history: median {human(past[0])} of {past[1]} {runs}"
        elif expect is not None:
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
        if status != "completed" or self.path is None:
            return
        line = json.dumps({"label": self.label,
                           "seconds": round(time.monotonic() - self.t0, 1),
                           "finished_at": _stamp(_now())}, ensure_ascii=False)
        try:
            with open(_history_path(self.path), "a", encoding="utf-8") as history:
                history.write(line + "\n")
        except OSError:
            pass


def run_job(file, label, command, *, stage=None, expect=None, total=None, match=None,
            interval=15.0) -> int:
    """Run `command`, streaming its output through, and keep its record in the
    progress file current while it runs. Returns the command's exit status."""
    out, err = sys.stdout, sys.stderr
    try:
        path = _checked_file(file)
        if not path.exists():
            raise ValueError(f"no progress file at {path}")
    except ValueError as problem:
        err.write(f"{SKIP}{problem}\n")
        path = None
    tracker = _JobTracker(path, label, stage, total, err)
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


def _sha(text):
    if not SHA_PATTERN.match(text or ""):
        raise ValueError(f"{text!r} is not a commit sha")
    return text


def _parse_args(argv):
    parser = _Parser(prog="implement_progress.py", add_help=False)
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init", add_help=False)
    init.add_argument("--repo-root", required=True)
    init.add_argument("--feature-version", type=_positive(int), required=True)
    init.add_argument("--description", required=True)
    init.add_argument("--branch")
    init.add_argument("--plan")
    init.add_argument("--design")
    init.add_argument("--tracker")
    init.add_argument("--stage", action="append", default=[], type=_stage_title)

    stage = commands.add_parser("stage", add_help=False)
    stage.add_argument("--file", required=True)
    stage.add_argument("--stage", dest="spec", required=True, type=parse_stage_list)
    stage.add_argument("--status", required=True, choices=STAGE_STATUSES)
    stage.add_argument("--sha", type=_sha)
    stage.add_argument("--prior", action="store_true")
    stage.add_argument("--title")
    stage.add_argument("--executor", choices=("main", "subagent"))
    stage.add_argument("--batch", type=_positive(int))
    stage.add_argument("--mode", choices=("serial", "parallel"))
    stage.add_argument("--note")

    update = commands.add_parser("update", add_help=False)
    update.add_argument("--file", required=True)
    update.add_argument("--phase", choices=PHASES[:-1])
    update.add_argument("--strategy")
    update.add_argument("--note")
    for name in COUNTS:
        update.add_argument(f"--{name.replace('_', '-')}", dest=name, type=int)

    finish = commands.add_parser("finish", add_help=False)
    finish.add_argument("--file", required=True)
    finish.add_argument("--outcome", required=True, choices=OUTCOMES)
    finish.add_argument("--note")

    args = parser.parse_args(argv)
    if args.command == "stage" and args.prior and args.status != "done":
        raise _ArgError("--prior goes only with --status done")
    if args.command == "init":
        numbers = [n for n, _ in args.stage]
        if len(numbers) != len(set(numbers)):
            raise _ArgError("a stage number appears twice")
    if args.command == "update" and any((getattr(args, n) or 0) < 0 for n in COUNTS):
        raise _ArgError("counts cannot be negative")
    return args


def _parse_job(argv):
    parser = _Parser(prog="implement_progress.py job", add_help=False)
    parser.add_argument("--file", required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--stage", type=_positive(int))
    parser.add_argument("--expect", type=_positive(float))
    parser.add_argument("--total", type=_positive(int))
    parser.add_argument("--match")
    parser.add_argument("--interval", type=_positive(float), default=15.0)
    args = parser.parse_args(argv)
    if args.match and not args.total:
        raise _ArgError("--match needs --total")
    args.match = re.compile(args.match) if args.match else None
    args.label = _clip(args.label.strip(), 120)
    if not args.label:
        raise _ArgError("--label is empty")
    return args


def _run_init(args) -> None:
    path = progress_path(args.repo_root, args.feature_version, args.description)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _locked(path):
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            previous = None
        doc = new_document(
            previous, repo_root=args.repo_root, version=args.feature_version,
            description=args.description, branch=args.branch, plan=args.plan,
            design=args.design, tracker=args.tracker, stages=args.stage, now=_now(),
        )
        _write(path, doc)
    print(f"{PREFIX}{path}")


def _change(args, change) -> None:
    path = _checked_file(args.file)
    if not path.exists():
        raise ValueError(f"no progress file at {path}")
    doc = update_file(path, change)
    print(f"{PREFIX}{doc['progress']['summary']}")


def _run_stage(args) -> None:
    _change(args, lambda doc, now: set_stages(
        doc, args.spec, args.status, now, sha=args.sha, prior=args.prior,
        title=args.title, executor=args.executor, batch=args.batch, mode=args.mode,
        note=args.note,
    ))


def _run_update(args) -> None:
    def change(doc, now):
        run = doc["run"]
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
                doc.setdefault("counts", {})[name] = getattr(args, name)

    _change(args, change)


def _run_finish(args) -> None:
    def change(doc, now):
        doc["run"].update(status=args.outcome, phase="done", finished_at=_stamp(now))
        if args.note is not None:
            doc["run"]["note"] = _clip(args.note, 1000)
        for stage in doc["stages"]:
            if stage["status"] == "running":
                stage["status"] = "stopped"

    _change(args, change)


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
    return run_job(args.file, args.label, argv[split + 1:], stage=args.stage,
                   expect=args.expect, total=args.total, match=args.match,
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
    runners = {"init": _run_init, "stage": _run_stage, "update": _run_update,
               "finish": _run_finish}
    try:
        runners[args.command](args)
    except Exception as problem:
        print(f"{SKIP}{problem}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
