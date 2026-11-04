"""DESIGN.md region tool for the dev-skills `design-language-update` skill.

`DESIGN.md` at the project root holds one managed region between two marker
comments. The skill decides what goes in it; this script does every piece of
deterministic file work around it, so the safety-relevant parts are tested
code rather than prose:

    region --file F      print `design-language: region <sha256>` followed by
                         the region text, or `design-language: region none`
                         when F is missing or carries no region
    write --file F --region R --expect H|none
                         validate the region in file R against the schema and
                         splice it into F atomically, provided F's current
                         region hash is H (`none`: F has no region yet); prints
                         `design-language: <created|appended|written|unchanged> <sha256>`

Region contract (kept in lockstep with the skill):

  * Exactly one START … END pair, never nested. Anything else is malformed and
    refused with the defect named; the script never repairs a file.
  * The region hash is sha256 over the region text with the managed warning
    comment and the header table's `Updated` / `Specimen` rows removed, CRLF
    read as LF and the ends stripped — so a timestamp or a newly recorded
    artifact URL never counts as a content change.
  * `write` never changes a byte outside the markers, line endings included;
    the region follows the file's newline style. The script owns the managed
    warning comment (stripped from input, written as the region's first line)
    and the `Updated` row (stamped only when other content changed).
  * Every path the script writes or reads as `--file` must resolve inside the
    current working directory (the project root); read-only inputs may live
    anywhere.

Stdlib only, deliberately: the skill runs this as the system `python3`, which
is not the project's uv-managed virtualenv, and may be older than it — hence
future annotations and no `match`.

`main` never raises and always exits 0 — any problem degrades to one
`design-language: skipped — <reason>` line, and the skill reports
`status: skipped` instead of failing its caller.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import os
import re
import stat
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

STDLIB_MODULES = {
    "__future__", "argparse", "datetime", "functools", "hashlib", "os", "re", "stat", "sys", "tempfile", "pathlib",
}

STATUS_PREFIX = "design-language: "
START = "<!-- design-language:start -->"
END = "<!-- design-language:end -->"
MANAGED_COMMENT = (
    "<!-- Managed by /design-language-update. Edits inside this region are overwritten "
    "on the next run; write overrides above or below it. -->"
)
PREAMBLE = (
    "# DESIGN.md\n\nNotes outside the marked region are yours: /design-language-update reads them "
    "as decisions that outrank the code, and never edits them.\n\n"
)

MARKER_RE = re.compile(re.escape(START) + "|" + re.escape(END))
VOLATILE_ROWS = ("Updated", "Specimen")


class MarkerError(ValueError):
    """The file's region markers are malformed."""


class SchemaError(ValueError):
    """The region breaks the schema; the message names the section and defect."""


class OutsideProject(ValueError):
    """A confined path resolves outside the working directory."""

    def __init__(self) -> None:
        super().__init__("path outside the project")


# --- Pure helpers ---------------------------------------------------------


def find_region(text: str) -> tuple[int, int] | None:
    """(start, end) offsets of the text strictly between the markers, or None.

    Raises MarkerError on a start without an end, an end without a start,
    nested regions or more than one region.
    """
    depth, spans, opened = 0, [], 0
    for marker in MARKER_RE.finditer(text):
        if marker.group() == START:
            if depth:
                raise MarkerError("nested regions")
            depth, opened = 1, marker.end()
        else:
            if not depth:
                raise MarkerError("end marker without a start marker")
            depth = 0
            spans.append((opened, marker.start()))
    if depth:
        raise MarkerError("start marker without an end marker")
    if len(spans) > 1:
        raise MarkerError("more than one region")
    return spans[0] if spans else None


def region_text(text: str, span: tuple[int, int]) -> str:
    """The region's lines: what sits between the markers, minus the START line's own break."""
    inner = text[span[0]:span[1]]
    for newline in ("\r\n", "\n"):
        if inner.startswith(newline):
            return inner[len(newline):]
    return inner


def _cells(line: str) -> list:
    line = line.strip()
    line = line[1:] if line.startswith("|") else line
    line = line[:-1] if line.endswith("|") else line
    return [cell.strip() for cell in line.split("|")]


