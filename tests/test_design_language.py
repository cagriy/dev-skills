"""Unit tests for scripts/design_language.py — the DESIGN.md region tool.

Every test runs with the cwd set to tmp_path, so the script's write-path
confinement is exercised for real rather than mocked.
"""

import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
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

# Every heading in schema order, every table populated, both Do and Don't
# bullets, one Decisions row per Status form, one section left empty.
FULL_REGION = """## Design language — Acme Billing

| Field | Value |
| --- | --- |
| Classification | partial |
| Platforms | web, ios |
| Updated | 2026-11-01 10:00 UTC |
| Specimen | https://claude.ai/artifact/abc123 |

### Visual Theme & Atmosphere

Calm, content-first screens with one indigo accent
and generous white space.
Source: user: 2026-10-30

### Color Palette & Roles

| Token | Light | Dark | Role | Group | Source |
| --- | --- | --- | --- | --- | --- |
| color.accent | #4f46e5 | #818cf8 | links, primary actions | brand | code: src/theme.css:12 |
| color.surface | rgb(250, 250, 250) | — | page background | surface | code: src/theme.css:4 |
| color.danger | hsl(0 72% 51%) | oklch(0.7 0.19 22) | errors | feedback | user · pending v7 |

### Typography Rules

| Token | Family | Weight | Size / line height | Treatment | Source |
| --- | --- | --- | --- | --- | --- |
| type.body | "Inter", system-ui, sans-serif | 400 | 1rem / 1.5 | sentence case | code: src/theme.css:30 |
| type.heading | Inter | bold | 24px/32px | tight tracking | skill: decision 4 |

### Layout Principles

- Comfortable density on an 8px grid — user: 2026-10-30
- Content column at most 1080px wide — code: src/layout.css:3

| Spacing token | Value | Source |
| --- | --- | --- |
| space.2 | 8px | code: src/theme.css:40 |
| space.4 | 1rem | code: src/theme.css:41 |

| Radius token | Value | Source |
| --- | --- | --- |
| radius.card | 14px | code: src/theme.css:50 |
| radius.pill | 999px | mockup: features/feature-v3-x/mockups/mockup-v3-overview.html |

### Depth & Elevation

| Token | Value | Use | Source |
| --- | --- | --- | --- |
| shadow.card | 0 1px 2px rgba(0, 0, 0, 0.08), 0 4px 12px -2px #0000001a | cards | code: src/theme.css:60 |
| shadow.flat | none | tables | user: DESIGN.md |

### Component Stylings

| Category | Canonical | Variants | Tokens | Source |
| --- | --- | --- | --- | --- |
| button | Button | primary, secondary, ghost | bg=color.accent; radius=radius.pill | code: src/components/Button.tsx:1 |
| alert | InlineAlert | — | border=color.danger | user · pending v7 |

### Responsive Behavior

- Single column below 640px — code: src/layout.css:20

### Iconography & Motion

None recorded — no icon set or motion in code yet

### Copy Tone

- Plain, direct, sentence case — skill: decision 4

### Do's and Don'ts

- Do: keep one primary action per screen — user: 2026-10-30
- Don't: use colour alone to signal state — skill: decision 4

### Decisions

| # | Decision | By | Date | Status |
| --- | --- | --- | --- | --- |
| 1 | Accent is indigo | user | 2026-10-30 | active |
| 2 | Danger colour is red | user | 2026-11-01 | pending v7 |
| 3 | Accent is blue | skill | 2026-10-01 | superseded by 1 |
| 4 | Plain, direct copy | skill | 2026-10-30 | drift |

### Drift

- Billing page copy uses title case — code: src/pages/Billing.tsx:14
"""


def sections_of(region):
    """The region split before each `### ` heading; [0] is the header section."""
    return re.split(r"(?m)^(?=### )", region)


def with_section(title, body, region=FULL_REGION):
    """The region with one section's body (or the header's, for title None) replaced."""
    parts = sections_of(region)
    index = 0 if title is None else next(i for i, p in enumerate(parts) if p.startswith(f"### {title}\n"))
    heading = parts[index].split("\n", 1)[0]
    parts[index] = f"{heading}\n\n{body}\n\n"
    return "".join(parts)


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


def swap_sections(region, first, second):
    parts = sections_of(region)
    i, j = (next(k for k, p in enumerate(parts) if p.startswith(f"### {t}\n")) for t in (first, second))
    parts[i], parts[j] = parts[j], parts[i]
    return "".join(parts)


def drop_section(region, title):
    return "".join(p for p in sections_of(region) if not p.startswith(f"### {title}\n"))


def swap(old, new):
    def mutate(region):
        assert old in region, f"fixture lacks {old!r}"
        return region.replace(old, new, 1)

    return mutate


