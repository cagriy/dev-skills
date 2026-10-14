"""Feedback-bar injector for the dev-skills `feature-mockup` skill.

Inserts (or replaces) the feedback bar from `templates/mockup-feedback.html`
into one mockup page under `<feature_folder>/mockups/`. The bar lets the user
answer on the published artifact itself: it posts a comment and sends it to
Claude, whose first line follows the grammar the skill parses:

    Mockup feedback · <set-id> · <action>[ <option-id>]
    Note: <free text>                       (optional second line)

Stdlib only, deliberately: the skill runs this as the system `python3`, which
is not the project's uv-managed virtualenv.

Everything above `run` is pure; `run` reads the template and the page and
rewrites exactly that one page. `main` never raises and always exits 0 — any
problem degrades to one `mockup-feedback: skipped — …` line, and the skill
then collects that round's choice through `AskUserQuestion` instead.

Template contract (kept in lockstep with templates/mockup-feedback.html):

  * The bar sits between START and END marker comments; everything from START
    to END inclusive is copied into the page, the template's leading doc
    comment is not.
  * CONFIG_TOKEN appears once inside the block, as the body of a
    `<script type="application/json" id="mf-config">`; it is replaced by the
    JSON config built here, escaped so no label can close that script.
  * Every option the page shows carries one root element marked
    `data-mf-option="<id>"`; the bar anchors comments to it and outlines it
    when selected.

Page shapes (one decision set per round, never mixed):

  * review  — one page, one proposal (exactly 1 option)
  * compare — one page, 2–4 options side by side (every option marked here)
  * pick    — 2–4 pages, one option each (`--this` names the page's own option;
              only that one is marked on this page, the rest are siblings)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

STDLIB_MODULES = {"__future__", "argparse", "json", "re", "sys", "pathlib"}

STATUS_PREFIX = "mockup-feedback: "
START = "<!-- mockup-feedback:start -->"
END = "<!-- mockup-feedback:end -->"
CONFIG_TOKEN = "{{MOCKUP_FEEDBACK_CONFIG}}"
GRAMMAR_PREFIX = "Mockup feedback · "
ACTIONS = ("accept", "choose", "revise", "none", "alternatives")
MODES = ("review", "compare", "pick")
STATUSES = ("open", "accepted", "not-chosen", "closed")
ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_LABEL = 80


# --- Pure helpers ---------------------------------------------------------


def default_template() -> Path:
    return Path(__file__).resolve().parent.parent / "templates" / "mockup-feedback.html"


def parse_option(text: str) -> dict:
    """`inline-panel=Inline panel` → {"id": …, "label": …}."""
    if "=" not in text:
        raise ValueError(f"option must be id=label, got {text!r}")
    option_id, label = (part.strip() for part in text.split("=", 1))
    if not ID_PATTERN.match(option_id):
        raise ValueError(f"option id {option_id!r} must be lowercase-hyphenated")
    check_label(label, "option label")
    return {"id": option_id, "label": label}


def check_label(label: str, what: str) -> None:
    if not label or not label.strip():
        raise ValueError(f"{what} is empty")
    if len(label) > MAX_LABEL:
        raise ValueError(f"{what} is longer than {MAX_LABEL} characters")
    if re.search(r"[\x00-\x1f\x7f]", label):
        raise ValueError(f"{what} carries control characters")


def build_config(set_id, set_label, mode, options, this=None, status="open", chosen=None) -> dict:
    """Validate the arguments and return the bar's config. Raises ValueError."""
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}; use one of {', '.join(MODES)}")
    if not set_id or not ID_PATTERN.match(set_id):
        raise ValueError(f"set id {set_id!r} must be lowercase-hyphenated")
    check_label(set_label or "", "set label")
    parsed = [parse_option(o) for o in options or ()]
    ids = [o["id"] for o in parsed]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate option id")
    if mode == "review" and len(parsed) != 1:
        raise ValueError("review needs exactly 1 option")
    if mode in ("compare", "pick") and not 2 <= len(parsed) <= 4:
        raise ValueError(f"{mode} needs 2–4 options")
    if mode == "pick":
        if this not in ids:
            raise ValueError("pick needs --this naming one of its options")
    elif this is not None:
        raise ValueError("--this is for pick pages only")
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}; use one of {', '.join(STATUSES)}")
    if mode == "compare" and status == "accepted":
        if chosen not in ids:
            raise ValueError("compare accepted needs --chosen naming one of its options")
    elif chosen is not None:
        raise ValueError("--chosen is for an accepted compare page only")
    return {
        "set": set_id,
        "setLabel": set_label,
        "mode": mode,
        "options": parsed,
        "this": this,
        "status": status,
        "chosen": chosen,
    }


