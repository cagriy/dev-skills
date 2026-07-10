"""Layer 1: deterministic consistency checks over the skill markdown files.

These encode the cross-file invariants that CLAUDE.md otherwise enforces only
by convention: the storm_quality rubric must judge sections the storm template
actually mandates, section renumberings must not leave stale references, the
plugin-wide mirrored blocks must stay identical, and tracker tokens / eval-type
literals must stay consistent with their consumers.
"""

import re

from helpers import (
    E2E_SKILL,
    FEATURE_SKILLS,
    REPO,
    SKILLS,
    TEMPLATES,
    cited_sections,
    design_quality_rubric,
    design_template_sections,
    storm_quality_rubric,
    storm_template_sections,
)

EXPECTED_STORM_SECTIONS = {
    1: "Summary",
    2: "Goals",
    3: "Scope (in / out)",
    4: "High-level technical direction",
    5: "Alternatives considered",
    6: "Risks",
    7: "Open questions for design",
}

EXPECTED_DESIGN_SECTIONS = {
    1: "Summary",
    2: "Goals and non-goals",
    3: "Requirements",
    4: "Background and context",
    5: "Design",
    6: "Alternatives considered",
    7: "Risks and issues",
    8: "Open questions",
    9: "Rollout plan",
}

EVAL_TYPES = {
    "storm_quality",
    "design_consistency",
    "design_quality",
    "plan_consistency",
    "plan_quality",
    "code_storm_consistency",
    "code_design_consistency",
    "code_plan_consistency",
}

# Phrases that can only be left-overs of the pre-7-section storm numbering.
STALE_STORM_REFERENCES = (
    "5-section",
    "questions §5",
    "§5 (Open questions",
    "§5 Open questions",
    "lifted from §5",
)

# `{{TOKEN}}` appears in prose as a meta-placeholder, not a real template token.
GENERIC_TOKEN_NAMES = {"TOKEN"}


def all_skill_files():
    return sorted(SKILLS.glob("*/SKILL.md"))


class TestStormRubricTemplateAlignment:
    """The regression guard: storm_quality must judge the document feature-storm mandates."""

    def test_template_has_expected_seven_sections(self):
        assert storm_template_sections() == EXPECTED_STORM_SECTIONS

    def test_rubric_cites_only_existing_sections(self):
        cited = cited_sections(storm_quality_rubric())
        assert cited, "storm_quality rubric cites no template sections"
        assert cited <= set(storm_template_sections()), (
            "rubric cites sections missing from the storm template"
        )

    def test_rubric_covers_every_section(self):
        assert cited_sections(storm_quality_rubric()) == set(EXPECTED_STORM_SECTIONS)


class TestDesignRubricTemplateAlignment:
    """design_quality must judge the document feature-design mandates."""

    def test_template_has_expected_nine_sections(self):
        assert design_template_sections() == EXPECTED_DESIGN_SECTIONS

    def test_rubric_cites_only_existing_sections(self):
        cited = cited_sections(design_quality_rubric())
        assert cited, "design_quality rubric cites no template sections"
        assert cited <= set(design_template_sections()), (
            "rubric cites sections missing from the design template"
        )

    def test_rubric_covers_every_section(self):
        assert cited_sections(design_quality_rubric()) == set(EXPECTED_DESIGN_SECTIONS)


def test_no_stale_storm_section_references():
    files = all_skill_files() + [REPO / "CLAUDE.md"]
    offenders = [
        f"{path.relative_to(REPO)}: {pattern!r}"
        for path in files
        for pattern in STALE_STORM_REFERENCES
        if pattern in path.read_text()
    ]
    assert not offenders, "stale pre-renumbering storm references:\n" + "\n".join(offenders)


def test_frontmatter_contract():
    # Lenient line-based parsing rather than strict YAML: some description
    # fields legitimately contain ": " mid-line, which the plugin loader
    # accepts but a strict YAML parser would reject.
    for skill_file in all_skill_files():
        text = skill_file.read_text()
        m = re.match(r"---\n(.*?)\n---\n", text, re.DOTALL)
        assert m, f"{skill_file}: missing frontmatter"
        frontmatter = m.group(1)
        # name is optional (the loader derives it from the directory), but
        # when present it must match the directory name.
        name = re.search(r"^name:\s*(\S+)\s*$", frontmatter, re.MULTILINE)
        if name:
            assert name.group(1) == skill_file.parent.name, (
                f"{skill_file}: frontmatter name {name.group(1)!r} != directory name"
            )
        assert re.search(r"^description:\s*\S", frontmatter, re.MULTILINE), (
            f"{skill_file}: frontmatter has no description"
        )


def test_terminology_block_mirrored():
    blocks = {}
    for slug in FEATURE_SKILLS:
        text = (SKILLS / slug / "SKILL.md").read_text()
        m = re.search(r"^\*\*Terminology \(plugin-wide\)\.\*\*.*$", text, re.MULTILINE)
        assert m, f"{slug}: terminology block missing"
        blocks[slug] = m.group(0)
    assert len(set(blocks.values())) == 1, (
        "the plugin-wide terminology block has drifted between feature-* skills"
    )


def test_skill_tokens_exist_in_templates():
    template_text = "".join(p.read_text() for p in sorted(TEMPLATES.glob("*.html")))
    for skill_file in all_skill_files():
        tokens = set(re.findall(r"\{\{([A-Z][A-Z0-9_]*)\}\}", skill_file.read_text()))
        for token in sorted(tokens - GENERIC_TOKEN_NAMES):
            assert f"{{{{{token}}}}}" in template_text, (
                f"{skill_file.parent.name}: {{{{{token}}}}} not found in any template"
            )


def test_eval_type_literals_consistent():
    text = E2E_SKILL.read_text()

    table = set(re.findall(r"^\s*\| `(\w+)` \|", text, re.MULTILINE))
    assert table == EVAL_TYPES, "Step 1 selection table disagrees with the canonical set"

    contract = re.search(r"eval_type: <([a-z_|]+)>", text)
    assert contract, "output contract eval_type line not found"
    assert set(contract.group(1).split("|")) == EVAL_TYPES, (
        "output contract disagrees with the canonical set"
    )

    step4_line = next(
        (line for line in text.splitlines() if "literal strings" in line), None
    )
    assert step4_line, "Step 4 literal-strings sentence not found"
    assert set(re.findall(r"`(\w+)`", step4_line)) >= EVAL_TYPES, (
        "Step 4 literal-strings list disagrees with the canonical set"
    )
