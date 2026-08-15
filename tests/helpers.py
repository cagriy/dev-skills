"""Shared helpers for the dev-skills test suite."""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILLS = REPO / "skills"
TEMPLATES = REPO / "templates"
FEATURE_SKILLS = ("feature-storm", "feature-design", "feature-plan", "feature-implement")

STORM_SKILL = SKILLS / "feature-storm" / "SKILL.md"
DESIGN_SKILL = SKILLS / "feature-design" / "SKILL.md"
PLAN_SKILL = SKILLS / "feature-plan" / "SKILL.md"
E2E_SKILL = SKILLS / "evals-e2e-run" / "SKILL.md"

# The two diagram skills and the templates they render from. They are siblings
# in style but not in scope: diagram-update refuses outside this repo, while
# diagram-c4-update runs in any repo — see TestC4DiagramContract.
C4_SKILL = SKILLS / "diagram-c4-update" / "SKILL.md"
C4_TEMPLATE = TEMPLATES / "c4-diagram.html"
WORKFLOW_SKILL = SKILLS / "diagram-update" / "SKILL.md"
WORKFLOW_TEMPLATE = TEMPLATES / "workflow-diagram.html"

# Model-only labelling helper. Its contract is a mix of herdr CLI facts (name
# charset, --clear) and plugin invariants (silent skip, writes nothing).
LABEL_SKILL = SKILLS / "set-herdr-label" / "SKILL.md"


def fenced_blocks(text: str) -> list[str]:
    """All fenced code blocks in a markdown document, fence markers stripped."""
    return re.findall(r"^```[a-z]*\n(.*?)^```", text, re.DOTALL | re.MULTILINE)


def template_sections(skill_file: Path) -> dict[int, str]:
    """The `## N. Title` headings of a skill's fenced document template.

    Returns the first fenced block that contains numbered headings — for both
    feature-storm and feature-design that is the Step 5 document template.
    """
    for block in fenced_blocks(skill_file.read_text()):
        headings = re.findall(r"^## (\d+)\. (.+?)\s*$", block, re.MULTILINE)
        if headings:
            return {int(n): title for n, title in headings}
    raise AssertionError(
        f"no fenced template block with '## N.' headings in {skill_file}"
    )


def storm_template_sections() -> dict[int, str]:
    return template_sections(STORM_SKILL)


def design_template_sections() -> dict[int, str]:
    return template_sections(DESIGN_SKILL)


def plan_template_sections() -> list[str]:
    """The named `## Title` headings of feature-plan's Step 5 document template.

    The plan template's sections are named, not numbered, so this returns the
    ordered heading titles (h2 only — `### Stage N` sub-headings are excluded).
    """
    for block in fenced_blocks(PLAN_SKILL.read_text()):
        headings = re.findall(r"^## ([^#\n].*?)\s*$", block, re.MULTILINE)
        if headings:
            return headings
    raise AssertionError(
        f"no fenced template block with '## ' headings in {PLAN_SKILL}"
    )


def quality_rubric(name: str) -> str:
    """A quality rubric block from evals-e2e-run (up to the next bold or # heading)."""
    m = re.search(
        rf"\*\*{name}\*\*.*?(?=\n\n(?:\*\*|#))",
        E2E_SKILL.read_text(),
        re.DOTALL,
    )
    if not m:
        raise AssertionError(f"{name} rubric not found in evals-e2e-run/SKILL.md")
    return m.group(0)


def storm_quality_rubric() -> str:
    return quality_rubric("storm_quality")


def design_quality_rubric() -> str:
    return quality_rubric("design_quality")


def plan_quality_rubric() -> str:
    return quality_rubric("plan_quality")


def cited_sections(rubric: str) -> set[int]:
    """Artefact-document section numbers (§N) the rubric cites."""
    return {int(n) for n in re.findall(r"§(\d+)", rubric)}
