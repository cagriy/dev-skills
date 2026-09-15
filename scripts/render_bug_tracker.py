"""Bug-tracker renderer for the dev-skills bug workflow.

Regenerates `bugs/bugs-tracker.html` wholesale from `templates/feature-tracker.html`
plus the current filesystem: one expandable Issues card per bug folder under
`bugs/` (open) and `bugs/archive/` (closed), screenshots referenced by relative
path, status derived from folder location and never stored.

Stdlib only, deliberately: the `bug-tracker-render` skill runs this as the
system `python3`, which is not the project's uv-managed virtualenv.

Everything above `render` is pure; `render` reads the template and the bug
folders and writes exactly one file. `main` never raises and always exits 0 —
any problem degrades to one `bug-tracker-render: skipped — …` line so a
rendering failure can never fail the calling skill.

Template contract (kept in lockstep with templates/feature-tracker.html and
CLAUDE.md → "Tracker token substitution"):

  * `<body>` → `<body data-tracker-kind="bugs">` switches the page to the
    bug-tracker view (Issues tab only; stepper and feature tabs hidden by CSS).
  * Header tokens: `{{FEATURE_TITLE}}` → "Bug Tracker"; `{{FEATURE_VERSION}}`
    and `{{FEATURE_SLUG}}` → empty; `{{GENERATED_AT}}` → today's ISO date.
  * The twenty feature-panel tokens (FEATURE_PANEL_TOKENS) → empty. Those
    panels are hidden, but a literal `{{…}}` would still be in the file.
  * The Issues panel is a marker-delimited living region, not a token:
    `<!-- ISSUES_AT:START -->…<!-- ISSUES_AT:END -->` carries the
    "Updated <UTC>" chip, `ISSUES_OPEN` and `ISSUES_CLOSED` carry the cards
    (or the template's `<p class="empty">…</p>` placeholder when empty).
  * The template opens with an HTML doc comment legending every token by
    name; substitution is confined to the body so the legend survives.
  * Open/Closed counts are computed by the template's own JS from the
    `.issue` cards at load — never written here.
"""

from __future__ import annotations

import argparse
import html
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

STDLIB_MODULES = {
    "__future__", "argparse", "html", "os", "re", "sys", "dataclasses", "datetime", "pathlib",
}

TRACKER_RELATIVE = Path("bugs") / "bugs-tracker.html"
STATUS_PREFIX = "bug-tracker-render: "

FEATURE_PANEL_TOKENS = tuple(
    "{{%s_%s}}" % (prefix, suffix)
    for prefix in ("BRAINSTORMING", "DESIGN", "PLAN", "IMPLEMENTATION")
    for suffix in ("AT", "BULLETS", "DETAILS", "USAGE_CHIP", "USAGE")
)

REGIONS = ("AT", "OPEN", "CLOSED")
PLACEHOLDERS = {
    "OPEN": '<p class="empty">No open issues.</p>',
    "CLOSED": '<p class="empty">No closed issues.</p>',
}

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
SEVERITIES = ("low", "medium", "high", "critical")
FOLDER_PATTERN = re.compile(r"^bug-(\d+)-(.*)$")
HEADING_PATTERN = re.compile(r"^#\s+Bug\s+\d+\s*:\s*(.+?)\s*$", re.MULTILINE)
SEVERITY_PATTERN = re.compile(r"^\s*-?\s*\*\*Severity:\*\*\s*(\S+)", re.MULTILINE | re.IGNORECASE)
FILED_PATTERN = re.compile(r"^\s*-?\s*\*\*Filed:\*\*\s*(\S+)", re.MULTILINE | re.IGNORECASE)

# Sections rendered into the card, in this order. Expected behaviour and
# Steps to reproduce appear only when the report has real content.
OPTIONAL_SECTIONS = ("Expected behaviour", "Steps to reproduce")
PLACEHOLDER_TEXTS = {"_not specified._", "_none provided._", "not specified.", "none provided."}


@dataclass(frozen=True)
class Bug:
    number: int
    slug: str
    title: str
    severity: str
    filed: str
    sections: dict = field(default_factory=dict)
    images: tuple = ()


# --- Pure helpers ---------------------------------------------------------


def split_doc_comment(text: str) -> tuple[str, str]:
    """(leading doc comment, rest). The legend names every token literally."""
    opened = text.find("<!--")
    if opened == -1:
        return "", text
    closed = text.find("-->", opened)
    if closed == -1:
        return "", text
    end = closed + len("-->")
    return text[:end], text[end:]


