#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Inspect a tabular source cheaply, then extract only the columns you need.

Two modes, in the order they are meant to be used:

  peek     Print the shape of the source: sheet names, row count, column headers
           with their position, and how full each column is. Cell values are NOT
           printed by default, so a peek costs a few hundred tokens and reveals
           no personal data.

  extract  Write the named columns to a file. Only counts go to stdout, so the
           values never enter the conversation.

Supported: .csv, .tsv, .xlsx, and a .json wrapper holding one long text field
(the shape a document connector saves when a response is too large to inline).

Standard library only.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree

MAIN_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
ENCODINGS = ("utf-8-sig", "utf-8", "cp932")
PREVIEW_LIMIT = 60


class PeekError(Exception):
    """The source cannot be inspected safely."""


def _decode(raw: bytes) -> str:
    for encoding in ENCODINGS:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise PeekError("could not decode the file as utf-8, utf-8-sig or cp932")


def _read_delimited(path: Path) -> list[list[str]]:
    text = _decode(path.read_bytes())
    delimiter = "\t" if path.suffix.lower() in {".tsv", ".tab"} else ","
    return list(csv.reader(io.StringIO(text), delimiter=delimiter))


def _sheet_parts(archive: zipfile.ZipFile) -> dict[str, str]:
    """Map worksheet name to its part name inside the archive."""
    relations: dict[str, str] = {}
    with archive.open("xl/_rels/workbook.xml.rels") as handle:
        for node in ElementTree.parse(handle).getroot():
            relations[node.attrib["Id"]] = node.attrib["Target"].lstrip("/")
    parts: dict[str, str] = {}
    with archive.open("xl/workbook.xml") as handle:
        for node in ElementTree.parse(handle).getroot().iter(MAIN_NS + "sheet"):
            target = relations.get(node.attrib.get(REL_NS + "id", ""), "")
            if target and not target.startswith("xl/"):
                target = "xl/" + target
            if target:
                parts[node.attrib["name"]] = target
    return parts


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    values: list[str] = []
    with archive.open("xl/sharedStrings.xml") as handle:
        for item in ElementTree.parse(handle).getroot().iter(MAIN_NS + "si"):
            values.append("".join(t.text or "" for t in item.iter(MAIN_NS + "t")))
    return values


def _column_index(reference: str) -> int:
    """Turn a cell reference such as AB12 into a zero-based column index."""
    letters = re.match(r"[A-Z]+", reference or "")
    if not letters:
        return 0
    index = 0
    for char in letters.group(0):
        index = index * 26 + (ord(char) - 64)
    return index - 1


def _column_letter(index: int) -> str:
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _read_xlsx(path: Path, sheet: str | None) -> tuple[list[list[str]], list[str]]:
    with zipfile.ZipFile(path) as archive:
        parts = _sheet_parts(archive)
        if not parts:
            raise PeekError("no worksheet found in the workbook")
        names = list(parts)
        chosen = sheet or names[0]
        if chosen not in parts:
            raise PeekError("sheet not found: %s (available: %s)" % (chosen, ", ".join(names)))
        shared = _shared_strings(archive)
        # A worksheet omits empty rows, so a row's position in the XML is not its
        # spreadsheet row number. Place each row at the index its r attribute states
        # and pad the gaps, so --header-row N means spreadsheet row N.
        by_index: dict[int, list[str]] = {}
        cursor = 0
        with archive.open(parts[chosen]) as handle:
            for row_node in ElementTree.parse(handle).getroot().iter(MAIN_NS + "row"):
                reference = row_node.attrib.get("r", "")
                if reference.isdigit() and int(reference) > 0:
                    cursor = int(reference) - 1
                row: list[str] = []
                for cell in row_node.iter(MAIN_NS + "c"):
                    position = _column_index(cell.attrib.get("r", ""))
                    while len(row) < position:
                        row.append("")
                    kind = cell.attrib.get("t")
                    if kind == "inlineStr":
                        text = "".join(t.text or "" for t in cell.iter(MAIN_NS + "t"))
                    else:
                        node = cell.find(MAIN_NS + "v")
                        text = node.text if node is not None else None
                        if kind == "s" and text is not None:
                            try:
                                text = shared[int(text)]
                            except (ValueError, IndexError):
                                text = ""
                    row.append(text or "")
                by_index[cursor] = row
                cursor += 1
        rows = [by_index.get(i, []) for i in range(max(by_index) + 1)] if by_index else []
        return rows, names