SCHEMA_VIOLATIONS = [
    ("missing-heading", lambda r: drop_section(r, "Copy Tone"), "missing heading '### Copy Tone'"),
    ("headings-out-of-order", lambda r: swap_sections(r, "Decisions", "Drift"), "headings out of order"),
    ("unknown-heading", swap("### Drift", "### Drift log"), "unexpected heading '### Drift log'"),
    ("text-before-header", lambda r: "Intro.\n\n" + r, "text before the header heading"),
    ("missing-column", swap("| Token | Light | Dark | Role | Group | Source |", "| Token | Light | Dark | Group | Source |"), "missing column 'Role'"),
    ("short-row", swap("| space.2 | 8px | code: src/theme.css:40 |", "| space.2 | 8px |"), "row 'space.2' has 2 cells, expected 3"),
    ("untagged-row", swap("| page background | surface | code: src/theme.css:4 |", "| page background | surface |  |"), "row 'color.surface': untagged"),
    ("untagged-bullet", swap("- Single column below 640px — code: src/layout.css:20", "- Single column below 640px"), "untagged bullet"),
    ("untagged-theme", swap("Source: user: 2026-10-30\n", ""), "Visual Theme & Atmosphere: untagged"),
    ("bad-source-tag", swap("code: src/theme.css:12", "theme.css line 12"), "bad source tag 'theme.css line 12'"),
    ("bad-colour", swap("| #4f46e5 |", "| red;background:x |"), "bad colour 'red;background:x' in Light"),
    ("bad-dark-colour", swap("| #818cf8 |", "| var(--accent) |"), "bad colour 'var(--accent)' in Dark"),
    ("bad-size", swap("| 8px |", "| 8 |"), "bad size '8' in Value"),
    ("bad-radius", swap("| 14px |", "| calc(1rem + 2px) |"), "bad size 'calc(1rem + 2px)' in Value"),
    ("bad-line-height", swap("1rem / 1.5", "1rem / normal"), "bad line height 'normal'"),
    ("size-without-line-height", swap("1rem / 1.5", "1rem"), "Size / line height must be '<size> / <line height>'"),
    ("bad-family", swap("| Inter | bold |", "| Inter; color: red | bold |"), "bad family"),
    ("bad-weight", swap("| 400 |", "| 450 |"), "bad weight '450'"),
    ("bad-shadow", swap("| none | tables |", "| 0 1px red | tables |"), "bad shadow '0 1px red'"),
    ("unknown-group", swap("| brand |", "| accent |"), "unknown group 'accent'"),
    ("unknown-category", swap("| alert | InlineAlert |", "| toast | InlineAlert |"), "unknown category 'toast'"),
    ("bad-component-tokens", swap("bg=color.accent; radius=radius.pill", "bg color.accent"), "bad token pair 'bg color.accent'"),
    ("bad-decision-by", swap("| user | 2026-10-30 | active |", "| team | 2026-10-30 | active |"), "By must be user or skill, got 'team'"),
    ("bad-decision-status", swap("| 2026-10-30 | drift |", "| 2026-10-30 | retired |"), "bad status 'retired'"),
    ("bad-decision-number", swap("| 4 | Plain", "| four | Plain"), "bad decision number 'four'"),
    ("bad-decision-date", swap("| 2026-11-01 | pending v7 |", "| 1 Nov | pending v7 |"), "bad date '1 Nov'"),
    ("bullet-without-do-prefix", swap("- Do: keep one", "- Keep one"), "bullet without a 'Do:' or 'Don't:' prefix"),
    ("prose-in-bullet-section", swap("- Single column below 640px", "Single column below 640px"), "Responsive Behavior: unexpected line"),
    ("missing-radius-table", lambda r: re.sub(r"\| Radius token[^#]*?(?=\n### )", "", r, flags=re.S), "missing the Radius token table"),
    ("empty-header-table", lambda r: re.sub(r"\| Classification.*?\| Specimen [^\n]*\n", "", r, flags=re.S), "missing row 'Classification'"),
    ("bad-classification", swap("| partial |", "| mature |"), "bad classification 'mature'"),
    ("bad-specimen-url", swap("https://claude.ai/artifact/abc123", "javascript:alert(1)"), "bad specimen URL"),
    ("empty-platforms", swap("| web, ios |", "| , |"), "Platforms is empty"),
    ("blank-section", lambda r: with_section("Copy Tone", "", r), "Copy Tone: no content"),
    ("table-in-bullet-section", swap("- Plain, direct, sentence case — skill: decision 4", "| A | B |\n| - | - |"), "Copy Tone: unexpected table 'A | B'"),
    ("table-without-separator", swap("| Status |\n| --- | --- | --- | --- | --- |\n", "| Status |\n"), "table without a separator row"),
]


