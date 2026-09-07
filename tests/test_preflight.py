# -*- coding: utf-8 -*-
"""preflight の境界を確かめる回帰テスト（Python 標準ライブラリのみ）。

    python -m unittest discover -s tests -v
    python tests/test_preflight.py
    python tests/test_preflight.py --fixture-root <書き込み可能なディレクトリ>

各テストは使い捨ての git リポジトリを組み立て、そこへ合成ファイルを置いて preflight を実行する。
**このリポジトリの追跡ファイルには、検査対象になる危険な文字列を置かない。** 検出させたい文字列は
実行時に組み立てる（下の `windows_user_path` を参照）。実在の氏名・ID・秘密情報・端末パスは使わない。

## fixture の作成先

既定は標準の一時ディレクトリ。標準の一時ディレクトリへ書けない実行環境では、書き込み可能な場所を
次のいずれかで指定する。

- 環境変数 `PREFLIGHT_FIXTURE_ROOT`（`unittest discover` でも効く）
- `--fixture-root <dir>`（このファイルを直接実行するとき）

指定先が存在しない・書き込めない場合は、設定すべき内容を示して停止する。
生成物は**その実行が作った一意な子ディレクトリの中だけ**に作り、後片付けもその子だけを対象にする。
"""
from __future__ import annotations

import atexit
import io
import json
import pathlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import uuid
from unittest import mock

# Windows の既定コードページに関係なく、設定案内と unittest の失敗表示を読める形にする。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PREFLIGHT = os.path.join(REPO_ROOT, "skills", "git-publish", "scripts", "preflight.py")
POLICY = os.path.join(REPO_ROOT, "config", "policy.json")

SYNTHETIC_AUTHOR = "Synthetic Reviewer"
SYNTHETIC_EMAIL = "synthetic.reviewer@example.com"

from fixture_root import (FIXTURE_ROOT_ENV, make_unique_directory, remove_tree,
                          resolve_fixture_root, session_dir)


def conversational_phrase() -> str:
    """会話文脈（C01）に一致する語を実行時に組み立てる。

    リテラルで書くとこのテストファイル自身が C01 に一致する。`windows_user_path` と同じ理由で、
    検出させたい文字列は追跡ファイルへ置かない。
    """
    return chr(0x4ECA) + chr(0x56DE)


def windows_user_path(user: str) -> str:
    """`C:\\Users\\<user>\\work` 相当の文字列を実行時に組み立てる。

    リテラルで書くとこのテストファイル自身が L01 に一致してしまうため、分割して連結する。
    """
    return "C:" + chr(92) + "Users" + chr(92) + user + chr(92) + "work" + chr(92) + "note.md"


