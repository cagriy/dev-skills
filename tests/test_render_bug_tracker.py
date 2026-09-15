"""Unit tests for scripts/render_bug_tracker.py — the bug-tracker renderer.

Runs the renderer against a synthetic repo under tmp_path: one open bug with
a screenshot, one closed bug with a Resolution section. The template is the
real templates/feature-tracker.html, so a template change that breaks the
Issues contract fails here rather than in a user's repo.
"""

import re
from pathlib import Path

import pytest
from helpers import REPO

from scripts import render_bug_tracker as rbt

TEMPLATE = REPO / "templates" / "feature-tracker.html"
NOW = "2026-09-13 14:00 UTC"

OPEN_REPORT = """# Bug 2: Login <button> does nothing on Safari

- **Severity:** High — blocks sign-in for every Safari user
- **Filed:** 2026-09-10

## Description
Clicking **Login** on Safari 17 does nothing; the `<form>` never submits.

## Expected behaviour
_Not specified._

## Steps to reproduce
1. Open the login page in Safari 17.
2. Click Login.

## Screenshots
![shot.png](shot.png)

## Triage

**Summary of understanding:** The click handler throws before submit.

**Probable affected area:** `web/login.js`

**Initial hypothesis:** A Safari-only `Event.submitter` access.

**Suggested next steps:**
- Reproduce in Safari with the console open.
- Guard the `submitter` read.

---
Filed via `/bug-submit` on 2026-09-10. To resolve, move this folder into `bugs/archive/`.
"""

CLOSED_REPORT = """# Bug 1: Export truncates names & titles

- **Severity:** low — cosmetic
- **Filed:** 2026-09-01

## Description
Names longer than 40 characters are cut in the CSV export.

## Expected behaviour
Full names are exported.

## Steps to reproduce
_Not specified._

## Screenshots
_None provided._

## Triage

**Summary of understanding:** Column width is hardcoded.

**Probable affected area:** `export/csv.py`

**Initial hypothesis:** A fixed slice at 40 characters.

**Suggested next steps:**
- Remove the slice.

## Resolution

- **Resolved:** 2026-09-03
- **Root cause:** `export/csv.py:12` sliced every cell to 40 characters
- **Fix:** removed the slice
- **Verification:** `test_export_keeps_long_names`

**Lessons learned:** none.

---
Filed via `/bug-submit` on 2026-09-01. To resolve, move this folder into `bugs/archive/`.
"""


@pytest.fixture
def repo(tmp_path):
    """A git work tree with one open and one closed bug."""
    (tmp_path / ".git").mkdir()
    open_dir = tmp_path / "bugs" / "bug-2-login-button-does-nothing-on-safari"
    open_dir.mkdir(parents=True)
    (open_dir / "bug-2-login-button-does-nothing-on-safari.md").write_text(OPEN_REPORT)
    (open_dir / "shot.png").write_bytes(b"\x89PNG")
    (open_dir / "notes.txt").write_text("not an image")
    closed_dir = tmp_path / "bugs" / "archive" / "bug-1-export-truncates-names"
    closed_dir.mkdir(parents=True)
    (closed_dir / "bug-1-export-truncates-names.md").write_text(CLOSED_REPORT)
    return tmp_path


def region(html, name):
    """The text between the ISSUES_<name> start and end markers."""
    match = re.search(
        rf"<!-- ISSUES_{name}:START -->(.*?)<!-- ISSUES_{name}:END -->", html, re.DOTALL
    )
    assert match, f"ISSUES_{name} markers missing from the rendered tracker"
    return match.group(1)


def render(repo, **kwargs):
    kwargs.setdefault("template", TEMPLATE)
    kwargs.setdefault("now", NOW)
    return rbt.render(repo, **kwargs)