class TestSchema:
    def test_full_region_parses_into_the_documented_shape(self):
        data = dl.parse_region(FULL_REGION)
        assert set(data) == {
            "project", "classification", "platforms", "updated", "specimen_url",
            "theme", "dos", "donts", "colours", "type", "layout", "spacing", "radius",
            "elevation", "components", "decisions", "drift", "counts", "empty",
        }
        assert data["project"] == "Acme Billing"
        assert data["classification"] == "partial"
        assert data["platforms"] == ["web", "ios"]
        assert data["updated"] == "2026-11-01 10:00 UTC"
        assert data["specimen_url"] == "https://claude.ai/artifact/abc123"
        assert data["theme"] == {
            "text": "Calm, content-first screens with one indigo accent and generous white space.",
            "source": "user: 2026-10-30",
        }
        assert data["dos"] == [{"text": "keep one primary action per screen", "source": "user: 2026-10-30"}]
        assert data["donts"] == [{"text": "use colour alone to signal state", "source": "skill: decision 4"}]
        assert data["colours"][0] == {
            "token": "color.accent", "light": "#4f46e5", "dark": "#818cf8",
            "role": "links, primary actions", "group": "brand", "source": "code: src/theme.css:12",
        }
        assert data["colours"][1]["dark"] is None, "a — cell means no dark value"
        assert data["type"][0] == {
            "token": "type.body", "family": '"Inter", system-ui, sans-serif', "weight": "400",
            "size": "1rem", "line": "1.5", "treatment": "sentence case", "source": "code: src/theme.css:30",
        }
        assert (data["type"][1]["size"], data["type"][1]["line"]) == ("24px", "32px")
        assert data["layout"][1] == {"text": "Content column at most 1080px wide", "source": "code: src/layout.css:3"}
        assert data["spacing"] == [
            {"token": "space.2", "value": "8px", "source": "code: src/theme.css:40"},
            {"token": "space.4", "value": "1rem", "source": "code: src/theme.css:41"},
        ]
        assert data["radius"][1] == {
            "token": "radius.pill", "value": "999px",
            "source": "mockup: features/feature-v3-x/mockups/mockup-v3-overview.html",
        }
        assert data["elevation"][1] == {"token": "shadow.flat", "value": "none", "use": "tables", "source": "user: DESIGN.md"}
        assert data["components"] == [
            {
                "category": "button", "canonical": "Button", "variants": ["primary", "secondary", "ghost"],
                "tokens": {"bg": "color.accent", "radius": "radius.pill"}, "source": "code: src/components/Button.tsx:1",
            },
            {
                "category": "alert", "canonical": "InlineAlert", "variants": [],
                "tokens": {"border": "color.danger"}, "source": "user · pending v7",
            },
        ]
        assert [d["status"] for d in data["decisions"]] == ["active", "pending v7", "superseded by 1", "drift"]
        assert data["decisions"][0] == {"n": 1, "decision": "Accent is indigo", "by": "user", "date": "2026-10-30", "status": "active"}
        assert data["drift"] == ["Billing page copy uses title case — code: src/pages/Billing.tsx:14"]
        assert data["counts"] == {
            "colours": 3, "type": 2, "components": 2, "decisions_user": 2,
            "decisions_skill": 2, "pending": 1, "drift": 1,
        }
        assert data["empty"] == {"Iconography & Motion": "None recorded — no icon set or motion in code yet"}

    @pytest.mark.parametrize("mutate, defect", [v[1:] for v in SCHEMA_VIOLATIONS], ids=[v[0] for v in SCHEMA_VIOLATIONS])
    def test_schema_violations_are_refused(self, mutate, defect):
        with pytest.raises(dl.SchemaError) as refused:
            dl.parse_region(mutate(FULL_REGION))
        assert defect in str(refused.value)

    def test_managed_comment_is_ignored(self):
        assert dl.parse_region(dl.MANAGED_COMMENT + "\n" + FULL_REGION) == dl.parse_region(FULL_REGION)

    @pytest.mark.parametrize(
        "tag",
        [
            "code: src/theme.css:12",
            "mockup: features/feature-v3-x/mockups/mockup-v3-overview.html",
            "user: 2026-10-30",
            "user: DESIGN.md",
            "user · pending v12",
            "skill: decision 3",
        ],
    )
    def test_every_source_tag_form_is_accepted(self, tag):
        assert dl.SOURCE_TAG_RE.match(tag)
        bullet = "- Single column below 640px — "
        data = dl.parse_region(swap(bullet + "code: src/layout.css:20", bullet + tag)(FULL_REGION))
        assert data["project"] == "Acme Billing"

    @pytest.mark.parametrize(
        "tag",
        ["code: src/theme.css", "code: /etc/theme.css:1", "mockup: /abs.html", "user: yesterday",
         "user: pending v7", "skill: decided", "code:src/a.css:1", "code: src/a.css:1 extra"],
    )
    def test_malformed_source_tags_are_refused(self, tag):
        assert not dl.SOURCE_TAG_RE.match(tag)

    def test_colour_forms(self):
        for good in ("#abc", "#abcd", "#AABBCC", "#aabbccdd", "rgb(0, 0, 0)", "rgba(0,0,0,0.5)",
                     "rgb(0 0 0 / 50%)", "hsl(210 40% 50%)", "hsla(210, 40%, 50%, .5)",
                     "oklch(0.7 0.19 22)", "oklch(70% 0.19 22deg)"):
            assert dl.is_colour(good), good
        for bad in ("url(x.png)", "red;background:x", "var(--x)", "red", "#abcde", "#ggg",
                    "rgb(0, 0, var(--x))", "color-mix(in srgb, red, blue)", "rgb(0,0,0);x:y", "rgb(0, 0)", ""):
            assert not dl.is_colour(bad), bad

    def test_size_forms(self):
        for good in ("8px", "1rem", "1.5em", "50%", "999px", ".5rem"):
            assert dl.is_size(good), good
        for bad in ("8", "0", "calc(1rem + 2px)", "1vh", "-4px", "8 px", "8px;", ""):
            assert not dl.is_size(bad), bad

    def test_line_height_and_elevation_and_font_values(self):
        for good in ("1.5", "1", "24px", "1.25rem"):
            assert dl.is_line_height(good), good
        for bad in ("normal", "1.5;", "calc(1em)", ""):
            assert not dl.is_line_height(bad), bad
        for good in ("none", "0 1px 2px #000", "inset 0 0 0 1px rgba(0, 0, 0, .1)",
                     "0 1px 2px rgba(0, 0, 0, 0.08), 0 4px 12px -2px #0003", "#000 0 1px 2px inset"):
            assert dl.is_shadow(good), good
        for bad in ("0 1px", "1px 2px 3px 4px 5px #000", "0 1px 2px red", "0 1px 2px #000 #fff",
                    "url(x)", "0 1px 2px #000; color: red", "inset inset 0 0 #000", "0 1px 2px 50% #000", ""):
            assert not dl.is_shadow(bad), bad
        for good in ('"Inter", system-ui, sans-serif', "Source Sans 3", "'Fira Code'"):
            assert dl.is_family(good), good
        for bad in ("Inter; color: red", "Inter</style>", "a(b)", "Inter{}", ""):
            assert not dl.is_family(bad), bad
        for good in ("100", "400", "900", "normal", "bold"):
            assert dl.is_weight(good), good
        for bad in ("450", "1000", "50", "bolder", "400;", ""):
            assert not dl.is_weight(bad), bad

    def test_specimen_field_forms(self):
        for good in ("none", "https://claude.ai/artifact/abc123"):
            assert dl.is_specimen_url(good), good
        for bad in ("http://claude.ai/x", "javascript:alert(1)", "https://a b", 'https://a"b', "https://a<b", ""):
            assert not dl.is_specimen_url(bad), bad

    def test_empty_section_marker_is_valid_except_for_the_header(self):
        marker = "None recorded — not evidenced yet"
        for title in (p.split("\n", 1)[0][4:] for p in sections_of(FULL_REGION)[1:]):
            assert dl.parse_region(with_section(title, marker))["empty"][title] == marker
        with pytest.raises(dl.SchemaError, match="expected one Field \\| Value table"):
            dl.parse_region(with_section(None, marker))

    def test_empty_sections_carry_no_entries(self):
        region = FULL_REGION
        for title in ("Visual Theme & Atmosphere", "Color Palette & Roles", "Layout Principles", "Do's and Don'ts"):
            region = with_section(title, "None recorded — not evidenced yet", region)
        data = dl.parse_region(with_section("Drift", "None.", region))
        assert data["theme"] is None
        assert data["colours"] == data["layout"] == data["spacing"] == data["radius"] == []
        assert data["dos"] == data["donts"] == data["drift"] == []
        assert data["counts"]["colours"] == data["counts"]["drift"] == 0
        assert "Drift" not in data["empty"], "`None.` is the Drift section's own no-entries form"


