"""Unit tests for scripts/design_language.py — the DESIGN.md region tool.

Every test runs with the cwd set to tmp_path, so the script's write-path
confinement is exercised for real rather than mocked.
"""

import re
from pathlib import Path

import pytest
from helpers import REPO

from scripts import design_language as dl

SCRIPT = REPO / "scripts" / "design_language.py"
HEX64 = re.compile(r"[0-9a-f]{64}")

REGION = """## Design language — Acme

| Field | Value |
| --- | --- |
| Classification | partial |
| Platforms | web |
| Updated | 2026-11-01 10:00 UTC |
| Specimen | none |

### Visual Theme & Atmosphere

Calm and content-first.
"""


@pytest.fixture(autouse=True)
def in_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def doc(region=REGION, before="# DESIGN.md\n\nNotes.\n\n", after="\nMore notes.\n", nl="\n"):
    """A DESIGN.md text holding one region, in the given newline style."""
    return f"{before}{dl.START}\n{region}{dl.END}\n{after}".replace("\n", nl)


def put(path, text):
    path = Path(path)
    path.write_bytes(text.encode("utf-8"))
    return path


class TestRegion:
    def test_region_none_for_missing_file(self):
        assert dl.cmd_region("DESIGN.md") == "design-language: region none"

    def test_region_none_without_markers(self):
        put("DESIGN.md", "# DESIGN.md\n\nJust notes.\n")
        assert dl.cmd_region("DESIGN.md") == "design-language: region none"

    def test_region_reports_hash_and_text(self):
        put("DESIGN.md", doc())
        status, text = dl.cmd_region("DESIGN.md").split("\n", 1)
        digest = status.removeprefix("design-language: region ")
        assert HEX64.fullmatch(digest), status
        assert digest == dl.region_hash(REGION)
        assert text == REGION

    @pytest.mark.parametrize(
        "text, defect",
        [
            (f"{dl.START}\nx\n", "start marker without an end marker"),
            (f"x\n{dl.END}\n", "end marker without a start marker"),
            (doc() + doc(), "more than one region"),
            (f"{dl.START}\n{dl.START}\nx\n{dl.END}\n{dl.END}\n", "nested regions"),
        ],
        ids=["start-only", "end-only", "two-regions", "nested"],
    )
    def test_region_skips_malformed_markers(self, text, defect):
        put("DESIGN.md", text)
        line = dl.cmd_region("DESIGN.md")
        assert line.startswith("design-language: skipped — "), line
        assert defect in line, line
        assert "\n" not in line

    def test_hash_ignores_updated_and_specimen_rows(self):
        moved = REGION.replace("2026-11-01 10:00 UTC", "2026-11-04 09:30 UTC").replace(
            "| Specimen | none |", "| Specimen | https://claude.ai/artifact/abc |"
        )
        assert dl.region_hash(moved) == dl.region_hash(REGION)
        assert dl.region_hash(REGION.replace("Calm", "Loud")) != dl.region_hash(REGION)
        assert dl.region_hash(REGION.replace("| web |", "| web, ios |")) != dl.region_hash(REGION)

    def test_hash_ignores_managed_comment_and_line_endings(self):
        expected = dl.region_hash(REGION)
        assert dl.region_hash(dl.MANAGED_COMMENT + "\n" + REGION) == expected
        assert dl.region_hash(REGION.replace("\n", "\r\n")) == expected
        put("DESIGN.md", doc(dl.MANAGED_COMMENT + "\n" + REGION, nl="\r\n"))
        assert dl.cmd_region("DESIGN.md").split("\n", 1)[0] == f"design-language: region {expected}"

    def test_region_file_outside_cwd_is_refused(self, tmp_path_factory):
        outside = put(tmp_path_factory.mktemp("elsewhere") / "DESIGN.md", doc())
        assert dl.cmd_region(outside) == "design-language: skipped — path outside the project"


class TestMain:
    @pytest.mark.parametrize(
        "argv",
        [["bogus"], [], ["region"], ["region", "--file", "."]],
        ids=["unknown-subcommand", "no-subcommand", "missing-file-argument", "file-is-a-directory"],
    )
    def test_main_never_raises(self, argv, capsys):
        assert dl.main(argv) == 0
        lines = capsys.readouterr().out.splitlines()
        assert len(lines) == 1, lines
        assert lines[0].startswith("design-language: skipped — "), lines[0]

    def test_status_lines_carry_the_prefix(self, capsys):
        assert dl.STATUS_PREFIX == "design-language: "
        put("good.md", doc())
        put("bad.md", f"{dl.START}\n")
        for name in ("missing.md", "good.md", "bad.md"):
            assert dl.main(["region", "--file", name]) == 0
            lines = capsys.readouterr().out.splitlines()
            assert lines[0].startswith(dl.STATUS_PREFIX), lines
            assert [line for line in lines if line.startswith(dl.STATUS_PREFIX)] == lines[:1]


class TestContract:
    def test_stdlib_only(self):
        source = SCRIPT.read_text()
        imports = re.findall(r"^(?:from|import)\s+([a-zA-Z_][\w.]*)", source, re.MULTILINE)
        third_party = [m for m in imports if m.split(".")[0] not in dl.STDLIB_MODULES]
        assert not third_party, f"design_language.py imports {third_party}"
