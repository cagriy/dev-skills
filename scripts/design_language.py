"""DESIGN.md region tool for the dev-skills `design-language-update` skill.

`DESIGN.md` at the project root holds one managed region between two marker
comments. The skill decides what goes in it; this script does every piece of
deterministic file work around it, so the safety-relevant parts are tested
code rather than prose:

    region --file F      print `design-language: region <sha256>` followed by
                         the region text, or `design-language: region none`
                         when F is missing or carries no region

Region contract (kept in lockstep with the skill):

  * Exactly one START … END pair, never nested. Anything else is malformed and
    refused with the defect named; the script never repairs a file.
  * The region hash is sha256 over the region text with the managed warning
    comment and the header table's `Updated` / `Specimen` rows removed, CRLF
    read as LF and the ends stripped — so a timestamp or a newly recorded
    artifact URL never counts as a content change.
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
import sys
from pathlib import Path

STDLIB_MODULES = {"__future__", "argparse", "functools", "hashlib", "os", "re", "sys", "pathlib"}

STATUS_PREFIX = "design-language: "
START = "<!-- design-language:start -->"
END = "<!-- design-language:end -->"
MANAGED_COMMENT = (
    "<!-- Managed by /design-language-update. Edits inside this region are overwritten "
    "on the next run; write overrides above or below it. -->"
)

MARKER_RE = re.compile(re.escape(START) + "|" + re.escape(END))
VOLATILE_ROW_RE = re.compile(r"^\|\s*(?:Updated|Specimen)\s*\|")


class MarkerError(ValueError):
    """The file's region markers are malformed."""


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


def normalise(region: str) -> str:
    """The region as hashed: no managed comment, no volatile header rows, LF, stripped."""
    lines, in_header = [], True
    for line in region.replace("\r\n", "\n").split("\n"):
        if line.startswith("### "):
            in_header = False
        if line.strip() == MANAGED_COMMENT or (in_header and VOLATILE_ROW_RE.match(line)):
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


def skipped(reason: str) -> str:
    return STATUS_PREFIX + "skipped — " + " ".join(reason.split())


def degrades(command):
    """Turn any exception a subcommand raises into its one skipped line."""

    @functools.wraps(command)
    def guarded(*args, **kwargs) -> str:
        try:
            return command(*args, **kwargs)
        except ValueError as exc:
            return skipped(str(exc))
        except Exception as exc:  # noqa: BLE001 — degrade, never fail the caller
            return skipped(f"{type(exc).__name__}: {exc}")

    return guarded


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
    return parser.parse_args(argv)


def main(argv=None) -> int:
    try:
        args = _parse_args(argv)
        out = cmd_region(args.file)
    except (_ArgError, SystemExit) as exc:
        out = skipped(f"bad arguments: {exc}")
    except Exception as exc:  # noqa: BLE001
        out = skipped(f"{type(exc).__name__}: {exc}")
    print(out, end="" if out.endswith("\n") else "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