NOW = datetime(2026, 11, 4, 9, 30, tzinfo=timezone.utc)
UPDATED_ROW = "| Updated | 2026-11-01 10:00 UTC |"
STAMPED_ROW = "| Updated | 2026-11-04 09:30 UTC |"


@pytest.fixture
def write(tmp_path_factory):
    """cmd_write with each --region file under its own directory outside the cwd."""
    inputs = tmp_path_factory.mktemp("inputs")

    def run(region=FULL_REGION, expect="none", now=NOW, file="DESIGN.md"):
        source = put(inputs / f"region-{len(list(inputs.iterdir()))}.md", region)
        return dl.cmd_write(file, source, expect, now=now)

    return run


def outcome(line, digest_re=HEX64):
    """`design-language: <outcome> <digest>` → (outcome, digest)."""
    word, digest = line.removeprefix(dl.STATUS_PREFIX).split(" ")
    assert digest_re.fullmatch(digest), line
    return word, digest


class TestWrite:
    def test_creates_missing_file_with_preamble(self, write):
        assert outcome(write())[0] == "created"
        assert Path("DESIGN.md").read_bytes().decode() == (
            dl.PREAMBLE + dl.START + "\n" + dl.MANAGED_COMMENT + "\n"
            + FULL_REGION.rstrip("\n").replace(UPDATED_ROW, STAMPED_ROW) + "\n" + dl.END + "\n"
        )
        assert dl.PREAMBLE.startswith("# DESIGN.md\n\nNotes outside the marked region are yours: ")

    def test_appends_to_file_without_region(self, write):
        original = "# DESIGN.md\n\nOur own notes.\n"
        put("DESIGN.md", original)
        assert outcome(write())[0] == "appended"
        text = Path("DESIGN.md").read_bytes().decode()
        assert text.startswith(original + "\n" + dl.START + "\n" + dl.MANAGED_COMMENT + "\n")
        assert text.endswith(dl.END + "\n")

    @pytest.mark.parametrize("nl", ["\n", "\r\n"], ids=["LF", "CRLF"])
    def test_replaces_region_preserving_outside_bytes(self, write, nl):
        before = (
            "# DESIGN.md" + nl + nl + "Overrides: accent stays indigo.  " + nl + nl
        )
        put("DESIGN.md", doc(dl.MANAGED_COMMENT + "\n" + FULL_REGION, before=before, after="\nTail\tnotes.", nl=nl))
        old = Path("DESIGN.md").read_bytes()
        line = write(FULL_REGION.replace("Calm", "Quiet"), expect=dl.region_hash(FULL_REGION))
        assert outcome(line)[0] == "written"
        new = Path("DESIGN.md").read_bytes()
        start, end = dl.START.encode(), dl.END.encode()
        assert new[:new.index(start)] == old[:old.index(start)]
        assert new[new.index(end):] == old[old.index(end):]
        region = new[new.index(start):new.index(end)].decode()
        assert "Quiet" in region and STAMPED_ROW in region
        assert region.count(nl) == region.count("\n"), "the region follows the file's newline style"

    def test_unchanged_when_only_updated_differs(self, write):
        write()
        before, stat = Path("DESIGN.md").read_bytes(), os.stat("DESIGN.md")
        line = write(FULL_REGION.replace(UPDATED_ROW, "| Updated | — |"), expect=dl.region_hash(FULL_REGION))
        assert outcome(line) == ("unchanged", dl.region_hash(FULL_REGION))
        assert Path("DESIGN.md").read_bytes() == before
        assert os.stat("DESIGN.md").st_mtime_ns == stat.st_mtime_ns

    def test_updated_row_set_only_when_content_changes(self, write):
        write(now=datetime(2026, 11, 1, 8, 0, tzinfo=timezone.utc))
        assert "| Updated | 2026-11-01 08:00 UTC |" in Path("DESIGN.md").read_text()
        changed = FULL_REGION.replace("Calm", "Quiet")
        write(changed, expect=dl.region_hash(FULL_REGION), now=datetime(2026, 11, 2, 8, 0, tzinfo=timezone.utc))
        assert "| Updated | 2026-11-02 08:00 UTC |" in Path("DESIGN.md").read_text()
        write(changed, expect=dl.region_hash(changed), now=datetime(2026, 11, 3, 8, 0, tzinfo=timezone.utc))
        assert "| Updated | 2026-11-02 08:00 UTC |" in Path("DESIGN.md").read_text()

    def test_specimen_url_change_is_written_without_changing_the_hash(self, write):
        write()
        recorded = FULL_REGION.replace("https://claude.ai/artifact/abc123", "https://claude.ai/artifact/new456")
        line = write(recorded, expect=dl.region_hash(FULL_REGION))
        assert outcome(line) == ("written", dl.region_hash(FULL_REGION))
        assert "| Specimen | https://claude.ai/artifact/new456 |" in Path("DESIGN.md").read_text()

    def test_stale_expect_is_refused(self, write):
        write()
        before = Path("DESIGN.md").read_bytes()
        changed = FULL_REGION.replace("Calm", "Quiet")
        assert write(changed, expect="0" * 64) == "design-language: skipped — region changed since read"
        assert write(changed, expect="none") == "design-language: skipped — region changed since read"
        assert Path("DESIGN.md").read_bytes() == before
        put("NOTES.md", "# Notes\n")
        assert write(file="NOTES.md", expect=dl.region_hash(FULL_REGION)) == (
            "design-language: skipped — region changed since read"
        ), "a hash for a file that has no region is stale too"

    def test_region_containing_a_marker_is_refused(self, write):
        line = write(FULL_REGION + dl.END + "\n")
        assert line == "design-language: skipped — the region input contains a design-language marker"
        assert not Path("DESIGN.md").exists()

    def test_schema_violation_is_refused(self, write):
        line = write(FULL_REGION.replace("| brand |", "| accent |"))
        assert line == (
            "design-language: skipped — schema: Color Palette & Roles: row 'color.accent': unknown group 'accent'"
        )
        assert not Path("DESIGN.md").exists()

    def test_write_reports_the_new_hash(self, write, capsys, tmp_path_factory):
        line = write()
        assert outcome(line) == ("created", dl.region_hash(FULL_REGION))
        assert dl.cmd_region("DESIGN.md").split("\n", 1)[0] == f"design-language: region {outcome(line)[1]}"
        source = put(tmp_path_factory.mktemp("cli") / "region.md", FULL_REGION.replace("Calm", "Quiet"))
        assert dl.main(["write", "--file", "DESIGN.md", "--region", str(source), "--expect", outcome(line)[1]]) == 0
        printed = capsys.readouterr().out
        assert printed == f"design-language: written {dl.region_hash(FULL_REGION.replace('Calm', 'Quiet'))}\n"

    def test_file_outside_cwd_is_refused(self, write, tmp_path_factory):
        outside = tmp_path_factory.mktemp("elsewhere") / "DESIGN.md"
        assert write(file=outside) == "design-language: skipped — path outside the project"
        assert not outside.exists()

    def test_region_input_outside_cwd_is_accepted(self, write, in_tmp):
        assert outcome(write())[0] == "created"
        assert (in_tmp / "DESIGN.md").exists()

    def test_write_is_atomic(self, write, in_tmp, monkeypatch):
        write()
        assert sorted(os.listdir(in_tmp)) == ["DESIGN.md"]
        before = Path("DESIGN.md").read_bytes()
        assert "schema" in write(FULL_REGION.replace("| brand |", "| accent |"), expect=dl.region_hash(FULL_REGION))

        def broken_replace(src, dst):
            raise OSError("disk full")

        monkeypatch.setattr(dl.os, "replace", broken_replace)
        line = write(FULL_REGION.replace("Calm", "Quiet"), expect=dl.region_hash(FULL_REGION))
        assert line == "design-language: skipped — OSError: disk full"
        assert Path("DESIGN.md").read_bytes() == before
        assert sorted(os.listdir(in_tmp)) == ["DESIGN.md"], "no temp file survives a refused or failed write"

    def test_main_degrades_on_unreadable_input_and_unwritable_directory(self, write, in_tmp, capsys):
        assert dl.main(["write", "--file", "DESIGN.md", "--region", str(in_tmp / "nowhere.md"), "--expect", "none"]) == 0
        assert capsys.readouterr().out.startswith("design-language: skipped — FileNotFoundError")
        locked = in_tmp / "locked"
        locked.mkdir()
        locked.chmod(0o555)
        try:
            line = write(file="locked/DESIGN.md")
        finally:
            locked.chmod(0o755)
        assert line.startswith("design-language: skipped — PermissionError"), line
        assert list(locked.iterdir()) == []

    def test_write_keeps_the_file_mode(self, write):
        write()
        os.chmod("DESIGN.md", 0o640)
        write(FULL_REGION.replace("Calm", "Quiet"), expect=dl.region_hash(FULL_REGION))
        assert os.stat("DESIGN.md").st_mode & 0o777 == 0o640


