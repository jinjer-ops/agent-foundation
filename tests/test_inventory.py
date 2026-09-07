# -*- coding: utf-8 -*-
"""inventory は「書いてあるだけ」と「効いている」を区別する。"""
from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

from fixture_root import make_unique_directory, remove_tree, session_dir

MODULE_PATH = (
    Path(__file__).parents[1] / "skills" / "agent-config-inventory" / "scripts" / "inventory.py"
)
SPEC = importlib.util.spec_from_file_location("inventory", MODULE_PATH)
inventory = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(inventory)


def make_home(root: Path) -> Path:
    home = root / ".agent-home"
    for part in ("skills", "commands", "rules", "hooks", "projects/p/memory"):
        (home / part).mkdir(parents=True)
    (home / "skills" / "demo").mkdir()
    (home / "skills" / "demo" / "SKILL.md").write_text("# demo\n", encoding="utf-8")
    (home / "commands" / "legacy.md").write_text("# legacy\n", encoding="utf-8")
    (home / "rules" / "always.md").write_text("# always\n", encoding="utf-8")
    (home / "settings.json").write_text("{}", encoding="utf-8")
    return home


def write_settings(home: Path, payload: dict, name: str = "settings.json") -> None:
    (home / name).write_text(json.dumps(payload), encoding="utf-8")


def write_note(home: Path, name: str, body: str, kind: str = "feedback") -> Path:
    path = home / "projects" / "p" / "memory" / name
    path.write_text(
        "---\nname: %s\nmetadata:\n  type: %s\n---\n\n%s\n" % (name[:-3], kind, body),
        encoding="utf-8",
    )
    return path


class InventoryTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(make_unique_directory(session_dir(), "inventory-"))
        self.addCleanup(remove_tree, self.root)
        self.home = make_home(self.root)

    def report(self):
        return inventory.build_report(self.home, None, [])

    def test_counts_each_shape_separately(self):
        report = self.report()
        self.assertEqual(report["counts"]["skills"], 1)
        self.assertEqual(report["counts"]["commands"], 1)
        self.assertEqual(report["counts"]["rules"], 1)
        self.assertEqual(report["counts"]["hooks_registered"], 0)
        self.assertEqual(report["commands"], ["legacy.md"])

    def test_note_asserting_an_unregistered_hook_is_a_contradiction(self):
        (self.home / "hooks" / "gate.py").write_text("# gate\n", encoding="utf-8")
        write_note(self.home, "gate-note.md", "`hooks/gate.py` が commit を拒否する。")
        claims = self.report()["unsubstantiated_hook_claims"]
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0]["severity"], "contradiction")
        self.assertTrue(claims[0]["file_exists"])
        self.assertFalse(claims[0]["registered"])

    def test_document_that_discloses_the_hook_is_off_is_not_a_contradiction(self):
        (self.home / "hooks" / "gate.py").write_text("# gate\n", encoding="utf-8")
        write_note(
            self.home,
            "honest-note.md",
            "`hooks/gate.py` は commit を拒否する仕組みだが、このリポジトリでは有効にしていない。",
        )
        claims = self.report()["unsubstantiated_hook_claims"]
        self.assertEqual([claim["severity"] for claim in claims], ["mention"])

    def test_registered_hook_is_not_reported(self):
        (self.home / "hooks" / "gate.py").write_text("# gate\n", encoding="utf-8")
        write_note(self.home, "gate-note.md", "`hooks/gate.py` が commit を拒否する。")
        write_settings(
            self.home,
            {
                "hooks": {
                    "PreToolUse": [
                        {"matcher": "Bash", "hooks": [{"command": "python hooks/gate.py"}]}
                    ]
                }
            },
        )
        report = self.report()
        self.assertEqual(report["unsubstantiated_hook_claims"], [])
        self.assertEqual(report["counts"]["hooks_registered"], 1)

    def test_missing_hook_file_is_reported_too(self):
        write_note(self.home, "ghost.md", "`hooks/absent.py` がブロックする。")
        claims = self.report()["unsubstantiated_hook_claims"]
        self.assertEqual(claims[0]["state"], "file missing")

    def test_secret_shaped_entry_is_found_even_with_a_prefixed_name(self):
        # Built from parts so this test file holds no literal credential-shaped text.
        key = "SUPERSET_" + "PASS" + "WORD"
        rule = "Bash(%s=%s python run.py)" % (key, "z" * 12)
        write_settings(self.home, {"permissions": {"allow": ["Bash(ls:*)", rule]}})
        found = self.report()["secret_shaped_settings"]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["key"], key)
        self.assertEqual(found[0]["index"], 1)
        self.assertFalse(found[0]["value_shown"])

    def test_a_command_that_reads_from_a_secret_store_is_not_reported(self):
        # Naming a secret in order to fetch it is not embedding its value.
        write_settings(
            self.home,
            {
                "permissions": {
                    "allow": [
                        "PowerShell(gcloud secrets versions access latest --secret=app-password)",
                        "Bash(aws secretsmanager get-secret-value --secret-id prod/token)",
                    ]
                }
            },
        )
        self.assertEqual(self.report()["secret_shaped_settings"], [])

    def test_secret_report_never_carries_the_value(self):
        key = "TO" + "KEN"
        value = "q" * 16
        write_settings(
            self.home,
            {"permissions": {"allow": ["Bash(%s=%s curl example)" % (key, value)]}},
        )
        serialized = json.dumps(self.report(), ensure_ascii=False)
        self.assertIn("secret_shaped_settings", serialized)
        self.assertNotIn(value, serialized)

    def test_dead_path_in_a_note_is_reported_but_placeholders_are_not(self):
        write_note(
            self.home,
            "paths.md",
            "保存先は `C:/definitely/not/here/x.md`。雛形は `~/agent-home/work/{project}/`。",
        )
        dead = self.report()["dead_paths"]
        self.assertEqual([item["path"] for item in dead], ["C:/definitely/not/here/x.md"])

    def test_exit_code_is_one_only_for_contradictions_and_secrets(self):
        (self.home / "hooks" / "gate.py").write_text("# gate\n", encoding="utf-8")
        write_note(
            self.home, "honest.md", "`hooks/gate.py` は拒否するが、いまは無効。"
        )
        self.assertEqual(inventory.main(["--home", str(self.home)]), 0)
        write_note(self.home, "claiming.md", "`hooks/gate.py` が push を拒否する。")
        self.assertEqual(inventory.main(["--home", str(self.home)]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
