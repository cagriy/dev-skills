"""Layer 2: golden-fixture judge tests for the artefact quality rubrics.

Each fixture is a storm or design document with known ground truth. The shipped
rubric is extracted from evals-e2e-run/SKILL.md (so the test always judges with
exactly what the skill ships) and run through a headless `claude` judge.
Assertions are score bands, not exact values, to absorb judge nondeterminism;
widen to median-of-3 only if bands prove flaky in practice.

Excluded by default — run explicitly with `uv run pytest -m llm` (token cost).
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from helpers import design_quality_rubric, storm_quality_rubric

FIXTURES = Path(__file__).resolve().parent / "fixtures"
JUDGE_TIMEOUT_SECONDS = 480

pytestmark = [
    pytest.mark.llm,
    pytest.mark.skipif(shutil.which("claude") is None, reason="claude CLI not available"),
]

ARTEFACTS = {
    "storm": {
        "kind": "storm document",
        "eval_type": "storm_quality",
        "rubric": storm_quality_rubric,
        "items_assessed": 10,
    },
    "design": {
        "kind": "design document",
        "eval_type": "design_quality",
        "rubric": design_quality_rubric,
        "items_assessed": 15,
    },
}

BRIEF_TEMPLATE = """You are an evaluation judge scoring one artefact. Judge the {kind} below against the rubric, item by item.

Shared scoring model:
- Judge each rubric item met (1), partially met (0.5), or unmet (0).
- score = round(100 x items_met / items_assessed), clamped to 0-100. Higher is better.
- Every deduction must cite evidence: quote or name the artefact section. A deduction you cannot point at is not a deduction.
- A score of 100 is the correct outcome for a genuinely clean artefact — never manufacture deductions to look rigorous.

Rubric:
{rubric}

{kind_title} to judge:
<document>
{document}
</document>

Your entire reply must be exactly this block and nothing else:

EVAL_RESULT
eval_type: {eval_type}
items_assessed: <N>
items_met: <N, halves allowed>
score: <0-100 integer>
findings:
- <one line per deduction, naming the rubric item and citing the section; or "- none">
recommendation: <one paragraph, at most 100 words, or empty>
END_EVAL_RESULT
"""


def run_judge(artefact: str, document: str) -> dict:
    spec = ARTEFACTS[artefact]
    prompt = BRIEF_TEMPLATE.format(
        kind=spec["kind"],
        kind_title=spec["kind"].capitalize(),
        eval_type=spec["eval_type"],
        rubric=spec["rubric"](),
        document=document,
    )
    result = subprocess.run(
        ["claude", "-p", prompt, "--model", "opus", "--output-format", "text"],
        capture_output=True,
        text=True,
        timeout=JUDGE_TIMEOUT_SECONDS,
    )
    assert result.returncode == 0, f"claude CLI failed: {result.stderr[-2000:]}"
    return parse_eval_result(result.stdout)


def parse_eval_result(text: str) -> dict:
    m = re.search(r"EVAL_RESULT\n(.*?)END_EVAL_RESULT", text, re.DOTALL)
    assert m, f"no EVAL_RESULT block in judge output; got:\n{text[-2000:]}"
    block = m.group(1)

    def field(name: str) -> str:
        fm = re.search(rf"^{name}:\s*(.+)$", block, re.MULTILINE)
        assert fm, f"{name} missing from EVAL_RESULT block:\n{block}"
        return fm.group(1).strip()

    findings_part = block.split("findings:", 1)[1].split("recommendation:", 1)[0]
    findings = [f for f in re.findall(r"^- (.+)$", findings_part, re.MULTILINE) if f != "none"]
    return {
        "eval_type": field("eval_type"),
        "items_assessed": float(field("items_assessed")),
        "items_met": float(field("items_met")),
        "score": int(field("score")),
        "findings": findings,
    }


CASES = [
    ("storm", "storm-flawless.md", lambda score: score >= 95, "flawless storm must score >= 95"),
    ("storm", "storm-flawed.md", lambda score: score <= 60, "seeded-defect storm must score <= 60"),
    ("storm", "storm-legacy.md", lambda score: score <= 70, "legacy 5-section storm must score <= 70"),
    ("design", "design-flawless.md", lambda score: score >= 95, "flawless design must score >= 95"),
    ("design", "design-flawed.md", lambda score: score <= 60, "seeded-defect design must score <= 60"),
]


@pytest.mark.parametrize("artefact,fixture,band,description", CASES, ids=[c[1] for c in CASES])
def test_score_bands(artefact, fixture, band, description):
    result = run_judge(artefact, (FIXTURES / fixture).read_text())
    spec = ARTEFACTS[artefact]
    assert result["eval_type"] == spec["eval_type"]
    assert result["items_assessed"] == spec["items_assessed"], (
        f"rubric has {spec['items_assessed']} items; judge assessed {result['items_assessed']}"
    )
    assert band(result["score"]), (
        f"{description}; got {result['score']} with findings: {result['findings']}"
    )
    if fixture.endswith("-flawed.md"):
        manifest = json.loads((FIXTURES / fixture.replace(".md", ".manifest.json")).read_text())
        findings_text = " ".join(result["findings"]).lower()
        caught = [
            d["name"]
            for d in manifest["defects"]
            if any(k.lower() in findings_text for k in d["keywords"])
        ]
        missed = [d["name"] for d in manifest["defects"] if d["name"] not in caught]
        assert len(caught) >= manifest["min_caught"], (
            f"judge caught only {caught}; missed {missed}"
        )
