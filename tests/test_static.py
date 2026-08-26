"""Layer 1: deterministic consistency checks over the skill markdown files.

These encode the cross-file invariants that CLAUDE.md otherwise enforces only
by convention: the storm_quality rubric must judge sections the storm template
actually mandates, section renumberings must not leave stale references, the
plugin-wide mirrored blocks must stay identical, and tracker tokens / eval-type
literals must stay consistent with their consumers.
"""

import re

from helpers import (
    BUG_TRACKER_SKILL,
    C4_SKILL,
    C4_TEMPLATE,
    DESIGN_SKILL,
    E2E_SKILL,
    FEATURE_SKILLS,
    LABEL_SKILL,
    REPO,
    SKILLS,
    TEMPLATES,
    TRACKER_TEMPLATE,
    USAGE_SCRIPT,
    USAGE_SKILL,
    WORKFLOW_SKILL,
    WORKFLOW_TEMPLATE,
    cited_sections,
    design_quality_rubric,
    design_template_sections,
    plan_quality_rubric,
    plan_template_sections,
    skill_text,
    step_span,
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

# The eight usage tokens, keyed by the tracker panel each pair must sit in
# (the `id="panel-<key>"` sections of templates/feature-tracker.html). Chip
# first, table second — the order render_tracker_html returns them in.
USAGE_TOKENS = {
    "brainstorming": ("{{BRAINSTORMING_USAGE_CHIP}}", "{{BRAINSTORMING_USAGE}}"),
    "design": ("{{DESIGN_USAGE_CHIP}}", "{{DESIGN_USAGE}}"),
    "plan": ("{{PLAN_USAGE_CHIP}}", "{{PLAN_USAGE}}"),
    "implementation": ("{{IMPLEMENTATION_USAGE_CHIP}}", "{{IMPLEMENTATION_USAGE}}"),
}

# Every feature-panel token. bug-tracker-render blanks all of them by name —
# it is the template's second consumer, and the one nothing in the bug
# workflow reminds you about. Twelve before the usage tokens, twenty after.
FEATURE_PANEL_TOKENS = tuple(
    "{{%s_%s}}" % (prefix, suffix)
    for prefix in ("BRAINSTORMING", "DESIGN", "PLAN", "IMPLEMENTATION")
    for suffix in ("AT", "BULLETS", "DETAILS", "USAGE_CHIP", "USAGE")
)


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
        "artifact_urls",
        "alternatives",
        "design_language",
        "decisions",
        "open_ui_questions",
        "notes",
    )
    # Keys feature-design must consume when it folds the mockup into the design.
    CONSUMED_KEYS = ("status", "chosen_mockup", "artifact_urls", "alternatives",
                     "decisions", "open_ui_questions")
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

    def test_step_4_does_not_close_appearance_decisions(self):
        # The failure this guards: Step 4 runs before Step 5 and is told to close
        # *every* material ambiguity (including a storm §7 full of UI questions).
        # Without a carve-out, a UI-heavy feature arrives at 5a with its
        # appearance "already settled" by answers this skill itself harvested —
        # so the more visual unknowns a feature has, the more likely the mockup
        # is skipped. The rule must invert back.
        design = DESIGN_SKILL.read_text()
        step_4 = design.split("## Step 4 —")[1].split("## Step 5 —")[0]
        assert re.search(r"appearance", step_4, re.I), (
            "feature-design Step 4 has no appearance carve-out — visual decisions "
            "closed here silently license the Step 5a 'Appearance already settled' skip"
        )
        assert "Step 5" in step_4, (
            "feature-design Step 4 must route appearance decisions to Step 5"
        )

    def test_step_5a_excludes_own_clarification_answers(self):
        design = DESIGN_SKILL.read_text()
        step_5 = design.split("## Step 5 —")[1].split("## Step 6 —")[0]
        assert re.search(r"Step 4.{0,200}(do not|never|does not) settle", step_5, re.S | re.I), (
            "feature-design 5a must state that its own Step 4 answers do not "
            "settle appearance — otherwise the skip exit swallows the fire case"
        )

    def test_step_5a_has_a_positive_fire_trip_wire(self):
        design = DESIGN_SKILL.read_text()
        step_5 = design.split("## Step 5 —")[1].split("## Step 6 —")[0]
        assert re.search(r"trip-wire", step_5, re.I), (
            "feature-design 5a has only skip exits and no condition that forces a "
            "fire; the rule needs one so UI-heavy features cannot be reasoned out of it"
        )

    def test_step_5_is_listed_as_load_bearing(self):
        # The intro used to state a *different* rule from 5a ("skipped only when
        # it genuinely has none"), and left Step 5 out of the do-not-skip list.
        intro = DESIGN_SKILL.read_text().split("## Step 0")[0]
        assert re.search(r"Step 5 \(mockup", intro), (
            "feature-design intro must name Step 5 among the load-bearing steps"
        )
        assert "skipped only when it genuinely has none" not in intro, (
            "feature-design intro restates a looser rule than Step 5a's four named exits"
        )

    def test_publishes_each_mockup_as_an_artifact(self):
        # A file:// path is a bad review surface: the user has to leave the
        # conversation, find the file, and open it, and it cannot be shared.
        # The page is published as a Claude Artifact so the round-trip is a
        # click on a link in the same conversation.
        text = self.MOCKUP_SKILL.read_text()
        allowed = next(
            l for l in self.frontmatter().splitlines() if l.startswith("allowed-tools:")
        )
        assert re.search(r"\bArtifact\b", allowed), (
            "feature-mockup cannot publish mockups: Artifact missing from allowed-tools"
        )
        assert re.search(r"publish.{0,120}artifact", text, re.S | re.I), (
            "feature-mockup never instructs publishing the mockup as an artifact"
        )

    def test_artifact_publishing_degrades_to_the_local_file(self):
        # The Artifact tool is not present in every session. Publishing is the
        # preferred presentation, never a precondition — a session without it
        # must still get its mockup, presented as a local path.
        text = self.MOCKUP_SKILL.read_text()
        assert re.search(
            r"(Artifact tool is (not|un)available|artifact.{0,80}not available|"
            r"cannot publish|publishing fails)",
            text,
            re.I,
        ), "feature-mockup never states the fallback when publishing is unavailable"
        assert re.search(r"fall back.{0,160}(local|file)", text, re.S | re.I), (
            "feature-mockup never falls back to the local mockup file"
        )

    def test_the_mockup_file_remains_the_source_of_record(self):
        # Publishing must not turn into "write it to a scratch dir and host it":
        # /feature-plan and /feature-implement read the accepted page out of the
        # feature folder, and the design links it by relative path.
        text = self.MOCKUP_SKILL.read_text()
        assert "mockup-v<N>-<name>.html" in text, (
            "feature-mockup no longer documents its on-disk filename convention"
        )
        assert re.search(
            r"<feature_folder>/mockups/.{0,400}(source|record|committed|repo)",
            text,
            re.S | re.I,
        ), (
            "feature-mockup must keep the file under <feature_folder>/mockups/ as "
            "the source of record, with the artifact as its published view"
        )

    def test_republishing_a_revision_keeps_the_same_url(self):
        # Revisions overwrite the same file; the Artifact contract makes that a
        # redeploy to the same URL. A run that publishes a fresh artifact per
        # round invalidates the link the user is comparing against.
        text = self.MOCKUP_SKILL.read_text()
        assert re.search(r"same (file path|URL).{0,200}(redeploy|republish|same URL)", text, re.S | re.I) or \
            re.search(r"(redeploy|republish).{0,200}same (file path|URL)", text, re.S | re.I), (
            "feature-mockup never states that re-publishing the same file path "
            "updates the same artifact URL"
        )

    def test_supplied_references_outrank_the_grounded_digest(self):
        # A user-supplied screenshot / design link / exact spec is the strongest
        # evidence of what they want; the mockup must not quietly override it.
        text = self.MOCKUP_SKILL.read_text()
        assert "references=" in text, "feature-mockup: references= slot undocumented"
        assert re.search(r"references.{0,200}(precedence|outrank)", text, re.S | re.I), (
            "feature-mockup never states that supplied references take precedence"
        )