def normalise(region: str, volatile=VOLATILE_ROWS) -> str:
    """The region with no managed comment and no `volatile` header rows, LF, stripped.

    With the default rows this is what the hash covers; `write` compares with
    only `Updated` dropped, so a newly recorded specimen URL is still written.
    """
    lines, in_header = [], True
    for line in region.replace("\r\n", "\n").split("\n"):
        if line.startswith("### "):
            in_header = False
        is_volatile = in_header and line.lstrip().startswith("|") and _cells(line)[0] in volatile
        if line.strip() == MANAGED_COMMENT or is_volatile:
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def region_hash(region: str) -> str:
    return hashlib.sha256(normalise(region).encode("utf-8")).hexdigest()


def confined(path) -> Path:
    """`path` resolved, provided it lies inside the working directory."""
    resolved = Path(path).resolve()
    if not resolved.is_relative_to(Path(os.getcwd()).resolve()):
        raise OutsideProject()
    return resolved


def read(path: Path) -> str:
    """The file's text with its line endings untouched."""
    return path.read_bytes().decode("utf-8")


def atomic_write(path: Path, data: bytes) -> None:
    """Replace `path` through a temp file in its own directory, keeping an existing file's mode."""
    if path.exists():
        mode = stat.S_IMODE(path.stat().st_mode)
    else:
        umask = os.umask(0)
        os.umask(umask)
        mode = 0o666 & ~umask
    handle, temp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(data)
        os.chmod(temp, mode)
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


def skipped(reason: str) -> str:
    return STATUS_PREFIX + "skipped — " + " ".join(reason.split())


def degrades(command):
    """Turn any exception a subcommand raises into its one skipped line."""

    @functools.wraps(command)
    def guarded(*args, **kwargs) -> str:
        try:
            return command(*args, **kwargs)
        except SchemaError as exc:
            return skipped(f"schema: {exc}")
        except ValueError as exc:
            return skipped(str(exc))
        except Exception as exc:  # noqa: BLE001 — degrade, never fail the caller
            return skipped(f"{type(exc).__name__}: {exc}")

    return guarded


# --- Region schema ----------------------------------------------------------
#
# Every value the specimen applies to `style` is validated here, so nothing in
# the region can smuggle CSS (or markup) into the published page.


HEADER_RE = re.compile(r"^## Design language — (\S.*)$")
HEADINGS = tuple(
    "### " + title
    for title in (
        "Visual Theme & Atmosphere",
        "Color Palette & Roles",
        "Typography Rules",
        "Layout Principles",
        "Depth & Elevation",
        "Component Stylings",
        "Responsive Behavior",
        "Iconography & Motion",
        "Copy Tone",
        "Do's and Don'ts",
        "Decisions",
        "Drift",
    )
)
COLUMNS = {
    "header": ("Field", "Value"),
    "colours": ("Token", "Light", "Dark", "Role", "Group", "Source"),
    "type": ("Token", "Family", "Weight", "Size / line height", "Treatment", "Source"),
    "spacing": ("Spacing token", "Value", "Source"),
    "radius": ("Radius token", "Value", "Source"),
    "elevation": ("Token", "Value", "Use", "Source"),
    "components": ("Category", "Canonical", "Variants", "Tokens", "Source"),
    "decisions": ("#", "Decision", "By", "Date", "Status"),
}
HEADER_FIELDS = ("Classification", "Platforms", "Updated", "Specimen")
CLASSIFICATIONS = ("greenfield", "partial", "established")
GROUPS = ("brand", "surface", "text", "feedback", "other")
CATEGORIES = ("button", "input", "card", "table", "nav", "alert", "other")
DECISION_BY = ("user", "skill")
DECISION_STATUS_RE = re.compile(r"^(?:active|pending v\d+|superseded by \d+|drift)$")
SOURCE_TAG_RE = re.compile(
    r"^(?:code: (?!/)\S+:\d+"
    r"|mockup: (?!/)\S+"
    r"|user: (?:\d{4}-\d{2}-\d{2}|DESIGN\.md)"
    r"|user · pending v\d+"
    r"|skill: decision \d+)$"
)
NONE = "—"  # an empty cell: no dark value, no variants, no token pairs
EMPTY_RE = re.compile(r"^None recorded — \S")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_NUMBER = r"(?:\d+(?:\.\d+)?|\.\d+)"
_ARG = rf"-?{_NUMBER}(?:%|deg)?"
_HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
_COLOUR_FN_RE = re.compile(rf"^(?:rgba?|hsla?|oklch)\(\s*{_ARG}(?:(?:\s*[,/]\s*|\s+){_ARG}){{2,3}}\s*\)$")
_SIZE_RE = re.compile(rf"^{_NUMBER}(?:px|rem|em|%)$")
_UNITLESS_RE = re.compile(rf"^{_NUMBER}$")
_LENGTH_RE = re.compile(rf"^(?:-?{_NUMBER}(?:px|rem|em)|0)$")
_WEIGHT_RE = re.compile(r"^(?:[1-9]00|normal|bold)$")
_URL_RE = re.compile(r"""^https://[^\s"'<>]+$""")