SHORT = re.compile(r"[0-9a-f]{7}")
SPECIMEN_TEMPLATE = """<title>{{PROJECT_NAME}} — design language</title>
<!-- design-language-specimen-hash: {{DATA_HASH}} -->
<h1>{{PROJECT_NAME}} — design language</h1>
<p>Generated {{GENERATED_AT}}</p>
<script type="application/json" id="specimen-data">{{SPECIMEN_DATA}}</script>
"""
SPECIMEN = Path("design/specimen.html")
LITERAL_TOKEN = re.compile(r"\{\{[A-Z0-9_]+\}\}")


def embedded(page):
    """The specimen data a rendered page carries, parsed."""
    blocks = re.findall(r'<script type="application/json" id="specimen-data">(.*?)</script>', page, re.S)
    assert len(blocks) == 1, "the page carries exactly one specimen-data block"
    return json.loads(blocks[0])


@pytest.fixture
def specimen_template(tmp_path_factory):
    """A minimal template outside the cwd, as the plugin cache is."""
    return put(tmp_path_factory.mktemp("plugin") / "design-specimen.html", SPECIMEN_TEMPLATE)


@pytest.fixture
def render(specimen_template):
    """cmd_render of DESIGN.md (rewritten to hold `region` when one is given)."""

    def run(region=None, force=False, template=specimen_template, out=SPECIMEN, file="DESIGN.md"):
        if region is not None:
            put("DESIGN.md", doc(region))
        return dl.cmd_render(file, template, out, force=force, now=NOW)

    return run