class Repo:
    """使い捨ての git リポジトリ。"""

    def __init__(self, author: str = SYNTHETIC_AUTHOR, email: str = SYNTHETIC_EMAIL):
        # git リポジトリとレシートは、この実行の fixture root 配下だけに作る。
        self.base = make_unique_directory(session_dir(), "case-")
        self.path = os.path.join(self.base, "repo")
        self.receipts = os.path.join(self.base, "receipts")
        os.makedirs(self.path)
        os.makedirs(self.receipts)
        self.git("init", "-q")
        self.git("config", "user.name", author)
        self.git("config", "user.email", email)
        # 検査対象になるリポジトリ形状の要件（README / .gitignore）は満たしておく。
        self.write("README.md", "# fixture\n\n合成データのみ。\n")
        self.write(".gitignore", "receipts/\n")
        # check_repo_shape は追跡ファイルを見るため、書くだけでなく stage する。
        self.stage("README.md", ".gitignore")

    def git(self, *args):
        return subprocess.run(
            ["git", "-C", self.path, *args],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )

    def write(self, rel: str, text: str):
        full = os.path.join(self.path, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)

    def stage(self, *rels):
        self.git("add", "--", *rels)

    def run(self, scope: str = "staged", policy: str | None = None):
        p = subprocess.run(
            [sys.executable, PREFLIGHT, "--repo", self.path, "--scope", scope,
             "--json", "--policy", policy or POLICY, "--receipt-dir", self.receipts],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        out = p.stdout.decode("utf-8", "replace")
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            raise AssertionError(
                "preflight が JSON を返さなかった\nexit=%d\nstdout=%s\nstderr=%s"
                % (p.returncode, out[:2000], p.stderr.decode("utf-8", "replace")[:2000])
            )
        return p.returncode, data

    def close(self):
        # 後片付けは、このテストが作った一意な子ディレクトリだけを対象にする。
        remove_tree(self.base)


def load_policy():
    """検査が実際に読む設定を、テストからも同じ経路で読む。"""
    root = pathlib.Path(__file__).resolve().parents[1]
    with (root / "config" / "policy.json").open(encoding="utf-8") as handle:
        return json.load(handle)


def rules(data, severity):
    return sorted({f["rule"] for f in data["findings"] if f["severity"] == severity})


class PreflightBoundaryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 作成先の問題は、検査ロジックの判定前に、対処が分かる形で報告する。
        # skip にはしない（設定すれば直るものを、通ったように見せない）。
        cls.fixture_root = session_dir()

    def setUp(self):
        self.assertTrue(os.path.exists(PREFLIGHT), "preflight.py が無い: %s" % PREFLIGHT)
        self.assertTrue(os.path.exists(POLICY), "policy.json が無い: %s" % POLICY)
        self.repo = Repo()
        self.addCleanup(self.repo.close)

    # --- 1. 組織アカウントは通り、合成の個人著者名は BLOCK -------------------
    def test_allowlisted_organization_account_passes(self):
        """許可リストの**仕組み**を検査する。同梱する設定の中身には依存しない。

        既定の設定は許可リストを空にしてある（利用者が自分の組織を足す）。
        同梱値を前提にすると、既定を空にした時点でこの検査が壊れる。
        """
        account = "example-org-" + uuid.uuid4().hex[:8]
        with open(POLICY, encoding="utf-8") as f:
            policy = json.load(f)
        policy["organization_accounts"] = [{
            "identifier": account,
            "kind": "github-organization",
            "reason": "テストが組み立てた合成の組織アカウント",
        }]
        path = os.path.join(self.repo.path, "policy-with-allowlist.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(policy, f, ensure_ascii=False)
        self.repo.write(
            "docs/ledger.md",
            "# 台帳\n\n所有は %s である。remote も同じ所有者を指す。\n" % account,
        )
        self.repo.stage("docs/ledger.md")
        code, data = self.repo.run(policy=path)
        self.assertNotIn("P04", rules(data, "BLOCK"),
                         "許可済みの組織アカウントが BLOCK された: %s" % rules(data, "BLOCK"))
        self.assertEqual(code, 0, "BLOCK: %s" % rules(data, "BLOCK"))

    def test_personal_author_name_blocks(self):
        # 著者名は git の設定から拾われる。本文に同じ名前があれば P04。
        self.repo.write(
            "docs/notes.md",
            "# 記録\n\n%s が確認した。\n" % SYNTHETIC_AUTHOR,
        )
        self.repo.stage("docs/notes.md")
        code, data = self.repo.run()
        self.assertIn("P04", rules(data, "BLOCK"),
                      "合成の個人著者名が BLOCK されなかった: %s" % data["findings"])
        self.assertEqual(code, 1)

    def test_reason_is_required_for_allowlist_entries(self):
        """理由の無いエントリを許さない（一般的な著者名の一括除外を防ぐ）。"""
        bad = os.path.join(self.repo.path, "bad_policy.json")
        with open(bad, "w", encoding="utf-8") as f:
            json.dump({"organization_accounts": [{"identifier": "someone"}],
                       "anonymized_path_placeholders": ["^<[^>]+>"],
                       "operational_log_paths": ["x"]}, f)
        p = subprocess.run(
            [sys.executable, PREFLIGHT, "--repo", self.repo.path, "--policy", bad,
             "--receipt-dir", self.repo.receipts],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        self.assertEqual(p.returncode, 2)
        self.assertIn("理由", p.stderr.decode("utf-8", "replace"))

    # --- 2. 匿名プレースホルダは通り、実在形式の絶対パスは BLOCK ------------
    def test_anonymized_placeholder_path_passes(self):
        self.repo.write(
            "docs/wiring.md",
            "# 配線\n\n生成ファイルの位置: `%s`\n" % windows_user_path("<利用者>"),
        )
        self.repo.stage("docs/wiring.md")
        code, data = self.repo.run()
        self.assertNotIn("L01", rules(data, "BLOCK"),
                         "匿名プレースホルダが BLOCK された: %s" % data["findings"])
        self.assertEqual(code, 0, "BLOCK: %s" % rules(data, "BLOCK"))

    def test_real_looking_absolute_path_blocks(self):
        self.repo.write(
            "docs/wiring.md",
            "# 配線\n\n生成ファイルの位置: `%s`\n" % windows_user_path("alice"),
        )
        self.repo.stage("docs/wiring.md")
        code, data = self.repo.run()
        self.assertIn("L01", rules(data, "BLOCK"),
                      "実在形式の絶対パスが BLOCK されなかった: %s" % data["findings"])
        self.assertEqual(code, 1)

    # --- 3. 会話文脈の規則に例外パスを設けない ----------------------------
    def test_conversational_wording_in_normal_doc_blocks(self):
        self.repo.write("docs/guide.md",
                        "# 手引き\n\n%s の対応で項目を追加した。\n" % conversational_phrase())
        self.repo.stage("docs/guide.md")
        code, data = self.repo.run()
        self.assertIn("C01", rules(data, "BLOCK"),
                      "通常文書の C01 が BLOCK されなかった: %s" % data["findings"])
        self.assertEqual(code, 1)

    def test_conversational_wording_blocks_under_every_path(self):
        """調整記録の置き場所にも例外を作らない。追跡しない場所に例外は要らない。"""
        for path in ("docs/guide.md", "docs/codex-briefs/ACTIVE.md", "notes/memo.md"):
            with self.subTest(path=path):
                self.repo.write(
                    path,
                    "# 文書\n\n## %s やらないこと\n\n- 何もしない\n" % conversational_phrase())
                self.repo.stage(path)
                code, data = self.repo.run()
                self.assertIn("C01", rules(data, "BLOCK"),
                              "%s の C01 が BLOCK されなかった: %s" % (path, data["findings"]))
                self.assertEqual(code, 1)

    def test_policy_declares_no_conversational_exemption(self):
        """設定側にも例外が残っていないこと。実装とデータの両方で確認する。"""
        declared = load_policy().get("conversational_rule_exempt_paths") or []
        self.assertEqual(list(declared), [],
                         "会話文脈の例外パスが宣言されている: %s" % declared)

    def test_secret_and_path_rules_still_apply_everywhere(self):
        """例外を外しても、秘密・個人情報・実在パスの検査は当然に続く。"""
        self.repo.write("docs/codex-briefs/ACTIVE.md",
                        "# 文書\n\n- 位置: `%s`\n" % windows_user_path("alice"))
        self.repo.stage("docs/codex-briefs/ACTIVE.md")
        code, data = self.repo.run()
        self.assertIn("L01", rules(data, "BLOCK"),
                      "実在パスが素通りした: %s" % data["findings"])
        self.assertEqual(code, 1)

    # --- 4. 運用ログは通り、backups/ の複製本体は BLOCK --------------------
    def test_operational_log_passes(self):
        self.repo.write("backups/BACKUP_LOG.md", "# 運用記録\n\n- 2026-09-02: 対象と戻し方\n")
        self.repo.write("backups/owner-assignment/BACKUP_LOG.md",
                        "# 運用記録（復旧領域別）\n\n- 2026-09-02: 対象と戻し方\n")
        self.repo.stage("backups/BACKUP_LOG.md", "backups/owner-assignment/BACKUP_LOG.md")
        code, data = self.repo.run()
        self.assertNotIn("T05", rules(data, "BLOCK"),
                         "復旧領域ごとの運用ログが BLOCK された: %s" % data["findings"])
        self.assertEqual(code, 0, "BLOCK: %s" % rules(data, "BLOCK"))

    def test_backup_body_blocks(self):
        self.repo.write("backups/owner-assignment/snapshot.xml", "<meta>合成データ</meta>\n")
        self.repo.stage("backups/owner-assignment/snapshot.xml")
        code, data = self.repo.run()
        self.assertIn("T05", rules(data, "BLOCK"),
                      "バックアップ本体が BLOCK されなかった: %s" % data["findings"])
        self.assertEqual(code, 1)

    # --- 追加: レシートと policy の扱い ------------------------------------
    def test_receipt_goes_to_the_given_directory(self):
        self.repo.write("docs/plain.md", "# 手引き\n\n事実だけを書く。\n")
        self.repo.stage("docs/plain.md")
        code, data = self.repo.run()
        self.assertEqual(code, 0, "BLOCK: %s" % rules(data, "BLOCK"))
        self.assertTrue(data["receipt"], "レシートが発行されていない")
        self.assertTrue(
            os.path.abspath(data["receipt"]).startswith(os.path.abspath(self.repo.receipts)),
            "レシートが指定ディレクトリ外に出た: %s" % data["receipt"],
        )

    def test_receipt_dir_defaults_to_the_policy_declaration(self):
        """場所の正本は policy。検査する側と読む側が別々に決めると食い違う。"""
        self.repo.write("docs/plain.md", "# 手引き\n\n事実だけを書く。\n")
        self.repo.stage("docs/plain.md")
        declared = os.path.join(self.repo.path, "declared-receipts")
        policy = json.loads(io.open(POLICY, encoding="utf-8").read())
        policy["receipt_root"] = declared
        custom = os.path.join(self.repo.path, "policy-with-root.json")
        io.open(custom, "w", encoding="utf-8").write(json.dumps(policy, ensure_ascii=False))
        p = subprocess.run(
            [sys.executable, PREFLIGHT, "--repo", self.repo.path, "--policy", custom, "--json"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace"))
        data = json.loads(p.stdout.decode("utf-8"))
        self.assertTrue(data["receipt"], "レシートが発行されていない")
        self.assertTrue(
            os.path.abspath(data["receipt"]).startswith(os.path.abspath(declared)),
            "policy の receipt_root が既定として使われていない: %s" % data["receipt"],
        )

    def test_explicit_receipt_dir_still_wins_over_the_policy(self):
        self.repo.write("docs/plain.md", "# 手引き\n\n事実だけを書く。\n")
        self.repo.stage("docs/plain.md")
        declared = os.path.join(self.repo.path, "declared-receipts")
        override = os.path.join(self.repo.path, "override-receipts")
        os.makedirs(override, exist_ok=True)
        policy = json.loads(io.open(POLICY, encoding="utf-8").read())
        policy["receipt_root"] = declared
        custom = os.path.join(self.repo.path, "policy-with-root.json")
        io.open(custom, "w", encoding="utf-8").write(json.dumps(policy, ensure_ascii=False))
        p = subprocess.run(
            [sys.executable, PREFLIGHT, "--repo", self.repo.path, "--policy", custom,
             "--receipt-dir", override, "--json"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace"))
        data = json.loads(p.stdout.decode("utf-8"))
        self.assertTrue(os.path.abspath(data["receipt"]).startswith(os.path.abspath(override)))
        self.assertFalse(os.path.exists(declared), "policy の場所へも書いてしまっている")

    def test_agent_home_is_rejected_as_receipt_dir(self):
        home_dir = os.path.join(os.path.expanduser("~"), ".claude", "cache", "x")
        p = subprocess.run(
            [sys.executable, PREFLIGHT, "--repo", self.repo.path, "--policy", POLICY,
             "--receipt-dir", home_dir],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        self.assertEqual(p.returncode, 2)
        self.assertIn("home", p.stderr.decode("utf-8", "replace"))

    def test_generated_paths_stay_under_the_fixture_root(self):
        """生成物が fixture root の外へ出ない。"""
        root = os.path.abspath(self.fixture_root)
        for path in (self.repo.base, self.repo.path, self.repo.receipts):
            self.assertTrue(
                os.path.abspath(path).startswith(root),
                "fixture root の外に作られた: %s (root=%s)" % (path, root),
            )

    def test_cleanup_removes_only_its_own_child(self):
        """後片付けは自分の子だけを消し、fixture root と session ディレクトリを残す。"""
        other = Repo()
        base = other.base
        self.assertTrue(os.path.isdir(base))
        other.close()
        self.assertFalse(os.path.exists(base), "作成した子ディレクトリが残っている: %s" % base)
        self.assertTrue(os.path.isdir(session_dir()), "session ディレクトリまで消している")
        self.assertTrue(os.path.isdir(self.repo.base), "他のテストの子まで消している")

    def test_unwritable_fixture_root_is_reported_with_guidance(self):
        """使えない作成先は、設定すべき内容を示して報告する。"""
        missing = os.path.join(self.repo.base, "no-such-directory")
        env = dict(os.environ)
        env[FIXTURE_ROOT_ENV] = missing
        code = (
            "import sys; sys.path.insert(0, %r); import test_preflight as t;\n"
            "\ntry:\n"
            "    t.resolve_fixture_root()\n"
            "except RuntimeError as e:\n"
            "    print(e); sys.exit(3)\n"
            "sys.exit(0)\n" % os.path.dirname(os.path.abspath(__file__))
        )
        p = subprocess.run([sys.executable, "-c", code], env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out = p.stdout.decode("utf-8", "replace")
        self.assertEqual(p.returncode, 3, "使えない作成先が報告されなかった: %s" % out)
        self.assertIn(FIXTURE_ROOT_ENV, out, "設定すべき環境変数が示されていない: %s" % out)
        self.assertIn("--fixture-root", out, "引数の指定方法が示されていない: %s" % out)

    def test_nested_fixture_permission_failure_is_reported_with_guidance(self):
        """root 直下だけ書けても case 用の子を作れない環境を、案内付きで止める。"""
        real_make = make_unique_directory

        def fail_only_nested(parent, prefix):
            if prefix == "preflight-probe-child-":
                raise PermissionError("synthetic nested denial")
            return real_make(parent, prefix)

        root = self.fixture_root
        before = set(os.listdir(root))
        with mock.patch.dict(os.environ, {FIXTURE_ROOT_ENV: root}):
            # ヘルパは fixture_root へ切り出したため、差し替え先もそちら。
            with mock.patch("fixture_root.make_unique_directory",
                            side_effect=fail_only_nested):
                with self.assertRaises(RuntimeError) as raised:
                    resolve_fixture_root()
        message = str(raised.exception)
        self.assertIn(FIXTURE_ROOT_ENV, message)
        self.assertIn("PermissionError", message)
        self.assertEqual(before, set(os.listdir(root)), "失敗した probe が fixture root に残った")

    def test_missing_policy_stops_the_check(self):
        p = subprocess.run(
            [sys.executable, PREFLIGHT, "--repo", self.repo.path,
             "--policy", os.path.join(self.repo.path, "no-such-policy.json"),
             "--receipt-dir", self.repo.receipts],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        self.assertEqual(p.returncode, 2, "policy が無いのに検査を続行した")


def _take_fixture_root_argument(argv):
    """`--fixture-root <dir>` を取り出して環境変数へ移す（unittest へは渡さない）。"""
    rest, i = [], 0
    while i < len(argv):
        a = argv[i]
        if a == "--fixture-root" and i + 1 < len(argv):
            os.environ[FIXTURE_ROOT_ENV] = argv[i + 1]
            i += 2
            continue
        if a.startswith("--fixture-root="):
            os.environ[FIXTURE_ROOT_ENV] = a.split("=", 1)[1]
            i += 1
            continue
        rest.append(a)
        i += 1
    return rest


if __name__ == "__main__":
    sys.argv = _take_fixture_root_argument(sys.argv)
    unittest.main(verbosity=2)