def _unwrap_json(path: Path) -> str:
    payload = json.loads(_decode(path.read_bytes()))
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        candidates = [(len(v), k) for k, v in payload.items() if isinstance(v, str)]
        if candidates:
            return payload[max(candidates)[1]]
    raise PeekError("no long text field found in the JSON wrapper")


def load(path: Path, sheet: str | None) -> tuple[list[list[str]], list[str], str]:
    """Return (rows, sheet_names, kind)."""
    if not path.is_file():
        raise PeekError("not a file: %s" % path)
    suffix = path.suffix.lower()
    if suffix == ".xlsx":
        rows, names = _read_xlsx(path, sheet)
        return rows, names, "xlsx"
    if suffix in {".csv", ".tsv", ".tab"}:
        return _read_delimited(path), [], "delimited"
    if suffix == ".json":
        return [], [], "json-text"
    raise PeekError("unsupported extension: %s" % (suffix or "(none)"))


def _truncate(value: str) -> str:
    value = value.replace("\n", " ").strip()
    if len(value) <= PREVIEW_LIMIT:
        return value
    return value[: PREVIEW_LIMIT - 1] + "…"


def peek(path: Path, sheet: str | None, header_row: int, show_values: int) -> dict:
    rows, names, kind = load(path, sheet)
    if kind == "json-text":
        text = _unwrap_json(path)
        return {
            "source": str(path),
            "kind": kind,
            "note": "JSON wrapper holding one text field, not a parsed table",
            "characters": len(text),
            "lines": text.count("\n") + 1,
            "first_line_preview": _truncate(text.split("\n", 1)[0]),
            "next_step": "re-fetch this source with a range or column selection; a text "
            "rendering cannot be sliced by column reliably",
        }
    if not rows:
        raise PeekError("the sheet has no rows")
    if header_row < 1 or header_row > len(rows):
        raise PeekError("--header-row out of range: %d (rows: %d)" % (header_row, len(rows)))
    header = rows[header_row - 1]
    body = rows[header_row:]
    columns = []
    for index, name in enumerate(header):
        filled = sum(1 for row in body if index < len(row) and row[index].strip())
        column = {
            "index": index,
            "letter": _column_letter(index),
            "name": name.strip() or "(unnamed %s)" % _column_letter(index),
            "filled": filled,
            "fill_rate": round(filled / len(body), 3) if body else 0.0,
        }
        if show_values:
            column["samples"] = [
                _truncate(row[index]) for row in body[:show_values] if index < len(row)
            ]
        columns.append(column)
    stripped = [cell.strip() for cell in header]
    duplicates = sorted({cell for cell in stripped if cell and stripped.count(cell) > 1})
    return {
        "source": str(path),
        "kind": kind,
        "sheets": names,
        "sheet_used": sheet or (names[0] if names else None),
        "header_row": header_row,
        "data_rows": len(body),
        "duplicate_names": duplicates,
        "columns": columns,
    }