def is_colour(value: str) -> bool:
    return bool(_HEX_RE.match(value) or _COLOUR_FN_RE.match(value))


def is_size(value: str) -> bool:
    return bool(_SIZE_RE.match(value))


def is_line_height(value: str) -> bool:
    return bool(_UNITLESS_RE.match(value)) or is_size(value)


def is_shadow(value: str) -> bool:
    """`none`, or layers of optional `inset`, 2–4 lengths and one colour."""
    if value == "none":
        return True
    for layer in re.split(r",(?![^()]*\))", value):
        parts = re.findall(r"[A-Za-z]+\([^()]*\)|\S+", layer)
        lengths = sum(1 for p in parts if _LENGTH_RE.match(p))
        colours = sum(1 for p in parts if is_colour(p))
        insets = parts.count("inset")
        if insets > 1 or colours != 1 or not 2 <= lengths <= 4 or lengths + colours + insets != len(parts):
            return False
    return True


def is_family(value: str) -> bool:
    return bool(value) and all(c.isalnum() or c in " -'\"," for c in value)


def is_weight(value: str) -> bool:
    return bool(_WEIGHT_RE.match(value))


def is_specimen_url(value: str) -> bool:
    return value == "none" or bool(_URL_RE.match(value))


def _require_exact(found, required, what, where="") -> None:
    prefix = f"{where}: " if where else ""
    for item in found:
        if item not in required:
            raise SchemaError(f"{prefix}unexpected {what} '{item}'")
    for item in required:
        if item not in found:
            raise SchemaError(f"{prefix}missing {what} '{item}'")
    if len(found) != len(required):
        raise SchemaError(f"{prefix}duplicate {what}")
    if list(found) != list(required):
        raise SchemaError(f"{prefix}{what}s out of order")


def _split_sections(text: str) -> list:
    """[(heading, body lines)] in order; the managed comment is dropped."""
    sections = []
    for line in text.replace("\r\n", "\n").split("\n"):
        if line.strip() == MANAGED_COMMENT:
            continue
        if re.match(r"#{1,6} ", line):
            sections.append((line.rstrip(), []))
        elif sections:
            sections[-1][1].append(line)
        elif line.strip():
            raise SchemaError("text before the header heading")
    return sections


def _blocks(title: str, lines: list) -> list:
    """A section body as ("table", header, rows), ("bullet", text) and ("text", line) blocks."""
    blocks, i = [], 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("|"):
            j = i
            while j < len(lines) and lines[j].strip().startswith("|"):
                j += 1
            table = [_cells(row) for row in lines[i:j]]
            if len(table) < 2 or not all(re.match(r"^:?-+:?$", cell) for cell in table[1]):
                raise SchemaError(f"{title}: table without a separator row")
            blocks.append(("table", table[0], table[2:]))
            i = j
            continue
        bullet = re.match(r"^[-*] +(.*)$", line)
        if bullet:
            blocks.append(("bullet", bullet.group(1).strip()))
        elif line:
            blocks.append(("text", line))
        i += 1
    return blocks


def _check_tag(tag: str, where: str) -> str:
    if not tag:
        raise SchemaError(f"{where}: untagged")
    if not SOURCE_TAG_RE.match(tag):
        raise SchemaError(f"{where}: bad source tag '{tag}'")
    return tag


def _only(title: str, blocks: list, *kinds) -> list:
    for block in blocks:
        if block[0] not in kinds:
            shown = " | ".join(block[1]) if block[0] == "table" else block[1]
            raise SchemaError(f"{title}: unexpected {'line' if block[0] == 'text' else block[0]} '{shown}'")
    return blocks