class TestRender:
    def test_renders_and_creates_design_dir(self, render):
        word, short = outcome(render(FULL_REGION), SHORT)
        assert word == "rendered"
        page = SPECIMEN.read_text()
        digest = dl.data_hash(dl.parse_region(FULL_REGION), SPECIMEN_TEMPLATE.encode())
        assert short == digest[:7]
        assert f"{dl.HASH_MARKER}{digest} -->" in page
        assert not LITERAL_TOKEN.search(page), "no token is left literal"
        assert "<title>Acme Billing — design language</title>" in page
        assert "<p>Generated 2026-11-04 09:30 UTC</p>" in page
        assert embedded(page) == dl.parse_region(FULL_REGION)

    def test_cli_render(self, specimen_template, capsys):
        put("DESIGN.md", doc(FULL_REGION))
        argv = ["render", "--file", "DESIGN.md", "--template", str(specimen_template), "--out", str(SPECIMEN)]
        for extra, word in (([], "rendered"), ([], "unchanged"), (["--force"], "rendered")):
            assert dl.main(argv + extra) == 0
            assert re.fullmatch(rf"design-language: {word} [0-9a-f]{{7}}\n", capsys.readouterr().out)

    def test_unchanged_on_equal_hash(self, render):
        short = outcome(render(FULL_REGION), SHORT)[1]
        before = (SPECIMEN.read_bytes(), SPECIMEN.stat().st_mtime_ns)
        assert outcome(render(), SHORT) == ("unchanged", short)
        assert (SPECIMEN.read_bytes(), SPECIMEN.stat().st_mtime_ns) == before

    def test_rerenders_on_changed_table(self, render):
        short = outcome(render(FULL_REGION), SHORT)[1]
        word, changed = outcome(render(FULL_REGION.replace("#4f46e5", "#1d4ed8")), SHORT)
        assert (word, changed != short) == ("rendered", True)
        assert embedded(SPECIMEN.read_text())["colours"][0]["light"] == "#1d4ed8"

    def test_rerenders_on_changed_template(self, render, specimen_template):
        short = outcome(render(FULL_REGION), SHORT)[1]
        put(specimen_template, SPECIMEN_TEMPLATE + "<p>v2</p>\n")
        word, changed = outcome(render(), SHORT)
        assert (word, changed != short) == ("rendered", True)
        assert "<p>v2</p>" in SPECIMEN.read_text()

    def test_force_rerenders(self, render):
        short = outcome(render(FULL_REGION), SHORT)[1]
        SPECIMEN.write_text(SPECIMEN.read_text() + "hand edit\n")
        assert outcome(render(), SHORT) == ("unchanged", short)
        assert outcome(render(force=True), SHORT) == ("rendered", short)
        assert "hand edit" not in SPECIMEN.read_text()

    def test_hash_excludes_updated_and_specimen_url(self, render):
        data = dl.parse_region(FULL_REGION)
        digest = dl.data_hash(data, b"t")
        assert HEX64.fullmatch(digest)
        assert dl.data_hash({**data, "updated": "later", "specimen_url": None}, b"t") == digest
        assert dl.data_hash({**data, "project": "Other"}, b"t") != digest
        assert dl.data_hash(data, b"t2") != digest
        short = outcome(render(FULL_REGION), SHORT)[1]
        moved = FULL_REGION.replace(UPDATED_ROW, STAMPED_ROW).replace("abc123", "new456")
        assert outcome(render(moved), SHORT) == ("unchanged", short)

    def test_embedded_json_escapes_script_breakers(self, render):
        render(FULL_REGION.replace("Calm,", "Calm </script><script>alert(1)</script> & co,"))
        page = SPECIMEN.read_text()
        assert page.count("</script>") == SPECIMEN_TEMPLATE.count("</script>")
        assert "<script>alert" not in page
        assert "\\u003c/script\\u003e" in page and "\\u0026 co" in page
        assert embedded(page)["theme"]["text"].startswith("Calm </script><script>alert(1)</script> & co,")

    def test_project_name_is_html_escaped(self, render):
        render(FULL_REGION.replace("Acme Billing", 'Acme <b>"Billing"</b> & Co'))
        page = SPECIMEN.read_text()
        assert "<h1>Acme &lt;b&gt;&quot;Billing&quot;&lt;/b&gt; &amp; Co — design language</h1>" in page
        assert "<b>" not in page
        assert embedded(page)["project"] == 'Acme <b>"Billing"</b> & Co'

    def test_data_text_is_never_rescanned_for_tokens(self, render):
        region = FULL_REGION.replace("Acme Billing", "Acme {{SPECIMEN_DATA}}").replace(
            "Calm,", "Calm {{DATA_HASH}} {{PROJECT_NAME}},"
        )
        render(region)
        page = SPECIMEN.read_text()
        assert "<title>Acme {{SPECIMEN_DATA}} — design language</title>" in page
        assert embedded(page)["theme"]["text"].startswith("Calm {{DATA_HASH}} {{PROJECT_NAME}},")

    @pytest.mark.parametrize(
        "template, defect",
        [
            (SPECIMEN_TEMPLATE.replace("<p>Generated {{GENERATED_AT}}</p>\n", ""), "template lacks {{GENERATED_AT}}"),
            (SPECIMEN_TEMPLATE + "<p>{{FOOTER}}</p>\n", "template carries an unknown token {{FOOTER}}"),
            (SPECIMEN_TEMPLATE.replace("design-language-specimen-hash: ", ""), "template lacks the hash marker"),
        ],
        ids=["token-missing", "unknown-token", "marker-missing"],
    )
    def test_drifted_template_is_refused(self, render, specimen_template, template, defect):
        put(specimen_template, template)
        assert render(FULL_REGION) == f"design-language: skipped — {defect}"
        assert not Path("design").exists()

    def test_missing_template_is_refused(self, render, tmp_path_factory):
        absent = tmp_path_factory.mktemp("gone") / "design-specimen.html"
        assert render(FULL_REGION, template=absent) == "design-language: skipped — template not found"
        assert not Path("design").exists()

    def test_missing_region_is_skipped(self, render):
        assert render() == "design-language: skipped — no region to render"
        put("DESIGN.md", "# DESIGN.md\n\nNotes only.\n")
        assert render() == "design-language: skipped — no region to render"
        assert not Path("design").exists()

    def test_schema_violation_is_skipped(self, render):
        line = render(FULL_REGION.replace("| brand |", "| accent |"))
        assert line.startswith("design-language: skipped — schema: Color Palette & Roles: "), line
        assert not Path("design").exists()

    def test_out_outside_cwd_is_refused(self, render, tmp_path_factory):
        out = tmp_path_factory.mktemp("elsewhere") / "specimen.html"
        assert render(FULL_REGION, out=out) == "design-language: skipped — path outside the project"
        assert not out.exists()

    def test_file_outside_cwd_is_refused(self, render, tmp_path_factory):
        outside = put(tmp_path_factory.mktemp("elsewhere") / "DESIGN.md", doc(FULL_REGION))
        assert render(file=outside) == "design-language: skipped — path outside the project"
        assert not Path("design").exists()

    def test_template_outside_cwd_is_accepted(self, render, specimen_template, in_tmp):
        assert not specimen_template.resolve().is_relative_to(in_tmp.resolve())
        assert outcome(render(FULL_REGION), SHORT)[0] == "rendered"


