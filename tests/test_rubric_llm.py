"""Layer 2: golden-fixture judge tests for the storm_quality rubric.

Each fixture is a storm document with known ground truth. The shipped rubric is
extracted from evals-e2e-run/SKILL.md (so the test always judges with exactly
what the skill ships) and run through a headless `claude` judge. Assertions are
score bands, not exact values, to absorb judge nondeterminism; widen to
median-of-3 only if bands prove flaky in practice.

Excluded by default — run explicitly with `uv run pytest -m llm` (token cost).
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from helpers import storm_quality_rubric

FIXTURES = Path(__file__).resolve().parent / "fixtures"
JUDGE_TIMEOUT_SECONDS = 480

pytestmark = [
    pytest.mark.llm,
    pytest.mark.skipif(shutil.which("claude") is None, reason="claude CLI not available"),
]

BRIEF_TEMPLATE = """You are an evaluation judge scoring one artefact. Judge the storm document below against the rubric, item by item.

Shared scoring model:
- Judge each rubric item met (1), partially met (0.5), or unmet (0).
- score = round(100 x items_met / items_assessed), clamped to 0-100. Higher is better.
- Every deduction must cite evidence: quote or name the artefact section. A deduction you cannot point at is not a deduction.
- A score of 100 is the correct outcome for a genuinely clean artefact — never manufacture deductions to look rigorous.

Rubric:
{rubric}

Storm document to judge:
<document>
{document}
</document>

Your entire reply must be exactly this block and nothing else:

EVAL_RESULT
eval_type: storm_quality
items_assessed: <N>
items_met: <N, halves allowed>
score: <0-100 integer>
findings:
- <one line per deduction, naming the rubric item and citing the section; or "- none">
recommendation: <one paragraph, at most 100 words, or empty>
END_EVAL_RESULT
"""


def run_judge(document: str) -> dict:
    prompt = BRIEF_TEMPLATE.format(rubric=storm_quality_rubric(), document=document)
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
    ("flawless.md", lambda score: score >= 95, "flawless storm must score >= 95"),
    ("flawed.md", lambda score: score <= 60, "seeded-defect storm must score <= 60"),
    ("legacy.md", lambda score: score <= 70, "legacy 5-section storm must score <= 70"),
]


@pytest.mark.parametrize("fixture,band,description", CASES, ids=[c[0] for c in CASES])
def test_score_bands(fixture, band, description):
    result = run_judge((FIXTURES / fixture).read_text())
    assert result["eval_type"] == "storm_quality"
    assert result["items_assessed"] == 10, (
        f"rubric has 10 items; judge assessed {result['items_assessed']}"
    )
    assert band(result["score"]), (
        f"{description}; got {result['score']} with findings: {result['findings']}"
    )
    if fixture == "flawed.md":
        manifest = json.loads((FIXTURES / "flawed.manifest.json").read_text())
        findings_text = " ".join(result["findings"]).lower()
        caught = [
            d["name"]
            for d in manifest["defects"]
            if any(k.lower() in findings_text for k in d["keywords"])
        ]
        missed = [d["name"] for d in manifest["defects"] if d["name"] not in caught]
        assert len(caught) >= 4, f"judge caught only {caught}; missed {missed}"