def _run_git(arguments: list[str], cwd: Path):
    """Run git and return the completed process, or None when git cannot answer."""
    executable = shutil.which("git")
    if not executable:
        return None
    try:
        return subprocess.run(
            [executable, "-C", str(cwd), *arguments],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def committable_destination(destination: Path) -> tuple[bool, str]:
    """Would git track a new file here?

    Asks git rather than looking for a .git entry: an abandoned .git directory is
    not a work tree, and treating one as a work tree refuses ordinary destinations
    such as the system temp directory.
    """
    anchor = destination.parent
    while not anchor.exists() and anchor != anchor.parent:
        anchor = anchor.parent
    top = _run_git(["rev-parse", "--show-toplevel"], anchor)
    if top is None:
        return False, "git is unavailable, so the destination could not be verified"
    if top.returncode != 0:
        return False, "not inside a git work tree"
    work_tree = top.stdout.strip()
    ignored = _run_git(["check-ignore", "-q", str(destination)], anchor)
    if ignored is not None and ignored.returncode == 0:
        return False, "inside %s but ignored by git" % work_tree
    return True, work_tree


def extract(
    path: Path,
    sheet: str | None,
    header_row: int,
    wanted: list[str],
    out: Path,
    allow_in_repo: bool = False,
) -> dict:
    rows, _, kind = load(path, sheet)
    if kind == "json-text":
        raise PeekError("cannot extract columns from a text rendering; re-fetch with a range")
    if not rows:
        raise PeekError("the sheet has no rows")
    if header_row < 1 or header_row > len(rows):
        raise PeekError("--header-row out of range: %d (rows: %d)" % (header_row, len(rows)))
    header = [cell.strip() for cell in rows[header_row - 1]]
    body = rows[header_row:]
    resolved: list[tuple[str, int]] = []
    for name in wanted:
        positions = [index for index, cell in enumerate(header) if cell == name]
        if not positions:
            raise PeekError("column not found: %s" % name)
        if len(positions) > 1:
            # Taking the first match would silently drop values held only by the
            # later duplicate, and the row count would still look plausible.
            letters = ", ".join(_column_letter(index) for index in positions)
            raise PeekError(
                "column name is not unique: %s appears at %s. Re-run with the "
                "intended column renamed or removed at the source" % (name, letters)
            )
        resolved.append((name, positions[0]))
    committable, detail = committable_destination(out.expanduser().resolve())
    if committable and not allow_in_repo:
        # Extracted columns often carry personal data. Writing them somewhere git
        # would track is one `git add -A` away from publishing them.
        raise PeekError(
            "git would track the destination (work tree: %s). Write outside it, add the "
            "path to .gitignore, or pass --allow-in-repo when you intend to keep it there"
            % detail
        )
    out.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([name for name, _ in resolved])
        for row in body:
            values = [row[i].strip() if i < len(row) else "" for _, i in resolved]
            if any(values):
                writer.writerow(values)
                written += 1
    first_index = resolved[0][1]
    first = [
        row[first_index].strip()
        for row in body
        if first_index < len(row) and row[first_index].strip()
    ]
    return {
        "out": str(out),
        "extracted": [name for name, _ in resolved],
        "data_rows_scanned": len(body),
        "rows_written": written,
        "first_column_non_empty": len(first),
        "first_column_unique": len(set(first)),
    }


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(
        description="Peek at a tabular source, then extract only the columns you need."
    )
    parser.add_argument("path", type=Path)
    parser.add_argument("--sheet", help="worksheet name (.xlsx); defaults to the first")
    parser.add_argument("--header-row", type=int, default=1)
    parser.add_argument(
        "--show-values",
        type=int,
        default=0,
        metavar="N",
        help="include N sample cell values per column. Off by default, because samples "
        "may carry personal data into the conversation",
    )
    parser.add_argument("--columns", help="comma-separated header names to extract; needs --out")
    parser.add_argument("--out", type=Path, help="destination CSV for --columns")
    parser.add_argument(
        "--allow-in-repo",
        action="store_true",
        help="permit --out inside a git work tree; use only when that path is ignored",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.columns:
            if not args.out:
                raise PeekError("--columns requires --out")
            names = [name.strip() for name in args.columns.split(",") if name.strip()]
            if not names:
                raise PeekError("--columns is empty")
            result = extract(
                args.path, args.sheet, args.header_row, names, args.out, args.allow_in_repo
            )
        else:
            result = peek(args.path, args.sheet, args.header_row, args.show_values)
    except (PeekError, zipfile.BadZipFile, json.JSONDecodeError, KeyError) as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if "out" in result:
        print("wrote %d row(s) to %s" % (result["rows_written"], result["out"]))
        print("columns: %s" % ", ".join(result["extracted"]))
        print(
            "scanned %d data row(s); first column non-empty %d, unique %d"
            % (
                result["data_rows_scanned"],
                result["first_column_non_empty"],
                result["first_column_unique"],
            )
        )
        return 0
    if result["kind"] == "json-text":
        print("%s  kind=%s" % (result["source"], result["kind"]))
        print("  %s" % result["note"])
        print("  characters=%d lines=%d" % (result["characters"], result["lines"]))
        print("  next step: %s" % result["next_step"])
        return 0
    print("%s  kind=%s" % (result["source"], result["kind"]))
    if result["sheets"]:
        print("  sheets (%d): %s" % (len(result["sheets"]), ", ".join(result["sheets"])))
        print("  sheet used: %s" % result["sheet_used"])
    print("  header row %d, data rows %d" % (result["header_row"], result["data_rows"]))
    if result.get("duplicate_names"):
        print(
            "  WARNING duplicate column name(s): %s — extraction refuses these"
            % ", ".join(result["duplicate_names"])
        )
    for column in result["columns"]:
        line = "  [%3s] %s  filled %d (%.0f%%)" % (
            column["letter"],
            column["name"],
            column["filled"],
            column["fill_rate"] * 100,
        )
        if column.get("samples"):
            line += "  e.g. " + " | ".join(column["samples"])
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
