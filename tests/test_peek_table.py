# -*- coding: utf-8 -*-
"""peek_table は形だけを出し、曖昧な列指定では fail-closed になる。"""
from __future__ import annotations

import csv
import importlib.util
import subprocess
import unittest
import zipfile
from pathlib import Path

from fixture_root import make_unique_directory, remove_tree, session_dir

MODULE_PATH = Path(__file__).parents[1] / "skills" / "tabular-read" / "scripts" / "peek_table.py"
SPEC = importlib.util.spec_from_file_location("peek_table", MODULE_PATH)
peek_table = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(peek_table)

SHEET_XML = (
    '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    "<sheetData>{rows}</sheetData></worksheet>"
)
WORKBOOK_XML = (
    '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
    '<sheets><sheet name="S" sheetId="1" r:id="rId1"/></sheets></workbook>'
)
RELS_XML = (
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>'
)


def write_csv(path: Path, rows: list[list[str]], encoding: str = "utf-8") -> Path:
    with path.open("w", encoding=encoding, newline="") as handle:
        csv.writer(handle).writerows(rows)
    return path


def write_xlsx(path: Path, rows_xml: str) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml", WORKBOOK_XML)
        archive.writestr("xl/_rels/workbook.xml.rels", RELS_XML)
        archive.writestr("xl/worksheets/sheet1.xml", SHEET_XML.format(rows=rows_xml))
    return path


def inline_row(index: int, values: list[str]) -> str:
    cells = "".join(
        '<c r="%s%d" t="inlineStr"><is><t>%s</t></is></c>'
        % (peek_table._column_letter(position), index, value)
        for position, value in enumerate(values)
    )
    return '<row r="%d">%s</row>' % (index, cells)


class PeekTableTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(make_unique_directory(session_dir(), "peek-table-"))
        self.addCleanup(remove_tree, self.root)

    def test_peek_reports_shape_without_cell_values(self):
        source = write_csv(
            self.root / "roster.csv",
            [["社員番号", "E-Mail(社用)"], ["E001", "addr-one"], ["E002", ""]],
        )
        result = peek_table.peek(source, None, 1, 0)
        self.assertEqual(result["data_rows"], 2)
        self.assertEqual([column["name"] for column in result["columns"]], ["社員番号", "E-Mail(社用)"])
        self.assertEqual(result["columns"][1]["filled"], 1)
        for column in result["columns"]:
            self.assertNotIn("samples", column)

    def test_peek_reads_cp932(self):
        source = write_csv(
            self.root / "cp932.csv", [["氏名", "所属"], ["山田", "システム"]], encoding="cp932"
        )
        result = peek_table.peek(source, None, 1, 0)
        self.assertEqual([column["name"] for column in result["columns"]], ["氏名", "所属"])

    def test_duplicate_column_name_is_refused_instead_of_silently_taking_the_first(self):
        source = write_csv(
            self.root / "dup.csv",
            [
                ["氏名", "mail", "mail"],
                ["A", "value-first", "value-second"],
                ["B", "", "value-only-second"],
            ],
        )
        self.assertEqual(peek_table.peek(source, None, 1, 0)["duplicate_names"], ["mail"])
        with self.assertRaises(peek_table.PeekError) as caught:
            peek_table.extract(source, None, 1, ["mail"], self.root / "out.csv")
        self.assertIn("not unique", str(caught.exception))
        self.assertFalse((self.root / "out.csv").exists())

    def test_extract_writes_only_the_named_column(self):
        source = write_csv(
            self.root / "roster.csv",
            [
                ["氏名", "E-Mail(社用)", "在籍状態"],
                ["山田", "addr-one", "在籍"],
                ["佐藤", "addr-two", "退職"],
            ],
        )
        out = self.root / "emails.csv"
        result = peek_table.extract(source, None, 1, ["E-Mail(社用)"], out)
        self.assertEqual(result["rows_written"], 2)
        self.assertEqual(result["first_column_unique"], 2)
        written = out.read_text(encoding="utf-8")
        self.assertIn("addr-one", written)
        self.assertNotIn("山田", written)
        self.assertNotIn("在籍", written)

    def test_destination_git_would_track_is_refused_by_default(self):
        source = write_csv(self.root / "roster.csv", [["mail"], ["addr-one"]])
        repo = self.root / "repo"
        repo.mkdir()
        if subprocess.run(
            ["git", "init", "-q", str(repo)], capture_output=True
        ).returncode != 0:
            self.skipTest("git is unavailable")
        out = repo / "sub" / "emails.csv"
        with self.assertRaises(peek_table.PeekError) as caught:
            peek_table.extract(source, None, 1, ["mail"], out)
        self.assertIn("work tree", str(caught.exception))
        self.assertFalse(out.exists())
        result = peek_table.extract(source, None, 1, ["mail"], out, allow_in_repo=True)
        self.assertEqual(result["rows_written"], 1)

    def test_ignored_destination_inside_a_repo_is_allowed(self):
        source = write_csv(self.root / "roster.csv", [["mail"], ["addr-one"]])
        repo = self.root / "repo2"
        repo.mkdir()
        if subprocess.run(
            ["git", "init", "-q", str(repo)], capture_output=True
        ).returncode != 0:
            self.skipTest("git is unavailable")
        (repo / ".gitignore").write_text("out/\n", encoding="utf-8")
        result = peek_table.extract(source, None, 1, ["mail"], repo / "out" / "e.csv")
        self.assertEqual(result["rows_written"], 1)

    def test_abandoned_git_directory_is_not_treated_as_a_work_tree(self):
        source = write_csv(self.root / "roster.csv", [["mail"], ["addr-one"]])
        fake = self.root / "fake"
        (fake / ".git").mkdir(parents=True)
        result = peek_table.extract(source, None, 1, ["mail"], fake / "e.csv")
        self.assertEqual(result["rows_written"], 1)

    def test_missing_column_fails_closed(self):
        source = write_csv(self.root / "roster.csv", [["氏名"], ["山田"]])
        with self.assertRaises(peek_table.PeekError):
            peek_table.extract(source, None, 1, ["mail"], self.root / "out.csv")

    def test_xlsx_row_positions_follow_the_spreadsheet_not_the_xml_order(self):
        source = write_xlsx(
            self.root / "offset.xlsx",
            inline_row(3, ["氏名", "mail"]) + inline_row(4, ["山田", "addr-one"]),
        )
        shifted = peek_table.peek(source, None, 1, 0)
        self.assertEqual([column["name"] for column in shifted["columns"]], [])
        result = peek_table.peek(source, None, 3, 0)
        self.assertEqual([column["name"] for column in result["columns"]], ["氏名", "mail"])
        self.assertEqual(result["data_rows"], 1)

    def test_xlsx_shared_and_ragged_rows(self):
        source = write_xlsx(
            self.root / "ragged.xlsx",
            inline_row(1, ["a", "b", "c"]) + inline_row(2, ["1"]),
        )
        result = peek_table.peek(source, None, 1, 0)
        self.assertEqual(result["columns"][0]["filled"], 1)
        self.assertEqual(result["columns"][2]["filled"], 0)

    def test_unknown_sheet_lists_available_names(self):
        source = write_xlsx(self.root / "book.xlsx", inline_row(1, ["a"]))
        with self.assertRaises(peek_table.PeekError) as caught:
            peek_table.peek(source, "missing", 1, 0)
        self.assertIn("S", str(caught.exception))

    def test_json_wrapper_is_reported_as_not_sliceable(self):
        source = self.root / "blob.json"
        source.write_text('{"fileContent": "line1\\nline2"}', encoding="utf-8")
        result = peek_table.peek(source, None, 1, 0)
        self.assertEqual(result["kind"], "json-text")
        self.assertEqual(result["lines"], 2)
        with self.assertRaises(peek_table.PeekError):
            peek_table.extract(source, None, 1, ["anything"], self.root / "out.csv")

    def test_unsupported_extension_fails_closed(self):
        source = self.root / "data.parquet"
        source.write_bytes(b"binary")
        with self.assertRaises(peek_table.PeekError):
            peek_table.peek(source, None, 1, 0)

    def test_header_row_out_of_range_fails_closed(self):
        source = write_csv(self.root / "roster.csv", [["氏名"], ["山田"]])
        with self.assertRaises(peek_table.PeekError):
            peek_table.peek(source, None, 9, 0)
        with self.assertRaises(peek_table.PeekError):
            peek_table.extract(source, None, 9, ["氏名"], self.root / "out.csv")


if __name__ == "__main__":
    unittest.main(verbosity=2)