class TestC4DiagramContract:
    """diagram-c4-update renders templates/c4-diagram.html by token substitution.

    It is a stylistic sibling of diagram-update but deliberately not a scoping
    one: diagram-update refuses outside this repo (manifest name "dev"), while
    this skill must run in a plugin repo, a conventional software repo, or a
    repo that is only architecture documents. The tests below pin the halves
    that drift silently — the token contract in both directions, the grid
    constants shared between prose and CSS, the reciprocal links, and the C4
    notation rules that make the output a legal C4 diagram rather than a
    picture of boxes.
    """

    # Column/row pitch and box size. Layout correctness rests on these agreeing
    # between the SKILL.md that authors coordinates and the CSS that renders
    # them; a silent divergence produces overlapping boxes on every diagram.
    GRID_PROPS = ("--c4-col-pitch", "--c4-row-pitch", "--c4-box-w", "--c4-box-h")

    def skill_text(self):
        assert C4_SKILL.exists(), "skills/diagram-c4-update/SKILL.md is missing"
        return C4_SKILL.read_text()

    def template_text(self):
        assert C4_TEMPLATE.exists(), "templates/c4-diagram.html is missing"
        return C4_TEMPLATE.read_text()

    def test_token_contract_holds_both_ways(self):
        # test_skill_tokens_exist_in_templates only checks skill -> template.
        # A token left in the template with no skill authoring it renders as a
        # literal `{{...}}` on the page, so check the reverse too.
        skill_tokens = set(re.findall(r"\{\{([A-Z][A-Z0-9_]*)\}\}", self.skill_text()))
        template_tokens = set(
            re.findall(r"\{\{([A-Z][A-Z0-9_]*)\}\}", self.template_text())
        )
        assert template_tokens, "c4-diagram.html defines no tokens"
        assert template_tokens - skill_tokens == set(), (
            "tokens in c4-diagram.html that diagram-c4-update never authors: "
            f"{sorted(template_tokens - skill_tokens)}"
        )
        assert skill_tokens - template_tokens == set(), (
            "tokens diagram-c4-update authors that c4-diagram.html lacks: "
            f"{sorted(skill_tokens - template_tokens)}"
        )

    def test_grid_constants_agree(self):
        template, skill = self.template_text(), self.skill_text()
        for prop in self.GRID_PROPS:
            m = re.search(rf"{prop}:\s*(\d+)px", template)
            assert m, f"c4-diagram.html: CSS custom property {prop} not found"
            assert m.group(1) in skill, (
                f"{prop} is {m.group(1)}px in the template but that number does "
                "not appear in the SKILL.md grid contract"
            )

    def test_grid_geometry_is_consistent(self):
        # Non-overlap is meant to be a theorem, not a hope: every box is
        # exactly one cell, so distinct cells give disjoint rectangles only if
        # the pitch exceeds the box. The boundary chrome then has to fit in the
        # leftover gutter, or a dashed boundary border collides with the
        # neighbouring box it is supposed to sit beside.
        template = self.template_text()

        def px(prop):
            m = re.search(rf"{prop}:\s*(\d+)px", template)
            assert m, f"c4-diagram.html: {prop} not found"
            return int(m.group(1))

        col_pitch, row_pitch = px("--c4-col-pitch"), px("--c4-row-pitch")
        box_w, box_h = px("--c4-box-w"), px("--c4-box-h")
        pad, pad_nested = px("--c4-bpad"), px("--c4-bpad-nested")
        label_h = px("--c4-blabel")

        assert col_pitch > box_w, f"column pitch {col_pitch} must exceed box width {box_w}"
        assert row_pitch > box_h, f"row pitch {row_pitch} must exceed box height {box_h}"

        col_gap, row_gap = col_pitch - box_w, row_pitch - box_h
        assert pad <= col_gap / 2 - 1, (
            f"boundary padding {pad}px does not fit the {col_gap}px column gutter — "
            "two side-by-side boundaries would overlap"
        )
        assert pad + label_h <= row_gap / 2 - 1, (
            f"boundary padding + label ({pad + label_h}px) does not fit the "
            f"{row_gap}px row gutter — the label would sit on the box above"
        )
        assert pad_nested < pad, (
            "nested boundary padding must be smaller than the outer padding, "
            "or the two rings render on top of each other"
        )

    def test_edge_resting_behaviour_is_per_view(self):
        # Two modes, chosen by the level. Landscape, context and container
        # views draw every edge at rest and fade the unpicked ones back — they
        # are small enough that the whole web reads at a glance. Component
        # views draw nothing until a box is picked: a container with twenty
        # peers can carry fifty relationships, which no amount of fading
        # rescues.
        template = self.template_text()

        base = re.search(r"#wires path \{([^}]*)\}", template)
        assert base, "c4-diagram.html: #wires path base rule not found"
        rest = re.search(r"opacity:\s*([\d.]+)", base.group(1))
        assert rest and float(rest.group(1)) > 0, (
            "ambient mode must draw edges at rest — container and component "
            "views show their relationships"
        )
        for cls in ("hl", "dm"):
            assert f"#wires path.{cls}" in template, f"missing #wires path.{cls}"

        # The quiet mode is scoped to a stage attribute, never global.
        quiet = re.findall(r'#stage\[data-edges="hidden"\][^{]*\{([^}]*)\}', template)
        assert quiet, 'c4-diagram.html: no #stage[data-edges="hidden"] rules'
        assert any(re.search(r"opacity:\s*0\s*[;}]", q) for q in quiet), (
            "quiet mode must zero the resting edges"
        )
        assert any(re.search(r"opacity:\s*1\s*[;}]", q) for q in quiet), (
            "quiet mode must still reveal the picked box's edges"
        )
        assert re.search(
            r'stage\.dataset\.edges = \w+ \? "hidden" : "ambient"', template), (
            "the engine must select the mode from the view kind"
        )
        assert re.search(r'const quiet = view\.kind === "component"', template), (
            "quiet mode must be chosen by view kind — the component board is "
            "the dense one; higher views show their edges at rest"
        )
        # Keyboard users must get the same reveal as pointer users.
        for evt in ('"mouseenter"', '"mouseleave"', '"focus"', '"blur"'):
            assert f"addEventListener({evt}, () => setHover(" in template, (
                f"c4-diagram.html: {evt} does not drive setHover"
            )

    def test_arrows_stand_off_the_boxes(self):
        # An arrowhead touching or piercing a box reads as a rendering fault.
        # Three things have to hold together: the endpoints are inset by a
        # gap, the marker's reference point is the arrow TIP (so the tip does
        # not overshoot by one stroke-width, which would grow when an edge is
        # highlighted), and a scope ring — painted outside offsetWidth, so
        # invisible to the geometry — is added to the gap.
        template = self.template_text()

        assert re.search(r"--c4-edge-gap:\s*\d+px", template), "no --c4-edge-gap"
        assert re.search(r"--c4-scope-ring:\s*\d+px", template), "no --c4-scope-ring"
        assert "var(--c4-scope-ring)" in template, (
            "the scope ring width must come from the variable, or the gap "
            "silently stops matching the ring it compensates for"
        )
        markers = re.findall(r"<marker\b[^>]*>", template, re.S)
        assert markers, "c4-diagram.html: arrow markers not found"
        for m in markers:
            assert 'refX="0"' in m, (
                "marker refX must be 0 so the arrowhead's BASE sits on the path "
                "end — anything else draws the line through the head to its tip"
            )
            assert 'markerUnits="userSpaceOnUse"' in m, (
                "arrowheads must be sized in px, not stroke-widths, or they "
                "grow when an edge is highlighted and eat the standoff"
            )
        # The head extends forward from the path end, so the receiving end has
        # to back off by its length on top of the gap.
        assert re.search(r'const ARROW = parseFloat\(\s*document\.getElementById\("m-sync"\)'
                         r'\.getAttribute\("markerWidth"\)\)', template), (
            "arrow length must be read off the marker, not restated in the JS"
        )
        assert "function edgeGap(" in template, "no per-endpoint gap helper"
        assert re.search(r"const ga = edgeGap\(r\.sourceId\), "
                         r"gb = edgeGap\(r\.destinationId\) \+ ARROW", template), (
            "the destination endpoint must also back off by the arrow length"
        )
        for axis in ("x1", "x2", "y1", "y2"):
            assert re.search(rf"{axis} = dir > 0 \? .*g[ab].*: .*g[ab]", template), (
                f"{axis} is not offset by an endpoint gap"
            )
        assert not re.search(r"\.el:hover \{[^}]*transform:", template), (
            "a hover transform moves the box but not its edges, which are laid "
            "out from offsetTop/offsetLeft — the gap would shift on hover"
        )

    def test_runs_in_any_repo(self):
        # The whole point of this skill versus diagram-update. Copy-paste from
        # the sibling would silently import a refusal that breaks every repo
        # except this one.
        skill = self.skill_text()
        assert "only runs inside the dev-skills" not in skill, (
            "diagram-c4-update must not carry diagram-update's repo refusal"
        )
        assert re.search(r"any repo|any project|software repo", skill, re.I), (
            "diagram-c4-update never states that it runs outside this repo"
        )

    def test_c4_notation_rules_are_enforced(self):
        # docs/c4-model.md 8 and 9: these are what separate a C4 diagram from
        # an unlabelled box drawing, and they are the skill's job to guarantee.
        skill = self.skill_text().lower()
        for rule, needle in (
            ("a mandatory legend", "legend"),
            ("per-element technology", "technology"),
            ("no bare 'Uses' relationship labels", '"uses"'),
            ("unidirectional relationships", "unidirectional"),
        ):
            assert needle in skill, f"diagram-c4-update never mentions {rule}"

    def test_reciprocal_links_declared_on_both_sides(self):
        # Two links pointing opposite ways, each resolved from the filesystem
        # so neither skill has to know the other exists.
        for token, skill_file, template in (
            ("C4_WORKFLOW_LINK", C4_SKILL, C4_TEMPLATE),
            ("WORKFLOW_C4_LINK", WORKFLOW_SKILL, WORKFLOW_TEMPLATE),
        ):
            assert f"{{{{{token}}}}}" in template.read_text(), (
                f"{template.name}: {{{{{token}}}}} missing"
            )
            assert f"{{{{{token}}}}}" in skill_file.read_text(), (
                f"{skill_file.parent.name}: {{{{{token}}}}} undocumented"
            )

    def test_frontmatter(self):
        m = re.match(r"---\n(.*?)\n---\n", self.skill_text(), re.DOTALL)
        assert m, "diagram-c4-update: missing frontmatter"
        frontmatter = m.group(1)
        assert re.search(r"^user-invocable:\s*true\s*$", frontmatter, re.MULTILINE), (
            "diagram-c4-update must be user-invocable"
        )
        # Skills run on the user's current session model/effort; hardcoded pins
        # are a plugin-wide invariant violation (CLAUDE.md).
        for pin in ("model", "effort"):
            assert not re.search(rf"^{pin}:", frontmatter, re.MULTILINE), (
                f"diagram-c4-update pins {pin} in frontmatter"
            )

    def test_template_is_self_contained(self):
        # The rendered page must work offline from file:// — no CDN, no fonts,
        # no remote images.
        offenders = re.findall(
            r'(?:src|href)="(https?://[^"]+)"', self.template_text()
        )
        assert not offenders, f"c4-diagram.html references external hosts: {offenders}"

    def test_does_not_call_lessons_capture(self):
        # Same reasoning as diagram-update and bug-submit: a rendering skill's
        # reflection overhead is not worth it. Checked structurally rather than
        # by absence of the string — the SKILL.md *documents* the decision, and
        # that sentence is worth keeping. Without the Skill tool it cannot
        # invoke another skill at all, the feature-mockup precedent.
        skill = self.skill_text()
        m = re.match(r"---\n(.*?)\n---\n", skill, re.DOTALL)
        tools = re.search(r"^allowed-tools:\s*(.+)$", m.group(1), re.MULTILINE)
        assert tools, "diagram-c4-update: no allowed-tools line"
        assert not re.search(r"\bSkill\b", tools.group(1)), (
            "diagram-c4-update holds the Skill tool, so it could invoke "
            "lessons-capture; drop the tool or revisit the decision"
        )
        assert re.search(r"does \*\*not\*\* call `lessons-capture`", skill), (
            "diagram-c4-update should state that it does not call lessons-capture"
        )