class TestRender:
    def test_writes_the_tracker_and_reports_counts(self, repo):
        line = render(repo)
        assert line == "bug-tracker-render: bugs/bugs-tracker.html updated — 1 open, 1 closed"
        assert (repo / "bugs" / "bugs-tracker.html").exists()

    def test_sets_the_bug_tracker_chrome(self, repo):
        render(repo)
        html = (repo / "bugs" / "bugs-tracker.html").read_text()
        assert html.count('<body data-tracker-kind="bugs">') == 1
        assert "<body>" not in html
        assert "<title>Bug Tracker</title>" in html
        assert 'class="version-chip">v</span>' in html
        assert "Generated 2026-09-13" in html

    def test_blanks_every_feature_panel_token_but_keeps_the_legend(self, repo):
        render(repo)
        html = (repo / "bugs" / "bugs-tracker.html").read_text()
        legend, body = rbt.split_doc_comment(html)
        assert "{{DESIGN_BULLETS}}" in legend, "the doc-comment legend must survive"
        leaked = sorted(set(re.findall(r"\{\{[A-Z_]+\}\}", body)))
        assert not leaked, f"literal tokens leaked into the rendered body: {leaked}"

    def test_open_card_lands_in_the_open_region_with_relative_screenshot(self, repo):
        render(repo)
        html = (repo / "bugs" / "bugs-tracker.html").read_text()
        open_region = region(html, "OPEN")
        assert '<details class="issue" data-status="open">' in open_region
        assert '<span class="issue-number">#2</span>' in open_region
        assert '<span class="issue-sev sev-high">high</span>' in open_region
        assert '<span class="issue-date">2026-09-10</span>' in open_region
        assert '<img src="bug-2-login-button-does-nothing-on-safari/shot.png" alt="shot.png" />' in open_region
        assert "notes.txt" not in open_region
        assert "No open issues." not in open_region

    def test_closed_card_lands_in_the_closed_region_with_resolution(self, repo):
        render(repo)
        html = (repo / "bugs" / "bugs-tracker.html").read_text()
        closed_region = region(html, "CLOSED")
        assert '<details class="issue" data-status="closed">' in closed_region
        assert '<span class="issue-number">#1</span>' in closed_region
        assert "<h3>Resolution</h3>" in closed_region
        assert "<strong>Root cause:</strong>" in closed_region
        assert "<h3>Screenshots</h3>" not in closed_region, "no images → no Screenshots block"
        assert "<h3>Steps to reproduce</h3>" not in closed_region, "placeholder sections are skipped"
        assert "<h3>Expected behaviour</h3>" in closed_region

    def test_bug_text_is_escaped_and_lightly_formatted(self, repo):
        render(repo)
        html = (repo / "bugs" / "bugs-tracker.html").read_text()
        open_region = region(html, "OPEN")
        assert "&lt;button&gt;" in open_region
        assert "<button>" not in open_region
        assert "&lt;form&gt;" in open_region
        assert "<strong>Login</strong>" in open_region
        assert "<code>web/login.js</code>" in open_region
        assert "<ol><li>Open the login page in Safari 17.</li>" in open_region
        assert "<ul><li>Reproduce in Safari with the console open.</li>" in open_region
        assert "Filed via" not in open_region, "the report footer is not part of the card"
        closed_region = region(html, "CLOSED")
        assert "names &amp; titles" in closed_region

    def test_cards_sort_newest_first(self, repo):
        third = repo / "bugs" / "bug-3-newest"
        third.mkdir()
        (third / "bug-3-newest.md").write_text(OPEN_REPORT.replace("Bug 2", "Bug 3"))
        tenth = repo / "bugs" / "bug-10-tenth"
        tenth.mkdir()
        (tenth / "bug-10-tenth.md").write_text(OPEN_REPORT.replace("Bug 2", "Bug 10"))
        render(repo)
        open_region = region(repo.joinpath("bugs", "bugs-tracker.html").read_text(), "OPEN")
        numbers = re.findall(r'issue-number">#(\d+)<', open_region)
        assert numbers == ["10", "3", "2"], "numeric descending, not lexical"

    def test_updated_chip_and_placeholders(self, repo):
        for folder in (repo / "bugs" / "archive").iterdir():
            for f in folder.iterdir():
                f.unlink()
            folder.rmdir()
        line = render(repo)
        assert line.endswith("1 open, 0 closed")
        html = (repo / "bugs" / "bugs-tracker.html").read_text()
        assert region(html, "AT") == f"Updated {NOW}"
        assert region(html, "CLOSED").strip() == '<p class="empty">No closed issues.</p>'

    def test_regenerates_wholesale(self, repo):
        render(repo)
        tracker = repo / "bugs" / "bugs-tracker.html"
        tracker.write_text("stale hand edit")
        render(repo)
        assert "stale hand edit" not in tracker.read_text()

    def test_never_touches_bug_folders(self, repo):
        before = {p: p.read_bytes() for p in (repo / "bugs").rglob("*") if p.is_file()}
        render(repo)
        after = {p: p.read_bytes() for p in (repo / "bugs").rglob("*") if p.is_file()}
        after.pop(repo / "bugs" / "bugs-tracker.html")
        assert before == after

    def test_unreadable_report_degrades_to_a_minimal_card(self, repo):
        broken = repo / "bugs" / "bug-7-no-report"
        broken.mkdir()
        line = render(repo)
        assert line.endswith("2 open, 1 closed")
        open_region = region(repo.joinpath("bugs", "bugs-tracker.html").read_text(), "OPEN")
        assert '<span class="issue-number">#7</span>' in open_region
        assert '<span class="issue-title">no report</span>' in open_region


