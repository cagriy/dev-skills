"""Unit tests for scripts/mockup_feedback.py — the mockup feedback-bar injector.

Runs the injector against synthetic mockup pages under tmp_path, using the real
templates/mockup-feedback.html, so a template change that breaks the injection
contract fails here rather than in a user's feature folder.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from helpers import REPO, SKILLS

from scripts import mockup_feedback as mf

TEMPLATE = REPO / "templates" / "mockup-feedback.html"
MOCKUP_SKILL = SKILLS / "feature-mockup" / "SKILL.md"

COMPARE_PAGE = """<title>Reminder placement</title>
<style>body { background: #fff; color: #111; }</style>
<div class="banner">Mockup — not shipping code</div>
<section id="inline-panel" data-mf-option="inline-panel">Inline panel</section>
<section id="sidebar-drawer" data-mf-option="sidebar-drawer">Sidebar drawer</section>
"""

PICK_PAGE = """<title>Sidebar drawer</title>
<style>body { background: #fff; color: #111; }</style>
<main id="sidebar-drawer" data-mf-option="sidebar-drawer">Sidebar drawer</main>
"""

REVIEW_PAGE = """<title>Reminders overview</title>
<main id="overview" data-mf-option="overview">Overview</main>
"""


def write(tmp_path, name, text):
    page = tmp_path / name
    page.write_text(text)
    return page


def config_of(text):
    """The JSON config the injected block carries."""
    match = re.search(
        r'<script type="application/json" id="mf-config">(.*?)</script>', text, re.DOTALL
    )
    assert match, "injected block carries no mf-config script"
    return json.loads(match.group(1))


def run(page, **kwargs):
    kwargs.setdefault("template", TEMPLATE)
    return mf.run(page, **kwargs)


COMPARE = dict(
    set_id="v3-s1",
    set_label="Reminder placement",
    mode="compare",
    options=["inline-panel=Inline panel", "sidebar-drawer=Sidebar drawer"],
)
PICK = dict(
    set_id="v3-s2",
    set_label="Reminder placement",
    mode="pick",
    options=["inline-panel=Inline panel", "sidebar-drawer=Sidebar drawer", "stacked-cards=Stacked cards"],
    this="sidebar-drawer",
)
REVIEW = dict(set_id="v3-s1", set_label="Reminders", mode="review", options=["overview=Reminders overview"])


class TestInject:
    def test_appends_one_block_and_reports(self, tmp_path):
        page = write(tmp_path, "mockup-v3-placement.html", COMPARE_PAGE)
        line = run(page, **COMPARE)
        assert line == "mockup-feedback: mockup-v3-placement.html — compare, 2 options, open"
        text = page.read_text()
        assert text.startswith(COMPARE_PAGE.rstrip("\n")), "the mockup itself is untouched"
        assert text.count(mf.START) == 1 and text.count(mf.END) == 1
        assert text.index(mf.START) > text.index("Sidebar drawer</section>"), "block sits after the mockup"

    def test_config_carries_the_set(self, tmp_path):
        page = write(tmp_path, "p.html", COMPARE_PAGE)
        run(page, **COMPARE)
        config = config_of(page.read_text())
        assert config == {
            "set": "v3-s1",
            "setLabel": "Reminder placement",
            "mode": "compare",
            "options": [
                {"id": "inline-panel", "label": "Inline panel"},
                {"id": "sidebar-drawer", "label": "Sidebar drawer"},
            ],
            "this": None,
            "status": "open",
            "chosen": None,
        }

    def test_pick_page_names_itself_among_its_siblings(self, tmp_path):
        page = write(tmp_path, "p.html", PICK_PAGE)
        line = run(page, **PICK)
        assert line.endswith("pick, 3 options, open")
        config = config_of(page.read_text())
        assert config["this"] == "sidebar-drawer"
        assert [o["id"] for o in config["options"]] == ["inline-panel", "sidebar-drawer", "stacked-cards"]

    def test_reinjection_replaces_the_block_idempotently(self, tmp_path):
        page = write(tmp_path, "p.html", COMPARE_PAGE)
        run(page, **COMPARE)
        first = page.read_text()
        run(page, **COMPARE)
        assert page.read_text() == first

    def test_status_update_rewrites_only_the_config(self, tmp_path):
        page = write(tmp_path, "p.html", COMPARE_PAGE)
        run(page, **COMPARE)
        line = run(page, **COMPARE, status="accepted", chosen="sidebar-drawer")
        assert line.endswith("compare, 2 options, accepted")
        text = page.read_text()
        assert text.count(mf.START) == 1
        config = config_of(text)
        assert config["status"] == "accepted" and config["chosen"] == "sidebar-drawer"

    def test_labels_cannot_break_out_of_the_script(self, tmp_path):
        page = write(tmp_path, "p.html", REVIEW_PAGE)
        run(page, **{**REVIEW, "set_label": "A </script><b>x</b> & co"})
        text = page.read_text()
        block = text[text.index(mf.START):]
        assert "</script><b>" not in block
        assert config_of(text)["setLabel"] == "A </script><b>x</b> & co"

    def test_never_touches_other_files(self, tmp_path):
        page = write(tmp_path, "p.html", REVIEW_PAGE)
        other = write(tmp_path, "other.html", "keep")
        run(page, **REVIEW)
        assert other.read_text() == "keep"
        assert sorted(p.name for p in tmp_path.iterdir()) == ["other.html", "p.html"]


class TestValidate:
    @pytest.mark.parametrize(
        "overrides, reason",
        [
            ({"mode": "carousel"}, "unknown mode"),
            ({"set_id": "V3 S1"}, "set id"),
            ({"set_label": "  "}, "set label"),
            ({"options": ["inline-panel=Inline panel"]}, "compare needs 2–4 options"),
            ({"options": ["a=A", "b=B", "c=C", "d=D", "e=E"]}, "compare needs 2–4 options"),
            ({"options": ["Inline Panel=Inline panel", "b=B"]}, "option id"),
            ({"options": ["inline-panel", "b=B"]}, "id=label"),
            ({"options": ["inline-panel=Inline panel", "inline-panel=Again"]}, "duplicate option"),
            ({"status": "maybe"}, "unknown status"),
            ({"status": "accepted"}, "accepted needs --chosen"),
            ({"status": "accepted", "chosen": "nope"}, "accepted needs --chosen"),
        ],
    )
    def test_compare_rejections(self, tmp_path, overrides, reason):
        page = write(tmp_path, "p.html", COMPARE_PAGE)
        line = run(page, **{**COMPARE, **overrides})
        assert line.startswith("mockup-feedback: skipped — "), line
        assert reason in line, line
        assert mf.START not in page.read_text(), "a rejected run writes nothing"

    def test_review_takes_exactly_one_option(self, tmp_path):
        page = write(tmp_path, "p.html", REVIEW_PAGE)
        line = run(page, **{**REVIEW, "options": ["overview=Overview", "b=B"]})
        assert "review needs exactly 1 option" in line

    def test_pick_needs_this(self, tmp_path):
        page = write(tmp_path, "p.html", PICK_PAGE)
        assert "pick needs --this" in run(page, **{**PICK, "this": None})
        assert "pick needs --this" in run(page, **{**PICK, "this": "nope"})

    def test_this_belongs_to_pick_only(self, tmp_path):
        page = write(tmp_path, "p.html", COMPARE_PAGE)
        assert "--this is for pick" in run(page, **COMPARE, this="inline-panel")

    def test_every_option_needs_one_marked_root(self, tmp_path):
        page = write(tmp_path, "p.html", COMPARE_PAGE.replace(' data-mf-option="sidebar-drawer"', ""))
        line = run(page, **COMPARE)
        assert 'no element marked data-mf-option="sidebar-drawer"' in line

    def test_a_pick_page_marks_only_its_own_option(self, tmp_path):
        page = write(tmp_path, "p.html", PICK_PAGE)
        assert run(page, **PICK).endswith("open"), "siblings live on other pages"

    def test_duplicate_marked_roots_are_ambiguous(self, tmp_path):
        page = write(tmp_path, "p.html", REVIEW_PAGE + '<div data-mf-option="overview"></div>\n')
        assert 'more than one element marked data-mf-option="overview"' in run(page, **REVIEW)

    def test_broken_block_is_refused(self, tmp_path):
        page = write(tmp_path, "p.html", REVIEW_PAGE + mf.START + "\n<p>half</p>\n")
        assert "broken mockup-feedback block" in run(page, **REVIEW)


class TestSkips:
    def test_missing_page(self, tmp_path):
        assert run(tmp_path / "nowhere.html", **REVIEW) == "mockup-feedback: skipped — page not found"

    def test_missing_template(self, tmp_path):
        page = write(tmp_path, "p.html", REVIEW_PAGE)
        line = run(page, **{**REVIEW, "template": tmp_path / "nowhere.html"})
        assert line == "mockup-feedback: skipped — template not found"

    def test_main_never_raises(self, tmp_path, capsys):
        page = write(tmp_path, "p.html", COMPARE_PAGE)
        assert mf.main(["--bogus"]) == 0
        assert capsys.readouterr().out.strip() == "mockup-feedback: skipped — bad arguments"
        code = mf.main([
            "--page", str(page), "--set", "v3-s1", "--set-label", "Reminder placement",
            "--mode", "compare", "--option", "inline-panel=Inline panel",
            "--option", "sidebar-drawer=Sidebar drawer",
        ])
        assert code == 0
        assert capsys.readouterr().out.strip().endswith("compare, 2 options, open")


class TestContract:
    def test_default_template_is_the_plugin_template(self):
        assert Path(mf.default_template()).resolve() == TEMPLATE.resolve()

    def test_stdlib_only(self):
        source = (REPO / "scripts" / "mockup_feedback.py").read_text()
        imports = re.findall(r"^(?:from|import)\s+([a-zA-Z_][\w.]*)", source, re.MULTILINE)
        third_party = [m for m in imports if m.split(".")[0] not in mf.STDLIB_MODULES]
        assert not third_party, f"mockup_feedback.py imports {third_party}"

    def test_template_carries_one_block_and_one_config_token(self):
        text = TEMPLATE.read_text()
        assert text.count(mf.START) == 1 and text.count(mf.END) == 1
        block = text[text.index(mf.START):text.index(mf.END)]
        assert block.count(mf.CONFIG_TOKEN) == 1

    def test_template_is_offline(self):
        # Mockups must render from disk and on the artifact host, which blocks
        # every external request; the bar may not be the first thing to break that.
        assert not re.search(r"https?://", TEMPLATE.read_text())

    def test_template_uses_the_comments_capability(self):
        text = TEMPLATE.read_text()
        for call in ('use("comments")', "canSendToClaude", "sendToClaude", "anchorFor", "openComposer"):
            assert call in text, f"template never calls {call}"
        assert "data-uncommentable" in text, "the bar itself must not collect comment pins"

    def test_grammar_is_shared_by_template_script_and_skill(self):
        # The page writes the decision line; the skill parses it. Both sides
        # must spell the prefix and every action word the same way.
        template = TEMPLATE.read_text()
        skill = MOCKUP_SKILL.read_text()
        assert mf.GRAMMAR_PREFIX in template and mf.GRAMMAR_PREFIX in skill
        for action in mf.ACTIONS:
            assert f'"{action}"' in template, f"template never sends {action!r}"
            assert f"`{action}" in skill, f"feature-mockup never documents {action!r}"

    @pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
    def test_template_script_parses(self, tmp_path):
        text = TEMPLATE.read_text()
        scripts = re.findall(r"<script>(.*?)</script>", text, re.DOTALL)
        assert len(scripts) == 1, "template carries exactly one executable script"
        js = tmp_path / "bar.js"
        js.write_text(scripts[0])
        result = subprocess.run(["node", "--check", str(js)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