def marked_ids(config: dict) -> list:
    """The option roots this page itself must carry."""
    if config["mode"] == "pick":
        return [config["this"]]
    return [o["id"] for o in config["options"]]


def strip_block(page: str) -> str:
    """The page without its feedback block. Raises on a half-written block."""
    starts, ends = page.count(START), page.count(END)
    if starts == 0 and ends == 0:
        return page
    if starts != 1 or ends != 1 or page.index(START) > page.index(END):
        raise ValueError("page has a broken mockup-feedback block")
    before, rest = page.split(START, 1)
    after = rest.split(END, 1)[1]
    return before.rstrip("\n") + after.lstrip("\n")


def check_roots(page: str, config: dict) -> None:
    for option_id in marked_ids(config):
        count = len(re.findall(rf'data-mf-option="{re.escape(option_id)}"', page))
        if count == 0:
            raise ValueError(f'no element marked data-mf-option="{option_id}"')
        if count > 1:
            raise ValueError(f'more than one element marked data-mf-option="{option_id}"')


def config_json(config: dict) -> str:
    """JSON safe to sit inside a <script> element."""
    text = json.dumps(config, ensure_ascii=False, separators=(",", ":"))
    return text.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")


def render_block(template: str, config: dict) -> str:
    if template.count(START) != 1 or template.count(END) != 1:
        raise ValueError("template has no single mockup-feedback block")
    block = template[template.index(START):template.index(END) + len(END)]
    if block.count(CONFIG_TOKEN) != 1:
        raise ValueError("template block must carry the config token exactly once")
    return block.replace(CONFIG_TOKEN, config_json(config))


def inject(page: str, block: str) -> str:
    """Append the block after the mockup, replacing any earlier one."""
    return strip_block(page).rstrip("\n") + "\n\n" + block + "\n"


# --- The one impure entry point -------------------------------------------


def run(page, set_id, set_label, mode, options, this=None, status="open", chosen=None, template=None) -> str:
    """Inject the bar into `page`. Returns the one status line. Never raises."""
    try:
        page_path = Path(page)
        if not page_path.is_file():
            return STATUS_PREFIX + "skipped — page not found"
        template_path = Path(template) if template else default_template()
        if not template_path.is_file():
            return STATUS_PREFIX + "skipped — template not found"
        try:
            config = build_config(set_id, set_label, mode, options, this, status, chosen)
            text = page_path.read_text(encoding="utf-8")
            check_roots(strip_block(text), config)
            rendered = inject(text, render_block(template_path.read_text(encoding="utf-8"), config))
        except ValueError as exc:
            return STATUS_PREFIX + f"skipped — {exc}"
        page_path.write_text(rendered, encoding="utf-8")
        count = len(config["options"])
        noun = "option" if count == 1 else "options"
        return STATUS_PREFIX + f"{page_path.name} — {mode}, {count} {noun}, {status}"
    except Exception as exc:  # noqa: BLE001 — degrade, never fail the caller
        return STATUS_PREFIX + f"skipped — {type(exc).__name__}: {exc}"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Inject the feedback bar into one mockup page.")
    parser.add_argument("--page", required=True, help="the mockup HTML file to rewrite in place")
    parser.add_argument("--set", required=True, dest="set_id", help="decision-set id, e.g. v3-s1")
    parser.add_argument("--set-label", required=True, help="the set's name as the user reads it")
    parser.add_argument("--mode", required=True, help="review | compare | pick")
    parser.add_argument("--option", action="append", default=[], help="id=label; repeat, in set order")
    parser.add_argument("--this", default=None, help="pick only: the option this page shows")
    parser.add_argument("--status", default="open", help="open | accepted | not-chosen | closed")
    parser.add_argument("--chosen", default=None, help="compare only: the accepted option")
    parser.add_argument("--template", default=None, help="bar template (default: the plugin's own)")
    try:
        args = parser.parse_args(argv)
        line = run(
            args.page, args.set_id, args.set_label, args.mode, args.option,
            this=args.this, status=args.status, chosen=args.chosen, template=args.template,
        )
    except SystemExit:
        line = STATUS_PREFIX + "skipped — bad arguments"
    except Exception as exc:  # noqa: BLE001
        line = STATUS_PREFIX + f"skipped — {type(exc).__name__}: {exc}"
    print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