def find_repo_root(start) -> Path | None:
    """The nearest ancestor (inclusive) holding a `.git` entry, or None."""
    here = Path(start).resolve()
    for candidate in (here, *here.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def default_template() -> Path:
    return Path(__file__).resolve().parent.parent / "templates" / "feature-tracker.html"


def parse_sections(text: str) -> dict:
    """`## Heading` → body text, in document order. Text before the first `##` is dropped."""
    sections: dict = {}
    current = None
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    return {name: "\n".join(lines).strip() for name, lines in sections.items()}


def strip_footer(body: str) -> str:
    """Drop the `---` + "Filed via …" footer that ends every report."""
    cut = body.rfind("\n---")
    if cut != -1 and "Filed via" in body[cut:]:
        return body[:cut].rstrip()
    return body


def _inline(text: str) -> str:
    """Escape, then apply the two inline forms the reports use: **bold** and `code`."""
    escaped = html.escape(text, quote=False)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    return escaped


def markdown_to_html(text: str) -> str:
    """The subset of Markdown a bug report uses, as HTML.

    Paragraphs, `- ` bullets, `1. ` numbered lists, `**bold**`, `` `code` ``.
    Image lines are dropped — screenshots render from the folder listing, not
    from the report text. Everything else is escaped as text.
    """
    blocks: list[str] = []
    paragraph: list[str] = []
    items: list[str] = []
    list_tag = None

    def flush_paragraph():
        if paragraph:
            blocks.append("<p>" + _inline(" ".join(paragraph)) + "</p>")
            paragraph.clear()

    def flush_list():
        nonlocal list_tag
        if items:
            blocks.append(f"<{list_tag}>" + "".join(f"<li>{_inline(i)}</li>" for i in items) + f"</{list_tag}>")
            items.clear()
        list_tag = None

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            flush_paragraph()
            flush_list()
            continue
        if re.match(r"^!\[[^\]]*\]\([^)]*\)$", line):
            continue
        bullet = re.match(r"^[-*]\s+(.*)$", line)
        numbered = re.match(r"^\d+[.)]\s+(.*)$", line)
        if bullet or numbered:
            flush_paragraph()
            tag = "ul" if bullet else "ol"
            if list_tag and list_tag != tag:
                flush_list()
            list_tag = tag
            items.append((bullet or numbered).group(1))
            continue
        flush_list()
        paragraph.append(line)
    flush_paragraph()
    flush_list()
    return "".join(blocks)


def is_placeholder(body: str) -> bool:
    return not body.strip() or body.strip().lower() in PLACEHOLDER_TEXTS


def parse_bug(folder: Path) -> Bug:
    """Read a bug folder. A missing or malformed report degrades to a minimal card."""
    match = FOLDER_PATTERN.match(folder.name)
    number = int(match.group(1)) if match else 0
    slug = match.group(2) if match else folder.name
    report = folder / f"{folder.name}.md"
    if not report.exists():
        candidates = sorted(p for p in folder.glob("bug-*.md"))
        report = candidates[0] if candidates else None
    text = ""
    if report is not None:
        try:
            text = report.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
    heading = HEADING_PATTERN.search(text)
    title = heading.group(1) if heading else slug.replace("-", " ")
    sev = SEVERITY_PATTERN.search(text)
    severity = sev.group(1).strip(" ,.;—-").lower() if sev else "unknown"
    if severity not in SEVERITIES:
        severity = "unknown"
    filed = FILED_PATTERN.search(text)
    images = tuple(
        sorted(p.name for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES)
    )
    return Bug(
        number=number,
        slug=slug,
        title=title,
        severity=severity,
        filed=filed.group(1) if filed else "",
        sections=parse_sections(strip_footer(text)),
        images=images,
    )


def render_card(bug: Bug, status: str, src_prefix: str) -> str:
    """One `<details class="issue">` card. `src_prefix` is relative to bugs/."""
    parts = [
        f'<details class="issue" data-status="{status}">',
        '  <summary class="issue-summary">',
        f'    <span class="issue-number">#{bug.number}</span>',
        f'    <span class="issue-title">{html.escape(bug.title, quote=False)}</span>',
        f'    <span class="issue-sev sev-{bug.severity}">{bug.severity}</span>',
        f'    <span class="issue-date">{html.escape(bug.filed, quote=False)}</span>',
        "  </summary>",
        '  <div class="issue-body prose">',
    ]
    description = bug.sections.get("Description", "")
    parts.append("    <h3>Description</h3>")
    parts.append("    " + (markdown_to_html(description) or "<p></p>"))
    for name in OPTIONAL_SECTIONS:
        body = bug.sections.get(name, "")
        if not is_placeholder(body):
            parts.append(f"    <h3>{name}</h3>")
            parts.append("    " + markdown_to_html(body))
    if bug.images:
        parts.append("    <h3>Screenshots</h3>")
        for name in bug.images:
            src = html.escape(f"{src_prefix}{bug.number}-{bug.slug}/{name}", quote=True)
            parts.append(f'    <img src="{src}" alt="{html.escape(name, quote=True)}" />')
    triage = bug.sections.get("Triage", "")
    if triage.strip():
        parts.append("    <h3>Triage</h3>")
        parts.append("    " + markdown_to_html(triage))
    resolution = bug.sections.get("Resolution", "")
    if resolution.strip():
        parts.append("    <h3>Resolution</h3>")
        parts.append("    " + markdown_to_html(resolution))
    parts.append("  </div>")
    parts.append("</details>")
    return "\n".join(parts)


def bug_folders(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    folders = [p for p in root.iterdir() if p.is_dir() and FOLDER_PATTERN.match(p.name)]
    return sorted(folders, key=lambda p: int(FOLDER_PATTERN.match(p.name).group(1)), reverse=True)


def replace_region(text: str, name: str, content: str) -> str:
    """Replace what sits between the ISSUES_<name> markers, keeping the markers."""
    pattern = re.compile(f"(<!-- ISSUES_{name}:START -->).*?(<!-- ISSUES_{name}:END -->)", re.DOTALL)
    if not pattern.search(text):
        raise ValueError(f"template has no ISSUES_{name} markers")
    return pattern.sub(lambda m: m.group(1) + content + m.group(2), text, count=1)


def _header_tokens(text: str, today: str) -> str:
    return (
        text.replace("{{FEATURE_TITLE}}", "Bug Tracker")
        .replace("{{FEATURE_VERSION}}", "")
        .replace("{{FEATURE_SLUG}}", "")
        .replace("{{GENERATED_AT}}", today)
    )


def render_html(template: str, open_bugs: list[Bug], closed_bugs: list[Bug], now: str, today: str) -> str:
    legend, body = split_doc_comment(template)
    # `<title>{{FEATURE_TITLE}}</title>` sits above the doc comment, so the
    # header tokens are applied on both sides of it; the comment itself is
    # left alone so the legend keeps every token name literally.
    comment_at = legend.find("<!--")
    pre, comment = (legend[:comment_at], legend[comment_at:]) if comment_at != -1 else (legend, "")
    pre = _header_tokens(pre, today)
    legend = pre + comment
    for name in REGIONS:
        if f"<!-- ISSUES_{name}:START -->" not in body:
            raise ValueError(f"template has no ISSUES_{name} markers")
    if body.count("<body>") != 1:
        raise ValueError("template must contain exactly one <body> tag")
    body = body.replace("<body>", '<body data-tracker-kind="bugs">')
    body = _header_tokens(body, today)
    for token in FEATURE_PANEL_TOKENS:
        body = body.replace(token, "")
    open_cards = "\n".join(render_card(b, "open", "bug-") for b in open_bugs)
    closed_cards = "\n".join(render_card(b, "closed", "archive/bug-") for b in closed_bugs)
    body = replace_region(body, "AT", f"Updated {now}")
    body = replace_region(body, "OPEN", "\n" + open_cards + "\n" if open_cards else "\n" + PLACEHOLDERS["OPEN"] + "\n")
    body = replace_region(body, "CLOSED", "\n" + closed_cards + "\n" if closed_cards else "\n" + PLACEHOLDERS["CLOSED"] + "\n")
    return legend + body


# --- The one impure entry point -------------------------------------------


def render(start, template=None, now: str | None = None) -> str:
    """Regenerate bugs/bugs-tracker.html for the repo containing `start`.

    Returns the one status line the calling skill relays. Never raises.
    """
    try:
        root = find_repo_root(start)
        if root is None:
            return STATUS_PREFIX + "skipped — not in a git work tree"
        template_path = Path(template) if template else default_template()
        if not template_path.is_file():
            return STATUS_PREFIX + "skipped — template not found"
        template_text = template_path.read_text(encoding="utf-8")
        moment = now or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        today = moment[:10]
        open_bugs = [parse_bug(f) for f in bug_folders(root / "bugs")]
        closed_bugs = [parse_bug(f) for f in bug_folders(root / "bugs" / "archive")]
        try:
            rendered = render_html(template_text, open_bugs, closed_bugs, moment, today)
        except ValueError as exc:
            return STATUS_PREFIX + f"skipped — {exc}"
        target = root / TRACKER_RELATIVE
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8")
        return STATUS_PREFIX + f"{TRACKER_RELATIVE.as_posix()} updated — {len(open_bugs)} open, {len(closed_bugs)} closed"
    except Exception as exc:  # noqa: BLE001 — degrade, never fail the caller
        return STATUS_PREFIX + f"skipped — {type(exc).__name__}: {exc}"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Regenerate bugs/bugs-tracker.html from the bug folders.")
    parser.add_argument("--repo", default=os.getcwd(), help="any path inside the target git work tree (default: cwd)")
    parser.add_argument("--template", default=None, help="tracker template (default: the plugin's own)")
    parser.add_argument("--now", default=None, help=argparse.SUPPRESS)
    try:
        args = parser.parse_args(argv)
        line = render(args.repo, template=args.template, now=args.now)
    except SystemExit:
        line = STATUS_PREFIX + "skipped — bad arguments"
    except Exception as exc:  # noqa: BLE001
        line = STATUS_PREFIX + f"skipped — {type(exc).__name__}: {exc}"
    print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