class TestSetHerdrLabelContract:
    """set-herdr-label is a model-only side-effect helper, not a chain skill.

    Its contract has two halves that both break silently if edited casually.
    The *plugin* half: model-only, writes nothing, no lessons-capture, no
    Step 0 gate (it is invoked by the model mid-turn, so a gate would defeat
    the point). The *herdr CLI* half: names are validated server-side against
    ``^[a-z][a-z0-9_-]{0,31}$``, and neither ``""`` nor ``"-"`` passes that
    check — ``--clear`` is the only way to unset a name. A well-meaning edit
    that "simplifies" the empty case back to passing an empty string produces
    a skill that fails every time it is asked to clear a label.
    """

    def skill_text(self):
        return LABEL_SKILL.read_text()

    def test_skill_exists(self):
        assert LABEL_SKILL.exists(), "skills/set-herdr-label/SKILL.md is missing"

    def test_is_model_only(self):
        frontmatter = re.match(r"---\n(.*?)\n---\n", self.skill_text(), re.DOTALL)
        assert frontmatter, "set-herdr-label: missing frontmatter"
        frontmatter = frontmatter.group(1)
        assert re.search(r"^user-invocable:\s*false\s*$", frontmatter, re.MULTILINE), (
            "set-herdr-label must not be user-invocable"
        )
        for pin in ("model", "effort"):
            assert not re.search(rf"^{pin}:", frontmatter, re.MULTILINE), (
                f"set-herdr-label pins {pin} in frontmatter"
            )

    def test_writes_nothing_and_cannot_invoke_other_skills(self):
        # It renames a pane and nothing else: no file writes, and without the
        # Skill tool it cannot reach lessons-capture (the feature-mockup
        # precedent). allowed-tools is the structural guard.
        m = re.match(r"---\n(.*?)\n---\n", self.skill_text(), re.DOTALL)
        tools = re.search(r"^allowed-tools:\s*(.+)$", m.group(1), re.MULTILINE)
        assert tools, "set-herdr-label: no allowed-tools line"
        for forbidden in ("Skill", "Write", "Edit", "AskUserQuestion"):
            assert not re.search(rf"\b{forbidden}\b", tools.group(1)), (
                f"set-herdr-label must not hold the {forbidden} tool"
            )

    def test_gates_on_herdr_env(self):
        skill = self.skill_text()
        assert "HERDR_ENV" in skill, "set-herdr-label never checks HERDR_ENV"
        assert re.search(r'HERDR_ENV[^\n]*!=[^\n]*"1"', skill), (
            "set-herdr-label must skip unless HERDR_ENV is exactly 1"
        )

    def test_targets_the_current_pane_by_env(self):
        # The target is the pane this session runs in, read from the
        # environment — never guessed by matching cwd against `herdr agent
        # list`, which would rename someone else's pane on a cwd collision.
        skill = self.skill_text()
        assert "HERDR_PANE_ID" in skill, (
            "set-herdr-label must target $HERDR_PANE_ID"
        )
        # Checked as a documented prohibition rather than absence of the
        # string — `allowed-tools: Bash(herdr *)` permits `herdr agent list`,
        # so prose is the only guard, and that sentence is worth keeping (the
        # diagram-c4-update precedent).
        assert re.search(r"never call `herdr agent list`", skill), (
            "set-herdr-label must forbid discovering its target via "
            "`herdr agent list` — a cwd match renames the wrong agent"
        )

    def test_empty_label_clears_rather_than_sending_an_empty_name(self):
        skill = self.skill_text()
        assert "--clear" in skill, (
            "set-herdr-label must use `herdr agent rename --clear` for the "
            "empty case; herdr rejects both an empty name and '-'"
        )

    def test_documents_the_name_charset_constraint(self):
        # herdr validates names server-side; the skill must normalise before
        # calling, or every label with a space or capital fails.
        skill = self.skill_text()
        assert "a-z0-9_-" in skill, (
            "set-herdr-label must document herdr's accepted name charset"
        )
        assert "32" in skill, (
            "set-herdr-label must document herdr's 32-character name limit"
        )

    def test_is_silent_on_skip(self):
        skill = self.skill_text()
        assert re.search(r"\bsilent|\bquiet|no output", skill, re.IGNORECASE), (
            "set-herdr-label must document that skipping is silent"
        )