def _tagged(title: str, text: str) -> dict:
    """`<text> — <tag>` → {"text", "source"}."""
    if " — " not in text:
        raise SchemaError(f"{title}: untagged bullet '{text}'")
    body, tag = text.rsplit(" — ", 1)
    return {"text": body.strip(), "source": _check_tag(tag.strip(), f"{title}: bullet '{body.strip()}'")}


def _rows(title: str, header: list, rows: list, key: str) -> list:
    """Table rows as dicts keyed by column, each `Source` cell checked."""
    columns = COLUMNS[key]
    _require_exact(header, columns, "column", title)
    out = []
    for cells in rows:
        where = f"{title}: row '{cells[0]}'"
        if len(cells) != len(columns):
            raise SchemaError(f"{where} has {len(cells)} cells, expected {len(columns)}")
        row = dict(zip(columns, cells))
        if "Source" in row:
            _check_tag(row["Source"], where)
        out.append((where, row))
    return out


def _one_table(title: str, blocks: list, key: str) -> list:
    tables = _only(title, blocks, "table")
    if len(tables) != 1:
        raise SchemaError(f"{title}: expected one table, found {len(tables)}")
    return _rows(title, tables[0][1], tables[0][2], key)


def _value(where: str, row: dict, column: str, valid, what: str) -> str:
    if not valid(row[column]):
        raise SchemaError(f"{where}: bad {what} '{row[column]}' in {column}")
    return row[column]


def _list(cell: str) -> list:
    return [] if cell == NONE else [item.strip() for item in cell.split(",") if item.strip()]


def _header(lines: list) -> dict:
    title = "Design language header"
    blocks = _blocks(title, lines)
    if len(blocks) != 1 or blocks[0][0] != "table":
        raise SchemaError(f"{title}: expected one Field | Value table")
    rows = [row for _, row in _rows(title, *blocks[0][1:], "header")]
    _require_exact([row["Field"] for row in rows], HEADER_FIELDS, "row", title)
    fields = {row["Field"]: row["Value"] for row in rows}
    if fields["Classification"] not in CLASSIFICATIONS:
        raise SchemaError(f"{title}: bad classification '{fields['Classification']}'")
    platforms = _list(fields["Platforms"])
    if not platforms:
        raise SchemaError(f"{title}: Platforms is empty")
    if not fields["Updated"]:
        raise SchemaError(f"{title}: Updated is empty")
    if not is_specimen_url(fields["Specimen"]):
        raise SchemaError(f"{title}: bad specimen URL '{fields['Specimen']}'")
    return {
        "classification": fields["Classification"],
        "platforms": platforms,
        "updated": fields["Updated"],
        "specimen_url": None if fields["Specimen"] == "none" else fields["Specimen"],
    }


def _theme(title, blocks, data):
    lines = [text for _, text in _only(title, blocks, "text")]
    if not lines or not lines[-1].startswith("Source:"):
        raise SchemaError(f"{title}: untagged — end the paragraph with a 'Source: <tag>' line")
    if len(lines) < 2:
        raise SchemaError(f"{title}: no paragraph")
    data["theme"] = {"text": " ".join(lines[:-1]), "source": _check_tag(lines[-1][len("Source:"):].strip(), title)}


def _colours(title, blocks, data):
    for where, row in _one_table(title, blocks, "colours"):
        if row["Group"] not in GROUPS:
            raise SchemaError(f"{where}: unknown group '{row['Group']}'")
        dark = None if row["Dark"] == NONE else _value(where, row, "Dark", is_colour, "colour")
        data["colours"].append({
            "token": row["Token"], "light": _value(where, row, "Light", is_colour, "colour"), "dark": dark,
            "role": row["Role"], "group": row["Group"], "source": row["Source"],
        })


def _type(title, blocks, data):
    for where, row in _one_table(title, blocks, "type"):
        size, slash, line = (part.strip() for part in row["Size / line height"].partition("/"))
        if not slash:
            raise SchemaError(f"{where}: Size / line height must be '<size> / <line height>'")
        if not is_size(size):
            raise SchemaError(f"{where}: bad size '{size}' in Size / line height")
        if not is_line_height(line):
            raise SchemaError(f"{where}: bad line height '{line}'")
        data["type"].append({
            "token": row["Token"], "family": _value(where, row, "Family", is_family, "family"),
            "weight": _value(where, row, "Weight", is_weight, "weight"), "size": size, "line": line,
            "treatment": row["Treatment"], "source": row["Source"],
        })


