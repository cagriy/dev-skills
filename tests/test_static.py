"""Layer 1: deterministic consistency checks over the skill markdown files.

These encode the cross-file invariants that CLAUDE.md otherwise enforces only
by convention: the storm_quality rubric must judge sections the storm template
actually mandates, section renumberings must not leave stale references, the
plugin-wide mirrored blocks must stay identical, and tracker tokens / eval-type
literals must stay consistent with their consumers.
"""

import re

from helpers import (
    DESIGN_SKILL,
    E2E_SKILL,
    FEATURE_SKILLS,
    REPO,
    SKILLS,
    TEMPLATES,
    cited_sections,
    design_quality_rubric,
    design_template_sections,
    plan_quality_rubric,
    plan_template_sections,
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

EXPECTED_PLAN_SECTIONS = [
    "Overview",
    "Development strategy — Test-Driven Development",
    "Requirements coverage map",
    "Stages",
    "Cross-cutting concerns",
    "Verification",
    "Risks and open issues",
    "Planning decisions taken",
    "Deviations from the design",
]

# Per-stage fields of the plan template's Stage blocks that the rubric must judge.
PLAN_STAGE_FIELDS = ("Design references", "Touches", "Steps (TDD)", "Definition of done")

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

# The Step 5g self-review lens set of feature-implement, in order; mirrored
# (in shorthand) in the subagent contract's Discipline bullet, the Constraints
# section, the frontmatter description, and README.md.
EXPECTED_SELF_REVIEW_LENSES = [
    "Bloat",
    "Duplication / reuse",
    "Supersession / orphans",
    "Functional issues",
    "Inefficiencies",
    "Security issues",
    "Style/comments",
]

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


class TestPlanRubricTemplateAlignment:
    """plan_quality must judge the document feature-plan mandates.

    The plan template's sections are named, not numbered, so alignment is
    checked by verbatim title containment rather than §-number citation; the
    reverse check (rubric cites no nonexistent section) has no name-based
    analogue and is covered by review instead.
    """

    def test_template_has_expected_nine_sections(self):
        assert plan_template_sections() == EXPECTED_PLAN_SECTIONS

    def test_rubric_names_every_section(self):
        rubric = plan_quality_rubric()
        missing = [title for title in EXPECTED_PLAN_SECTIONS if title not in rubric]
        assert not missing, f"plan_quality rubric never names: {missing}"

    def test_rubric_names_the_per_stage_fields(self):
        rubric = plan_quality_rubric()
        missing = [field for field in PLAN_STAGE_FIELDS if field not in rubric]
        assert not missing, f"plan_quality rubric never names stage fields: {missing}"


class TestSelfReviewLensAlignment:
    """feature-implement's 5g lens set, and its shorthand mirrors, must agree.

    The lens list appears in full in Step 5g and in shorthand in the subagent
    contract's Discipline bullet, the Constraints section, the frontmatter
    description, and README.md — a lens added or removed in one place but not
    the others is exactly the drift these checks catch.
    """

    IMPLEMENT_SKILL = SKILLS / "feature-implement" / "SKILL.md"

    def test_5g_has_expected_lenses(self):
        text = self.IMPLEMENT_SKILL.read_text()
        assert "### 5g." in text and "### 5h." in text, "5g/5h headings missing"
        section = text.split("### 5g.")[1].split("### 5h.")[0]
        lenses = re.findall(r"^- \*\*(.+?)\*\* —", section, re.MULTILINE)
        assert lenses == EXPECTED_SELF_REVIEW_LENSES

    def test_mirror_sites_name_duplication(self):
        text = self.IMPLEMENT_SKILL.read_text()
        lines = text.splitlines()

        discipline = next(
            (l for l in lines if l.startswith("- **Discipline**")), None
        )
        assert discipline, "subagent-contract Discipline bullet not found"
        assert "duplication" in discipline.lower(), (
            "Discipline bullet's lens shorthand omits duplication"
        )

        constraint = next(
            (l for l in lines if "Self-review every stage before commit" in l), None
        )
        assert constraint, "self-review constraint bullet not found"
        assert "duplicat" in constraint.lower(), (
            "Constraints self-review bullet omits duplication"
        )

        description = next(
            (l for l in lines if l.startswith("description:")), None
        )
        assert description, "frontmatter description not found"
        assert "duplication" in description.lower(), (
            "frontmatter description's lens list omits duplication"
        )

        # The README no longer enumerates the lens list — the per-skill docs
        # moved to the GitHub wiki (a separate repo this suite can't read).
        # The wiki's Skills-Reference page mirrors these lenses; keep it
        # aligned manually when the lens list changes.


class TestFeatureListContract:
    """feature-list reports on the chain without being part of it.

    It reads two producer-owned artefacts — the stage `.md` filenames minted by
    feature-resolve and the tracker's per-stage `data-stage`/`data-state`
    attributes flipped by the four feature-* skills — so a rename on either side
    silently breaks the report. It is also strictly read-only: it must never
    acquire a write tool or call feature-resolve (which creates folders and
    seeds trackers) — the same reason evals-e2e-run globs by hand.
    """

    LIST_SKILL = SKILLS / "feature-list" / "SKILL.md"
    STAGE_SLUGS = ("storm", "design", "plan", "implement")

    def frontmatter(self):
        m = re.match(r"---\n(.*?)\n---\n", self.LIST_SKILL.read_text(), re.DOTALL)
        assert m, "feature-list: missing frontmatter"
        return m.group(1)

    def allowed_tools(self):
        line = next(
            (
                l
                for l in self.frontmatter().splitlines()
                if l.startswith("allowed-tools:")
            ),
            None,
        )
        assert line, "feature-list: no allowed-tools in frontmatter"
        return line

    def test_is_user_invocable_and_documents_the_all_argument(self):
        frontmatter = self.frontmatter()
        assert re.search(r"^user-invocable:\s*true\s*$", frontmatter, re.MULTILINE)
        hint = re.search(r"^argument-hint:\s*(.+)$", frontmatter, re.MULTILINE)
        assert hint, "feature-list: no argument-hint"
        assert "all" in hint.group(1), "argument-hint never mentions the `all` argument"

    def test_is_read_only(self):
        allowed = self.allowed_tools()
        for tool in ("Write", "Edit", "NotebookEdit", "Skill", "Agent"):
            assert not re.search(rf"\b{tool}\b", allowed), (
                f"feature-list must stay read-only: {tool} in allowed-tools"
            )

    def test_does_not_delegate_to_feature_resolve_or_lessons_capture(self):
        text = self.LIST_SKILL.read_text()
        for line in text.splitlines():
            if line.lstrip().startswith(("- **Never", "- **Read-only", ">")):
                continue
            assert "Skill` tool" not in line, (
                "feature-list must not invoke other skills"
            )

    def test_stage_slugs_match_the_tracker_template(self):
        text = self.LIST_SKILL.read_text()
        template_text = (TEMPLATES / "feature-tracker.html").read_text()
        for slug in self.STAGE_SLUGS:
            assert f'data-stage="{slug}"' in template_text, (
                f"tracker template lost data-stage={slug!r}"
            )
            assert f'data-stage="{slug}"' in text, (
                f"feature-list never reads data-stage={slug!r}"
            )
        assert 'data-state="complete"' in text, (
            "feature-list never reads the tracker's complete state"
        )

    def test_stage_file_naming_matches_feature_resolve(self):
        pattern = "feature-<stage>-v<N>-<description>.md"
        resolver = (SKILLS / "feature-resolve" / "SKILL.md").read_text()
        assert pattern in resolver, "feature-resolve no longer states the stage-file pattern"
        assert pattern in self.LIST_SKILL.read_text(), (
            "feature-list must derive stage files from the same documented pattern"
        )


class TestFeatureMockupContract:
    """feature-mockup is an inline, model-only helper of feature-design.

    Its result block is a machine-read contract: feature-design parses the keys
    and folds them into the design document, so a key renamed on one side
    silently drops UI decisions. It is also deliberately *not* a chain skill —
    it takes its pathing as input rather than calling feature-resolve (which
    would allocate folders), and its reflection belongs to feature-design's own
    lessons step, so it holds no `Skill` tool at all.
    """

    MOCKUP_SKILL = SKILLS / "feature-mockup" / "SKILL.md"
    RESULT_KEYS = (
        "status",
        "kind",
        "mockup_dir",
        "chosen_mockup",
        "alternatives",
        "design_language",
        "decisions",
        "open_ui_questions",
        "notes",
    )
    # Keys feature-design must consume when it folds the mockup into the design.
    CONSUMED_KEYS = ("status", "chosen_mockup", "alternatives", "decisions",
                     "open_ui_questions")
    INPUT_SLOTS = ("feature_folder=", "version=", "feature=", "references=")
    # The named skip conditions of feature-design's fire/skip rule. A mockup is
    # not free — it costs the user a round of attention — so the decision must
    # be a rule with named exits, not one prose sentence a run can reinterpret.
    SKIP_CONDITIONS = (
        "No user-visible surface",
        "Appearance already settled",
        "Mechanical delta",
        "User declined",
    )

    def frontmatter(self):
        m = re.match(r"---\n(.*?)\n---\n", self.MOCKUP_SKILL.read_text(), re.DOTALL)
        assert m, "feature-mockup: missing frontmatter"
        return m.group(1)

    def test_is_model_only(self):
        frontmatter = self.frontmatter()
        assert re.search(r"^user-invocable:\s*false\s*$", frontmatter, re.MULTILINE), (
            "feature-mockup must not be user-invocable — it is a helper of feature-design"
        )
        assert not re.search(
            r"^disable-model-invocation:\s*true\s*$", frontmatter, re.MULTILINE
        ), "feature-mockup must stay model-invocable"

    def test_cannot_invoke_other_skills(self):
        allowed = next(
            (
                l
                for l in self.frontmatter().splitlines()
                if l.startswith("allowed-tools:")
            ),
            None,
        )
        assert allowed, "feature-mockup: no allowed-tools in frontmatter"
        for tool in ("Skill", "Agent"):
            assert not re.search(rf"\b{tool}\b", allowed), (
                f"feature-mockup must not delegate to other skills: {tool} in allowed-tools"
            )

    def test_result_block_declares_every_key(self):
        text = self.MOCKUP_SKILL.read_text()
        assert "feature-mockup result" in text, "result block header missing"
        for key in self.RESULT_KEYS:
            assert f"{key}: <" in text, f"result block never declares {key!r}"

    def test_writes_only_under_the_feature_folder(self):
        text = self.MOCKUP_SKILL.read_text()
        assert "<feature_folder>/mockups/" in text, (
            "feature-mockup must document its output directory as <feature_folder>/mockups/"
        )
        assert "feature-resolve" in text, (
            "feature-mockup must state that it never calls feature-resolve"
        )

    def test_does_not_end_its_turn_on_success(self):
        # Same inline-helper invariant feature-resolve and lessons-capture carry:
        # the Skill tool loads this into the caller's own turn.
        assert "do not end your turn" in self.MOCKUP_SKILL.read_text().lower(), (
            "feature-mockup: missing the inline do-not-end-your-turn guard"
        )

    def test_feature_design_invokes_it_with_the_documented_slots(self):
        design = DESIGN_SKILL.read_text()
        assert "feature-mockup" in design, "feature-design never invokes feature-mockup"
        for slot in self.INPUT_SLOTS:
            assert slot in design, f"feature-design never passes {slot!r}"
            assert slot in self.MOCKUP_SKILL.read_text(), (
                f"feature-mockup never documents the {slot!r} input slot"
            )

    def test_feature_design_consumes_the_result_keys(self):
        design = DESIGN_SKILL.read_text()
        for key in self.CONSUMED_KEYS:
            assert f"`{key}`" in design, (
                f"feature-design never reads the result block's {key!r}"
            )

    def test_feature_design_names_every_skip_condition(self):
        design = DESIGN_SKILL.read_text()
        for condition in self.SKIP_CONDITIONS:
            assert condition in design, (
                f"feature-design's fire/skip rule never names {condition!r}"
            )

    def test_supplied_references_outrank_the_grounded_digest(self):
        # A user-supplied screenshot / design link / exact spec is the strongest
        # evidence of what they want; the mockup must not quietly override it.
        text = self.MOCKUP_SKILL.read_text()
        assert "references=" in text, "feature-mockup: references= slot undocumented"
        assert re.search(r"references.{0,200}(precedence|outrank)", text, re.S | re.I), (
            "feature-mockup never states that supplied references take precedence"
        )


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