class TestHerdrLabelLifecycle:
    """The four chain skills label the herdr pane for the length of a run.

    Set once in Step 1 and cleared at the end, so a workspace of parallel
    agents shows which skill each pane is running. Two placement rules carry
    the weight, and both are regressions waiting to happen:

    * The set lives in **Step 1, not Step 0**. Step 0 is the confirmation
      gate; labelling before it means a declined confirmation strands a label
      on a run that never started and has no end to clear it.
    * The clear lives **before the final step's offer**, not after it. On the
      chain-in branch the skill hands over through the `Skill` tool and never
      returns to the step, so a trailing clear would silently never run.

    The blocks are mirrored verbatim across all four skills (modulo the slug),
    checked as a set for the same reason as the terminology block.
    """

    SET_RE = r"^\*\*Label the herdr pane\.\*\*.*$"
    CLEAR_RE = r"^\*\*Clear the herdr pane label\.\*\*.*$"

    def test_each_skill_sets_its_own_slug(self):
        for slug in FEATURE_SKILLS:
            line = re.search(self.SET_RE, skill_text(slug), re.MULTILINE)
            assert line, f"{slug}: no herdr label-set block"
            assert f"`{slug}`" in line.group(0), (
                f"{slug}: labels the pane with something other than its own slug"
            )

    def test_each_skill_clears_with_no_argument(self):
        for slug in FEATURE_SKILLS:
            line = re.search(self.CLEAR_RE, skill_text(slug), re.MULTILINE)
            assert line, f"{slug}: no herdr label-clear block"
            assert "**no argument**" in line.group(0), (
                f"{slug}: clear block does not state that it passes no argument"
            )

    def test_set_lives_in_step_1_not_step_0(self):
        # A label set inside the Step 0 gate outlives a declined confirmation.
        for slug in FEATURE_SKILLS:
            text = skill_text(slug)
            at = re.search(self.SET_RE, text, re.MULTILINE).start()
            start, end = step_span(text, 1)
            assert start < at < end, (
                f"{slug}: the herdr label is set outside Step 1 — a declined "
                f"Step 0 confirmation would strand it"
            )

    def test_clear_precedes_the_final_offer(self):
        # Every chain skill ends with an AskUserQuestion offer; the clear has
        # to come first or the hand-over branch skips it.
        for slug in FEATURE_SKILLS:
            text = skill_text(slug)
            at = re.search(self.CLEAR_RE, text, re.MULTILINE).start()
            offer = text.index("AskUserQuestion", at)
            assert text.count("AskUserQuestion", at) >= 1, (
                f"{slug}: no offer follows the clear block"
            )
            assert at < offer, f"{slug}: clear block does not precede the offer"

    def test_clearing_before_any_stop_is_a_constraint(self):
        # The enumerated exits cannot cover every halt, so the catch-all is
        # what stops an unanticipated stop path from stranding a label.
        for slug in FEATURE_SKILLS:
            assert re.search(
                r"\*\*Clear the herdr label before you stop\.\*\*",
                skill_text(slug),
            ), f"{slug}: no catch-all constraint clearing the label on early exits"

    def test_blocks_are_mirrored_across_the_four_skills(self):
        for label, pattern in (("set", self.SET_RE), ("clear", self.CLEAR_RE)):
            seen = {}
            for slug in FEATURE_SKILLS:
                line = re.search(pattern, skill_text(slug), re.MULTILINE)
                seen[slug] = line.group(0).replace(f"`{slug}`", "`<slug>`")
            assert len(set(seen.values())) == 1, (
                f"the herdr {label} block has drifted between feature-* skills"
            )