def _layout(title, blocks, data):
    tables = {}
    for block in _only(title, blocks, "bullet", "table"):
        if block[0] == "bullet":
            data["layout"].append(_tagged(title, block[1]))
            continue
        key = {"Spacing token": "spacing", "Radius token": "radius"}.get(block[1][0] if block[1] else "")
        if key is None or key in tables:
            raise SchemaError(f"{title}: unexpected table '{' | '.join(block[1])}'")
        tables[key] = block
    for key, first in (("spacing", "Spacing token"), ("radius", "Radius token")):
        if key not in tables:
            raise SchemaError(f"{title}: missing the {first} table")
        for where, row in _rows(title, *tables[key][1:], key):
            data[key].append({
                "token": row[first], "value": _value(where, row, "Value", is_size, "size"), "source": row["Source"],
            })


def _elevation(title, blocks, data):
    for where, row in _one_table(title, blocks, "elevation"):
        data["elevation"].append({
            "token": row["Token"], "value": _value(where, row, "Value", is_shadow, "shadow"),
            "use": row["Use"], "source": row["Source"],
        })


def _components(title, blocks, data):
    for where, row in _one_table(title, blocks, "components"):
        if row["Category"] not in CATEGORIES:
            raise SchemaError(f"{where}: unknown category '{row['Category']}'")
        tokens = {}
        for pair in [] if row["Tokens"] == NONE else row["Tokens"].split(";"):
            key, eq, token = (part.strip() for part in pair.partition("="))
            if not (key and eq and token):
                raise SchemaError(f"{where}: bad token pair '{pair.strip()}' in Tokens")
            tokens[key] = token
        data["components"].append({
            "category": row["Category"], "canonical": row["Canonical"], "variants": _list(row["Variants"]),
            "tokens": tokens, "source": row["Source"],
        })


def _bullets(title, blocks, data):
    for _, text in _only(title, blocks, "bullet"):
        _tagged(title, text)


def _dos_donts(title, blocks, data):
    for _, text in _only(title, blocks, "bullet"):
        for prefix, key in (("Do:", "dos"), ("Don't:", "donts")):
            if text.startswith(prefix):
                data[key].append(_tagged(title, text[len(prefix):].strip()))
                break
        else:
            raise SchemaError(f"{title}: bullet without a 'Do:' or 'Don't:' prefix '{text}'")


def _decisions(title, blocks, data):
    for where, row in _one_table(title, blocks, "decisions"):
        if not row["#"].isdigit():
            raise SchemaError(f"{where}: bad decision number '{row['#']}'")
        if row["By"] not in DECISION_BY:
            raise SchemaError(f"{where}: By must be user or skill, got '{row['By']}'")
        if not DATE_RE.match(row["Date"]):
            raise SchemaError(f"{where}: bad date '{row['Date']}'")
        if not DECISION_STATUS_RE.match(row["Status"]):
            raise SchemaError(f"{where}: bad status '{row['Status']}'")
        data["decisions"].append({
            "n": int(row["#"]), "decision": row["Decision"], "by": row["By"], "date": row["Date"],
            "status": row["Status"],
        })


def _drift(title, blocks, data):
    if blocks != [("text", "None.")]:
        data["drift"] = [text for _, text in _only(title, blocks, "bullet")]


SECTION_PARSERS = dict(zip(HEADINGS, (
    _theme, _colours, _type, _layout, _elevation, _components,
    _bullets, _bullets, _bullets, _dos_donts, _decisions, _drift,
)))