TEMPLATE = REPO / "templates" / "design-specimen.html"
# The panels the specimen draws; their empty states read `empty[<title>]`.
SHOWN_SECTIONS = [
    heading[len("### "):]
    for heading in dl.HEADINGS
    if heading not in ("### Responsive Behavior", "### Iconography & Motion", "### Copy Tone", "### Drift")
]


@pytest.fixture(scope="module")
def template_text():
    return TEMPLATE.read_text()


def executable_scripts(text):
    return re.findall(r"<script>(.*?)</script>", text, re.S)


class TestTemplate:
    def test_default_template_is_the_plugin_template(self):
        assert dl.default_template().resolve() == TEMPLATE.resolve()

    def test_template_carries_exactly_the_four_tokens(self, template_text):
        assert sorted(dl.TOKEN_RE.findall(template_text)) == sorted(
            ["PROJECT_NAME", "PROJECT_NAME", "GENERATED_AT", "DATA_HASH", "DATA_HASH", "SPECIMEN_DATA"]
        ), "PROJECT_NAME sits in <title> and the header; DATA_HASH in the marker and the page root"
        assert "<title>{{PROJECT_NAME}} — design language</title>" in template_text

    def test_hash_marker_comment_carries_the_data_hash_token(self, template_text):
        assert dl.HASH_MARKER + "{{DATA_HASH}} -->" in template_text

    def test_viewport_meta_present(self, template_text):
        assert '<meta name="claude:viewport-fit-sides" content="cover">' in template_text

    def test_is_artifact_page_content(self, template_text):
        for wrapper in ("<!doctype", "<html", "<head", "<body"):
            assert not re.search(rf"{wrapper}\b", template_text, re.I), f"artifact page content carries no {wrapper}>"

    def test_template_is_offline(self, template_text):
        assert not re.search(r"https?://", template_text)
        for request in ("@import", "@font-face", "url(", "fetch(", "XMLHttpRequest", " src="):
            assert request not in template_text, f"the specimen loads nothing: found {request!r}"

    def test_theme_guards(self, template_text):
        assert re.search(r"(?m)^\s*:root \{", template_text)
        assert re.search(
            r'@media \(prefers-color-scheme: dark\) \{\s*:root:not\(\[data-theme="light"\]\) \{', template_text
        )
        assert re.search(r':root\[data-theme="dark"\] \{', template_text)

    def test_no_html_sinks(self, template_text):
        for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "cssText"):
            assert sink not in template_text, f"template uses {sink}"
        script = executable_scripts(template_text)[0]
        assert not re.search(r"""setAttribute\(\s*["']style""", script)
        assert not re.search(r"\.style(?:\.\w+)?\s*=(?!=)", script), "style values go through style.setProperty only"
        assert "style.setProperty" in script

    def test_one_data_block_and_one_executable_script(self, template_text):
        assert re.findall(r"<script\b[^>]*>", template_text) == [
            '<script type="application/json" id="specimen-data">', "<script>",
        ]
        assert '<script type="application/json" id="specimen-data">{{SPECIMEN_DATA}}</script>' in template_text

    def test_empty_states_read_the_section_titles(self, template_text):
        script = executable_scripts(template_text)[0]
        for title in SHOWN_SECTIONS:
            assert f'"{title}"' in script, f"the page never shows the empty state of {title!r}"

    @pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
    def test_template_script_parses(self, template_text, tmp_path):
        js = tmp_path / "specimen.js"
        js.write_text(executable_scripts(template_text)[0])
        result = subprocess.run(["node", "--check", str(js)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr

    def test_real_template_renders_full_region(self):
        put("DESIGN.md", doc(FULL_REGION))
        word, short = outcome(dl.cmd_render("DESIGN.md", None, SPECIMEN, now=NOW), SHORT)
        assert word == "rendered"
        page = SPECIMEN.read_text()
        digest = dl.data_hash(dl.parse_region(FULL_REGION), TEMPLATE.read_bytes())
        assert short == digest[:7]
        assert f"{dl.HASH_MARKER}{digest} -->" in page
        assert not LITERAL_TOKEN.search(page)
        assert "<title>Acme Billing — design language</title>" in page
        assert embedded(page) == dl.parse_region(FULL_REGION)


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
