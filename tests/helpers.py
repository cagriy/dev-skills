"""Shared helpers for the dev-skills test suite."""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILLS = REPO / "skills"
TEMPLATES = REPO / "templates"
FEATURE_SKILLS = ("feature-storm", "feature-design", "feature-plan", "feature-implement")

STORM_SKILL = SKILLS / "feature-storm" / "SKILL.md"
E2E_SKILL = SKILLS / "evals-e2e-run" / "SKILL.md"


def fenced_blocks(text: str) -> list[str]:
    """All fenced code blocks in a markdown document, fence markers stripped."""
    return re.findall(r"^```[a-z]*\n(.*?)^```", text, re.DOTALL | re.MULTILINE)


def storm_template_sections() -> dict[int, str]:
    """The `## N. Title` headings of feature-storm's Step 5 document template."""
    for block in fenced_blocks(STORM_SKILL.read_text()):
        headings = re.findall(r"^## (\d+)\. (.+?)\s*$", block, re.MULTILINE)
        if headings:
            return {int(n): title for n, title in headings}
    raise AssertionError("no fenced template block with '## N.' headings in feature-storm/SKILL.md")


def storm_quality_rubric() -> str:
    """The storm_quality rubric block from evals-e2e-run (up to the design_quality rubric)."""
    m = re.search(
        r"\*\*storm_quality\*\*.*?(?=\n\n\*\*design_quality\*\*)",
        E2E_SKILL.read_text(),
        re.DOTALL,
    )
    if not m:
        raise AssertionError("storm_quality rubric not found in evals-e2e-run/SKILL.md")
    return m.group(0)


def cited_sections(rubric: str) -> set[int]:
    """Storm-document section numbers (§N) the rubric cites."""
    return {int(n) for n in re.findall(r"§(\d+)", rubric)}
