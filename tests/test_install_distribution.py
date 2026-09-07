# -*- coding: utf-8 -*-
"""インストーラが配る skill と、runtime ごとの除外の宣言を検査する。

skill を追加したときに配布対象へ入れ忘れる、あるいは runtime を分ける判断を
忘れる、という抜けを検出する。**インストーラを実行せずに、宣言だけを読む。**
実際にリンクが張られるかは環境に依存するため、ここでは扱わない。
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALLER = REPO_ROOT / "scripts" / "install.ps1"

SKILL_LIST = re.compile(
    r"foreach \(\$skillName in @\((.*?)\)\) \{", re.S)
EXCLUSION_BLOCK = re.compile(
    r"\$skillRuntimeExclusions = @\{(.*?)\n\}", re.S)
QUOTED = re.compile(r"'([^']+)'")


def installer_text() -> str:
    return INSTALLER.read_bytes().decode("utf-8-sig")


def distributed_skills() -> list[str]:
    match = SKILL_LIST.search(installer_text())
    assert match, "配布対象の一覧が見つからない"
    return QUOTED.findall(match.group(1))


def exclusions() -> dict[str, list[str]]:
    match = EXCLUSION_BLOCK.search(installer_text())
    assert match, "runtime ごとの除外の宣言が見つからない"
    found: dict[str, list[str]] = {}
    for line in match.group(1).splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        names = QUOTED.findall(key)
        if not names:
            continue
        found[names[0]] = QUOTED.findall(value)
    return found


class InstallerEncodingTest(unittest.TestCase):
    """`.ps1` は BOM が無いと、日本語環境の PowerShell が別のコードページと誤認する。"""

    def test_the_installer_keeps_its_byte_order_mark(self):
        self.assertEqual(INSTALLER.read_bytes()[:3], b"\xef\xbb\xbf",
                         "BOM が落ちている。テキスト編集で失われやすい")

    def test_line_endings_are_consistent(self):
        raw = INSTALLER.read_bytes()
        self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"),
                         "行末が混在している")


class DistributionDeclarationTest(unittest.TestCase):
    def test_every_skill_in_this_repository_is_distributed(self):
        """skill を足して配布対象へ入れ忘れると、ここで落ちる。"""
        present = {p.name for p in (REPO_ROOT / "skills").iterdir()
                   if p.is_dir() and (p / "SKILL.md").is_file()}
        declared = set(distributed_skills())
        self.assertEqual(present - declared, set(),
                         "配布対象に入っていない skill: %s" % sorted(present - declared))

    def test_every_distributed_skill_exists(self):
        for name in distributed_skills():
            with self.subTest(name=name):
                self.assertTrue((REPO_ROOT / "skills" / name / "SKILL.md").is_file(),
                                "配布対象に宣言されているが実体が無い")

    def test_both_runtimes_have_an_exclusion_entry(self):
        """除外が無い runtime も空の一覧を書く。書き忘れと「除外なし」を区別する。"""
        self.assertEqual(set(exclusions()), {"codex", "claude"})

    def test_excluded_skills_are_actually_distributed(self):
        """配布していないものを除外に書いても意味が無い。宣言のずれを検出する。"""
        declared = set(distributed_skills())
        for runtime, names in exclusions().items():
            for name in names:
                with self.subTest(runtime=runtime, name=name):
                    self.assertIn(name, declared,
                                  "配布対象でないものが除外に書かれている")

    def test_the_implementer_contract_is_not_distributed_to_the_design_runtime(self):
        """役割の分離を設定で表現する。両方へ置くと表現が消える。"""
        self.assertIn("codex-implement", exclusions()["codex"])
        self.assertNotIn("codex-implement", exclusions()["claude"])

    def test_no_skill_is_excluded_from_every_runtime(self):
        """すべての runtime から除外するなら、配布対象から外すべきである。"""
        runtimes = list(exclusions())
        for name in distributed_skills():
            excluded_from = [r for r in runtimes if name in exclusions()[r]]
            with self.subTest(name=name):
                self.assertNotEqual(len(excluded_from), len(runtimes),
                                    "どこへも配らない skill が配布対象に残っている")


if __name__ == "__main__":
    unittest.main()
