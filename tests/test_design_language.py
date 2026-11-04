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