class TestUsageReportLifecycle:
    """The four chain skills report what a run cost, via the usage-report helper.

    Modelled on TestHerdrLabelLifecycle, and needed for the same reason: the
    feature is spread across six files that nothing else forces to agree. The
    tracker template carries eight tokens, `scripts/usage_report.py` is the
    only thing that fills them, `skills/usage-report/SKILL.md` is the only
    skill that names them, and `bug-tracker-render` — the template's *second*
    consumer — has to blank them, or every regenerated bug tracker renders
    literal `{{DESIGN_USAGE}}` text.
    """

    def panel_span(self, text, panel):
        """(start, end) offsets of the tracker template's `panel-<panel>` section."""
        start = text.find(f'id="panel-{panel}"')
        assert start != -1, f"no `id=\"panel-{panel}\"` section in the template"
        return start, text.index("</section>", start)

    def test_eight_usage_tokens_exist_in_the_template(self):
        text = TRACKER_TEMPLATE.read_text()
        for panel, tokens in USAGE_TOKENS.items():
            start, end = self.panel_span(text, panel)
            for token in tokens:
                assert token in text, (
                    f"{token} not in templates/feature-tracker.html"
                )
                # Searched within the span, not by first index — the doc
                # comment at the top of the template legends all eight.
                assert token in text[start:end], (
                    f"{token} sits outside the {panel} panel"
                )

    def test_the_rendered_chip_and_table_are_styled_by_the_template(self):
        # The script owns the markup, the template owns its presentation, and
        # nothing makes the two agree: a renamed class renders an unstyled
        # table rather than failing anything.
        script, template = USAGE_SCRIPT.read_text(), TRACKER_TEMPLATE.read_text()
        for markup, selector in (
            ('<span class="chip usage">', ".chip.usage"),
            ('<table class="usage">', "table.usage"),
        ):
            assert markup in script, f"usage_report.py no longer renders {markup}"
            assert selector in template, (
                f"templates/feature-tracker.html has no `{selector}` rule, so "
                f"{markup} renders unstyled"
            )

    def test_script_token_map_matches_the_template(self):
        # Read as text, not imported: TRACKER_TOKENS is the script's half of
        # the contract and this asserts it names exactly the eight tokens the
        # template above was just shown to carry.
        block = re.search(
            r"^TRACKER_TOKENS[^=]*= \{(.*?)^\}", USAGE_SCRIPT.read_text(),
            re.DOTALL | re.MULTILINE,
        )
        assert block, "scripts/usage_report.py: no TRACKER_TOKENS mapping"
        named = set(re.findall(r"\{\{[A-Z0-9_]+\}\}", block.group(1)))
        expected = {token for pair in USAGE_TOKENS.values() for token in pair}
        assert named == expected, (
            "TRACKER_TOKENS disagrees with the template's usage tokens: "
            f"{named ^ expected}"
        )

    def test_bug_tracker_render_blanks_twenty_tokens(self):
        # The bug tracker hides the feature panels but still renders their
        # text, so a token it does not blank leaks as a literal `{{...}}`.
        line = next(
            (
                line
                for line in BUG_TRACKER_SKILL.read_text().splitlines()
                if "feature-panel tokens" in line
            ),
            None,
        )
        assert line, "bug-tracker-render: no feature-panel blanking instruction"
        assert "twelve" not in line, (
            "bug-tracker-render still says twelve feature-panel tokens"
        )
        assert "twenty" in line, (
            "bug-tracker-render must blank all twenty feature-panel tokens"
        )
        missing = [token for token in FEATURE_PANEL_TOKENS if token not in line]
        assert not missing, f"bug-tracker-render does not blank {missing}"

    # --- The helper skill itself --------------------------------------

    def test_usage_report_is_internal_only(self):
        frontmatter = re.match(r"---\n(.*?)\n---\n", USAGE_SKILL.read_text(), re.DOTALL)
        assert frontmatter, "usage-report: missing frontmatter"
        frontmatter = frontmatter.group(1)
        assert re.search(r"^user-invocable:\s*false\s*$", frontmatter, re.MULTILINE), (
            "usage-report must not be user-invocable — it is a call-site helper"
        )
        assert not re.search(
            r"^disable-model-invocation:\s*true", frontmatter, re.MULTILINE
        ), (
            "usage-report must stay model-invocable — the four chain skills "
            "invoke it through the Skill tool"
        )
        for pin in ("model", "effort"):
            assert not re.search(rf"^{pin}:", frontmatter, re.MULTILINE), (
                f"usage-report pins {pin} in frontmatter"
            )

    def test_usage_report_owns_the_usage_tokens(self):
        tokens = {token for pair in USAGE_TOKENS.values() for token in pair}
        missing = sorted(t for t in tokens if t not in USAGE_SKILL.read_text())
        assert not missing, f"usage-report does not name its own tokens: {missing}"
        # Sole *filling* owner. bug-tracker-render is the one other skill
        # allowed to name them, and it blanks rather than fills (design §5
        # C6); anyone else naming them would be a second writer.
        for skill_file in all_skill_files():
            if skill_file.parent.name in ("usage-report", "bug-tracker-render"):
                continue
            also = sorted(t for t in tokens if t in skill_file.read_text())
            assert not also, f"{skill_file.parent.name} also names {also}"

    def test_usage_chip_is_never_a_timestamp_chip(self):
        # feature-list derives a feature's last-activity date by matching
        # `Updated <date>` in the tracker's chips. A usage chip in that shape
        # makes every feature report the wrong date, and nothing else catches
        # it — feature-list would simply read a plausible wrong number.
        text = USAGE_SKILL.read_text()
        assert "feature-list" in text, (
            "usage-report must name feature-list as the reason for the chip shape"
        )
        constraint = next(
            (line for line in text.splitlines() if "`Updated`" in line), None
        )
        assert constraint, "usage-report never states the feature-list chip constraint"
        assert "never" in constraint.lower(), (
            f"the chip constraint is not stated as a prohibition: {constraint!r}"
        )

    def test_usage_report_never_calls_feature_resolve(self):
        text = USAGE_SKILL.read_text()
        assert "feature-resolve" in text, (
            "usage-report should record that it never calls feature-resolve — it "
            "takes its pathing as input (the feature-mockup precedent)"
        )
        for line in text.splitlines():
            if "feature-resolve" in line:
                assert "never" in line.lower(), (
                    "usage-report mentions feature-resolve outside a "
                    f"'never calls' sentence: {line!r}"
                )

    def test_the_skill_holds_no_transcript_schema_knowledge(self):
        # All schema knowledge stays in scripts/usage_report.py, so a
        # transcript-format change is a one-file fix (design §5, C2).
        text = USAGE_SKILL.read_text()
        leaked = [
            field
            for field in (
                "requestId",
                "output_tokens_details",
                "cache_creation_input_tokens",
                "cache_read_input_tokens",
                "ephemeral_1h_input_tokens",
                "ephemeral_5m_input_tokens",
                "server_tool_use",
                "service_tier",
            )
            if field in text
        ]
        assert not leaked, f"usage-report names transcript schema fields: {leaked}"

    # --- The start call sites in the four chain skills -----------------

    START_RE = r"^\*\*Start the usage window\.\*\*.*$"

    def test_each_skill_starts_usage_with_its_own_slug(self):
        for slug in FEATURE_SKILLS:
            line = re.search(self.START_RE, skill_text(slug), re.MULTILINE)
            assert line, f"{slug}: no usage-start block"
            assert f"`start {slug}`" in line.group(0), (
                f"{slug}: opens the usage window with something other than its "
                f"own slug — the marker is keyed on session and slug, so a "
                f"wrong one is reported by whichever skill owns it"
            )

    def test_start_lives_in_step_1_not_step_0(self):
        # Same reasoning as the herdr label beside it: Step 0 is the
        # confirmation gate, and a marker written before it outlives a
        # declined run with no report to clear it.
        for slug in FEATURE_SKILLS:
            text = skill_text(slug)
            at = re.search(self.START_RE, text, re.MULTILINE).start()
            start, end = step_span(text, 1)
            assert start < at < end, (
                f"{slug}: the usage window is opened outside Step 1 — a "
                f"declined Step 0 confirmation would strand the marker"
            )

    def test_start_blocks_are_mirrored(self):
        seen = {
            re.search(self.START_RE, skill_text(slug), re.MULTILINE)
            .group(0)
            .replace(slug, "<slug>")
            for slug in FEATURE_SKILLS
        }
        assert len(seen) == 1, (
            "the usage-start block has drifted between feature-* skills"
        )

    # --- The report call sites and their deliberate asymmetry ---------

    REPORT_RE = r"^\*\*Report the run usage\.\*\*.*$"

    def final_step_span(self, text):
        """(start, end) offsets of the skill's highest-numbered Step section."""
        last = max(int(n) for n in re.findall(r"^## Step (\d+) —", text, re.MULTILINE))
        return step_span(text, last)

    def test_each_skill_reports_with_its_own_slug(self):
        for slug in FEATURE_SKILLS:
            text = skill_text(slug)
            line = re.search(self.REPORT_RE, text, re.MULTILINE)
            assert line, f"{slug}: no usage-report block"
            assert f"report {slug}" in line.group(0), (
                f"{slug}: closes a usage window that is not its own — the "
                f"marker is keyed on session and slug"
            )
            start, end = self.final_step_span(text)
            assert start < line.start() < end, (
                f"{slug}: the usage report is not in its final step, so an "
                f"earlier return would leave the window open"
            )

    def test_report_precedes_the_offer_for_the_three_chaining_skills(self):
        # These three hand over through the Skill tool on acceptance and never
        # return to the step, so a report placed after the offer would
        # silently never run — the same reasoning as the herdr label clear.
        for slug in ("feature-storm", "feature-design", "feature-plan"):
            text = skill_text(slug)
            at = re.search(self.REPORT_RE, text, re.MULTILINE).start()
            start, end = self.final_step_span(text)
            offer = text.index("AskUserQuestion", start)
            assert at < offer, (
                f"{slug}: the usage report follows the chain offer — on the "
                f"hand-over branch it would never run"
            )

    def test_implement_reports_after_the_eval_relay(self):
        # The one deliberate asymmetry, and the one most likely to be tidied
        # into line with the three above. feature-implement's final question
        # hands over to nothing and control returns on every branch, so the
        # report sits last — which is the only position that can include the
        # eval subagents the user chose to run inside the measured window.
        text = skill_text("feature-implement")
        at = re.search(self.REPORT_RE, text, re.MULTILINE).start()
        start, _ = self.final_step_span(text)
        offer = text.index("AskUserQuestion", start)
        relay = text.index("When both return", start)
        assert at > offer, (
            "feature-implement: the usage report precedes its eval offer, so "
            "an accepted eval run falls outside the window it reports"
        )
        assert at > relay, (
            "feature-implement: the usage report precedes the eval relay"
        )

    def test_reporting_before_any_stop_is_a_constraint(self):
        # The enumerated early exits cannot cover every halt; without the
        # catch-all an unanticipated stop leaves a marker and no log entry.
        for slug in FEATURE_SKILLS:
            assert re.search(
                r"\*\*Report the run usage before you stop\.\*\*", skill_text(slug)
            ), f"{slug}: no catch-all constraint reporting usage on early exits"

    def test_early_exits_report_halted(self):
        # A halted run still cost tokens. Each enumerated early exit has to
        # say so, or those runs vanish from the log and skew every average.
        exits = {
            # Step 2's relay, not the Execution-model paragraph that also
            # names the protocol — the relay is the code path that stops.
            "feature-plan": ("If the message starts with `BLOCKED:`",),
            "feature-implement": ("Tests already failing", "## Step 6 —"),
        }
        for slug, anchors in exits.items():
            text = skill_text(slug)
            for anchor in anchors:
                where = text.index(anchor)
                window = text[where : where + 4000]
                assert "outcome=halted" in window, (
                    f"{slug}: the early exit at {anchor!r} does not report "
                    f"outcome=halted"
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


class TestSkillCustomizeContract:
    """skill-customize stores per-skill behaviour overrides in the plugin's data dir.

    Two halves of its contract break silently under a well-meaning edit.

    The *resolution* half: ``${CLAUDE_PLUGIN_DATA}`` is a plugin-config
    substitution token, not an exported environment variable — Claude Code
    expands it in hook / MCP / LSP command strings and nowhere else, so a skill
    that simply reads ``$CLAUDE_PLUGIN_DATA`` from its shell gets an empty
    string and silently writes to ``/<slug>.extras``. Every consumer therefore
    resolves the directory the same documented way, and because the writer and
    each reader must agree on the answer, that ladder is a mirrored block
    guarded like the herdr-label ones.

    The *authority* half: a customisation refines a skill, it never overrides a
    rule the skill marks non-negotiable. Drop that sentence and the extras file
    becomes a way to talk any skill out of its own safety constraints.
    """

    CUSTOMIZE_SKILL = SKILLS / "skill-customize" / "SKILL.md"
    # Skills wired to load their own .extras. Every test below runs against
    # all of them; add a slug here when you wire a new reader.
    READERS = (
        "feature-mockup",
        "feature-storm",
        "feature-design",
        "feature-plan",
        "feature-implement",
    )
    # Readers whose Step 0 is the proactive-invocation confirmation gate. The
    # load must sit *after* it, for the reason the herdr label does: a run the
    # user declined must not have done work first. feature-mockup is excluded
    # because it has no gate (its caller already gated) and its load IS Step 0.
    GATED_READERS = (
        "feature-storm",
        "feature-design",
        "feature-plan",
        "feature-implement",
    )
    # Readers that hand their real work to subagents. A subagent starts with a
    # fresh context and cannot resolve the data directory reliably, so the main
    # agent loads once and passes the text down in the brief — exactly as it
    # keeps the herdr label and the usage window to itself. Miss this and
    # customising feature-implement changes nothing, because Step 5 is
    # delegated and the customisations never reach the agent doing the work.
    DELEGATING_READERS = ("feature-plan", "feature-implement")
    # The marker introducing the mirrored resolution ladder in every consumer.
    LADDER_MARKER = "**Resolving `${CLAUDE_PLUGIN_DATA}`.**"

    def customize_text(self):
        return self.CUSTOMIZE_SKILL.read_text()

    def frontmatter(self):
        m = re.match(r"---\n(.*?)\n---\n", self.customize_text(), re.DOTALL)
        assert m, "skill-customize: missing frontmatter"
        return m.group(1)

    def load_section(self, text, where):
        """The load block: from the resolution marker to the next `## ` heading.

        For feature-mockup that is its Step 0 body; for a chain skill it is the
        remainder of Step 1. Rules that must live *with* the load are asserted
        against this window rather than the whole file, or a chain skill would
        pass on the strength of prose that has nothing to do with customisation.
        """
        i = text.find(self.LADDER_MARKER)
        assert i != -1, f"{where}: missing the {self.LADDER_MARKER} block"
        nxt = re.search(r"^## ", text[i:], re.MULTILINE)
        return text[i:i + nxt.start()] if nxt else text[i:]

    def ladder(self, text, where):
        """The fenced block following the resolution marker in one consumer."""
        i = text.find(self.LADDER_MARKER)
        assert i != -1, f"{where}: missing the {self.LADDER_MARKER} block"
        m = re.search(r"^```[a-z]*\n(.*?)^```", text[i:], re.DOTALL | re.MULTILINE)
        assert m, f"{where}: the resolution marker is not followed by a fenced ladder"
        return m.group(1)

    def test_skill_exists(self):
        assert self.CUSTOMIZE_SKILL.exists(), "skills/skill-customize/SKILL.md is missing"

    def test_is_user_facing_and_model_invocable(self):
        # Typed by the user as /skill-customize, and reachable by the model when
        # the user says "make /feature-mockup always do X" in plain words.
        frontmatter = self.frontmatter()
        assert re.search(r"^user-invocable:\s*true\s*$", frontmatter, re.MULTILINE), (
            "skill-customize must be user-invocable"
        )
        assert not re.search(
            r"^disable-model-invocation:\s*true\s*$", frontmatter, re.MULTILINE
        ), "skill-customize must stay model-invocable"
        for pin in ("model", "effort"):
            assert not re.search(rf"^{pin}:", frontmatter, re.MULTILINE), (
                f"skill-customize pins {pin} in frontmatter"
            )

    def test_declares_an_argument_hint(self):
        assert re.search(r"^argument-hint:\s*\S", self.frontmatter(), re.MULTILINE), (
            "skill-customize takes a skill name — it must declare an argument-hint"
        )

    def test_validates_the_slug_against_the_skills_directory(self):
        # The legal set is whatever is on disk. A hardcoded roster goes stale
        # the moment a skill is added, and the failure is a false "unknown
        # skill" rejection the user cannot work around.
        text = self.customize_text()
        assert re.search(r"skills/\s*`?\s*director|`skills/`", text) or "skills/" in text, (
            "skill-customize must derive the legal slugs from the skills/ directory"
        )
        assert "never" in text.lower() and "hardcod" in text.lower(), (
            "skill-customize must forbid hardcoding the list of skills"
        )

    def test_extras_filename_shape_is_shared(self):
        assert "<skill_name>.extras" in self.customize_text(), (
            "skill-customize must document the <skill_name>.extras filename"
        )
        for slug in self.READERS:
            section = self.load_section(skill_text(slug), slug)
            assert f"{slug}.extras" in section, (
                f"{slug}: the load block must name its own {slug}.extras file"
            )

    def test_documents_that_the_variable_is_not_an_env_var(self):
        # The whole reason the ladder exists. Without this sentence the next
        # editor "simplifies" it back to $CLAUDE_PLUGIN_DATA and every write
        # lands outside the data directory.
        for where, text in [("skill-customize", self.customize_text())] + [
            (slug, skill_text(slug)) for slug in self.READERS
        ]:
            # Whitespace-normalised: the fact must be stated, but the prose is
            # free to wrap wherever it reads best.
            flat = " ".join(text.split())
            assert "not an exported environment variable" in flat, (
                f"{where}: must state that ${{CLAUDE_PLUGIN_DATA}} is not an env var"
            )

    def test_resolution_ladder_is_mirrored(self):
        canonical = self.ladder(self.customize_text(), "skill-customize")
        assert "CLAUDE_CONFIG_DIR" in canonical, (
            "the resolution ladder must fall back through $CLAUDE_CONFIG_DIR"
        )
        assert "plugins/data/" in canonical, (
            "the resolution ladder must name <config-dir>/plugins/data/"
        )
        for slug in self.READERS:
            assert self.ladder(skill_text(slug), slug) == canonical, (
                f"the ${{CLAUDE_PLUGIN_DATA}} resolution ladder has drifted between "
                f"skill-customize and {slug} — writer and reader would disagree on "
                f"which file is the customisation"
            )

    def test_customisations_never_override_non_negotiable_constraints(self):
        assert re.search(r"non-negotiable", self.customize_text(), re.IGNORECASE), (
            "skill-customize: must state that a customisation cannot override a "
            "non-negotiable constraint"
        )
        for slug in self.READERS:
            # Asserted inside the load block: every skill in this plugin has a
            # `Constraints (non-negotiable)` heading, so a whole-file search
            # would pass on that alone and guard nothing.
            section = self.load_section(skill_text(slug), slug)
            assert re.search(r"non-negotiable", section, re.IGNORECASE), (
                f"{slug}: the load block must state that a customisation cannot "
                f"override a non-negotiable constraint"
            )

    def test_shows_the_file_verbatim(self):
        text = self.customize_text()
        assert re.search(r"verbatim", text, re.IGNORECASE), (
            "skill-customize must share the extras file verbatim when asked"
        )
        assert re.search(r"never summaris|never summariz|do not summaris|do not summariz",
                         text, re.IGNORECASE), (
            "skill-customize must forbid summarising the file instead of showing it"
        )

    def test_is_not_part_of_the_feature_chain(self):
        # Same posture as bug-submit and feature-list: no resolver (it would
        # allocate feature folders), no lessons log, no usage window.
        text = self.customize_text()
        for helper in ("feature-resolve", "lessons-capture", "usage-report"):
            assert helper in text, (
                f"skill-customize must state that it never calls {helper}"
            )
        tools = re.search(r"^allowed-tools:\s*(.+)$", self.frontmatter(), re.MULTILINE)
        assert tools, "skill-customize: no allowed-tools line"
        assert not re.search(r"\bSkill\b", tools.group(1)), (
            "skill-customize must not hold the Skill tool — it calls nothing"
        )

    def test_readers_load_extras_before_doing_any_work(self):
        # The load has to happen before the work it can change. feature-mockup
        # puts it in Step 0, ahead of Step 1's is-there-a-surface decision; the
        # chain skills put it in Step 1 beside the herdr label and the usage
        # window. Either way it must be settled before Step 2.
        for slug in self.READERS:
            text = skill_text(slug)
            load = text.find(self.LADDER_MARKER)
            step2 = re.search(r"^## Step 2 —", text, re.MULTILINE)
            assert step2, f"{slug}: no `## Step 2` heading"
            assert 0 < load < step2.start(), (
                f"{slug}: the customisation load must be settled before Step 2"
            )

    def test_gated_readers_load_after_their_confirmation_gate(self):
        # Same rule the herdr label follows, for the same reason: Step 0 is the
        # proactive-invocation gate, and a run the user declined must not have
        # read, announced or applied anything first.
        for slug in self.GATED_READERS:
            text = skill_text(slug)
            gate = re.search(r"^## Step 0 —", text, re.MULTILINE)
            assert gate, f"{slug}: no `## Step 0` gate heading"
            step1 = re.search(r"^## Step 1 —", text, re.MULTILINE)
            assert step1, f"{slug}: no `## Step 1` heading"
            load = text.find(self.LADDER_MARKER)
            assert load > step1.start(), (
                f"{slug}: the customisation load must sit in Step 1, after the "
                f"Step 0 confirmation gate — not before it"
            )

    def test_delegating_readers_pass_customisations_into_the_subagent_brief(self):
        # feature-plan delegates Steps 3-10 and feature-implement delegates its
        # stage loop. If the brief omits the customisations, the agent doing the
        # work never sees them and the whole feature is inert for those skills.
        for slug in self.DELEGATING_READERS:
            text = skill_text(slug)
            brief = re.search(
                r"^(?:A|The) subagent starts with a fresh context.*?(?=^#{2,4} )",
                text,
                re.DOTALL | re.MULTILINE,
            )
            assert brief, f"{slug}: could not locate the subagent briefing list"
            assert re.search(r"customisation", brief.group(0), re.IGNORECASE), (
                f"{slug}: the subagent brief must pass the loaded customisations "
                f"down — otherwise customising this skill changes nothing"
            )

    def test_readers_treat_a_missing_extras_file_as_a_silent_no_op(self):
        # The common path by far. A reader that announces "no customisations"
        # every run adds a line of noise to every mockup ever drawn.
        for slug in self.READERS:
            section = self.load_section(skill_text(slug), slug)
            assert re.search(r"silent|say nothing|no output", section, re.IGNORECASE), (
                f"{slug}: a missing .extras file must be a silent no-op"
            )