class TestSkips:
    def test_not_a_git_work_tree(self, tmp_path):
        assert render(tmp_path) == "bug-tracker-render: skipped — not in a git work tree"
        assert not (tmp_path / "bugs").exists()

    def test_repo_root_is_found_from_a_subdirectory(self, repo):
        sub = repo / "src" / "deep"
        sub.mkdir(parents=True)
        assert render(sub).endswith("1 open, 1 closed")
        assert (repo / "bugs" / "bugs-tracker.html").exists()

    def test_missing_template(self, repo):
        line = render(repo, template=repo / "nowhere.html")
        assert line == "bug-tracker-render: skipped — template not found"
        assert not (repo / "bugs" / "bugs-tracker.html").exists()

    def test_template_without_the_issues_markers(self, repo):
        bad = repo / "bad.html"
        bad.write_text("<html><body>{{FEATURE_TITLE}}</body></html>")
        line = render(repo, template=bad)
        assert line.startswith("bug-tracker-render: skipped — template has no ISSUES_")

    def test_main_never_raises(self, repo, capsys, monkeypatch):
        monkeypatch.chdir(repo)
        code = rbt.main(["--template", str(repo / "nowhere.html")])
        assert code == 0
        assert capsys.readouterr().out.strip() == "bug-tracker-render: skipped — template not found"
        code = rbt.main(["--now", NOW])
        assert code == 0
        assert capsys.readouterr().out.strip().endswith("1 open, 1 closed")


class TestContract:
    def test_blanks_exactly_the_twenty_feature_panel_tokens(self):
        expected = tuple(
            "{{%s_%s}}" % (prefix, suffix)
            for prefix in ("BRAINSTORMING", "DESIGN", "PLAN", "IMPLEMENTATION")
            for suffix in ("AT", "BULLETS", "DETAILS", "USAGE_CHIP", "USAGE")
        )
        assert tuple(rbt.FEATURE_PANEL_TOKENS) == expected

    def test_default_template_is_the_plugin_template(self):
        assert Path(rbt.default_template()).resolve() == TEMPLATE.resolve()

    def test_stdlib_only(self):
        source = (REPO / "scripts" / "render_bug_tracker.py").read_text()
        imports = re.findall(r"^(?:from|import)\s+([a-zA-Z_][\w.]*)", source, re.MULTILINE)
        third_party = [m for m in imports if m.split(".")[0] not in rbt.STDLIB_MODULES]
        assert not third_party, f"render_bug_tracker.py imports {third_party}"