def parse_region(text: str) -> dict:
    """Validate a region against the schema and return its specimen data.

    Raises SchemaError naming the heading, row or column at fault. A section
    holding only `None recorded — <reason>` contributes no entries; its line is
    kept under `empty`, keyed by section title, for the specimen's empty state.
    """
    sections = _split_sections(text)
    header = HEADER_RE.match(sections[0][0]) if sections else None
    if not header:
        raise SchemaError("missing heading '## Design language — <Project>'")
    _require_exact([heading for heading, _ in sections[1:]], HEADINGS, "heading")
    data = {
        "project": header.group(1).strip(),
        **_header(sections[0][1]),
        "theme": None, "dos": [], "donts": [], "colours": [], "type": [], "layout": [], "spacing": [],
        "radius": [], "elevation": [], "components": [], "decisions": [], "drift": [], "empty": {},
    }
    for heading, lines in sections[1:]:
        title = heading[len("### "):]
        content = [line.strip() for line in lines if line.strip()]
        if not content:
            raise SchemaError(f"{title}: no content — write 'None recorded — <reason>'")
        if len(content) == 1 and EMPTY_RE.match(content[0]):
            data["empty"][title] = content[0]
        else:
            SECTION_PARSERS[heading](title, _blocks(title, lines), data)
    statuses = [d["status"] for d in data["decisions"]]
    by = [d["by"] for d in data["decisions"]]
    data["counts"] = {
        "colours": len(data["colours"]),
        "type": len(data["type"]),
        "components": len(data["components"]),
        "decisions_user": by.count("user"),
        "decisions_skill": by.count("skill"),
        "pending": sum(1 for s in statuses if s.startswith("pending")),
        "drift": len(data["drift"]),
    }
    return data


# --- Subcommands ------------------------------------------------------------


@degrades
def cmd_region(file) -> str:
    """`region <sha256>` plus the region text, or `region none`."""
    path = confined(file)
    if not path.exists():
        return STATUS_PREFIX + "region none"
    text = read(path)
    span = find_region(text)
    if span is None:
        return STATUS_PREFIX + "region none"
    region = region_text(text, span)
    return f"{STATUS_PREFIX}region {region_hash(region)}\n{region}"


def _block(body: str, nl: str) -> str:
    """The managed region, markers and managed comment included, in newline style `nl`."""
    return nl.join((START, MANAGED_COMMENT, *body.split("\n"), END))


@degrades
def cmd_write(file, region, expect, now=None) -> str:
    """Splice the region in file `region` into `file`; `<outcome> <sha256>`."""
    path = confined(file)
    body = normalise(read(Path(region)), volatile=())
    if START in body or END in body:
        raise ValueError("the region input contains a design-language marker")
    parse_region(body)
    text = read(path) if path.exists() else None
    span = find_region(text) if text is not None else None
    old = region_text(text, span) if span else None
    if expect != (region_hash(old) if old is not None else "none"):
        raise ValueError("region changed since read")
    digest = region_hash(body)
    if old is not None and normalise(old, ("Updated",)) == normalise(body, ("Updated",)):
        return f"{STATUS_PREFIX}unchanged {digest}"
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M UTC")
    body = re.sub(r"(?m)^\|\s*Updated\s*\|.*$", f"| Updated | {stamp} |", body, count=1)
    if text is None:
        outcome, new = "created", PREAMBLE + _block(body, "\n") + "\n"
    else:
        nl = "\r\n" if "\r\n" in text else "\n"
        if span is None:
            gap = nl if text.endswith("\n") else nl + nl if text else ""
            outcome, new = "appended", text + gap + _block(body, nl) + nl
        else:
            before, after = text[:span[0] - len(START)], text[span[1] + len(END):]
            outcome, new = "written", before + _block(body, nl) + after
    atomic_write(path, new.encode("utf-8"))
    return f"{STATUS_PREFIX}{outcome} {digest}"


class _ArgError(Exception):
    """An argparse complaint, raised rather than exited on."""


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise _ArgError(message)


def _parse_args(argv):
    parser = _Parser(prog="design_language.py", add_help=False)
    commands = parser.add_subparsers(dest="command", required=True)
    region = commands.add_parser("region", add_help=False)
    region.add_argument("--file", required=True)
    write = commands.add_parser("write", add_help=False)
    write.add_argument("--file", required=True)
    write.add_argument("--region", required=True)
    write.add_argument("--expect", required=True)
    return parser.parse_args(argv)


COMMANDS = {
    "region": lambda args: cmd_region(args.file),
    "write": lambda args: cmd_write(args.file, args.region, args.expect),
}


def main(argv=None) -> int:
    try:
        args = _parse_args(argv)
        out = COMMANDS[args.command](args)
    except (_ArgError, SystemExit) as exc:
        out = skipped(f"bad arguments: {exc}")
    except Exception as exc:  # noqa: BLE001
        out = skipped(f"{type(exc).__name__}: {exc}")
    print(out, end="" if out.endswith("\n") else "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
