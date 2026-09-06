#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""共有リポジトリへ入れる前の機械検査（preflight）と検査レシートの発行。

ルールの正本は、共通運用ルールを定める索引リポジトリの `CONVENTIONS.md` である。
本スクリプトはその実装であり、正本ではない。**組織固有の判断（許容する組織アカウント、
匿名化プレースホルダ、ブリーフのパス、運用ログのパス）は本リポジトリの policy configuration
（既定 `config/policy.json`）に置く。** スクリプト本体に組織名・URL・端末パスを直書きしない。

判定を変えるときの順序は、①索引リポジトリの `CONVENTIONS.md` を更新する
②本リポジトリの policy configuration を更新する ③必要ならスクリプトを更新する、である。

使い方:
  python preflight.py --repo <repo>                        # index（stage 済み）を検査
  python preflight.py --repo <repo> --scope all            # 追跡ファイル全体を検査（初回公開時）
  python preflight.py --repo <repo> --json                 # 機械可読出力
  python preflight.py --repo <repo> --receipt-dir <dir>    # レシートの出力先（既定は policy の receipt_root）
  python preflight.py --repo <repo> --policy <file>        # policy configuration の明示指定
  python preflight.py --repo <repo> --force --reason "…"   # BLOCK を承知で通す（理由を記録）

終了コード: 0 = BLOCK なし（レシート発行） / 1 = BLOCK あり（レシート未発行） / 2 = 実行エラー

行末に `git-publish:allow` を書いた行は検査対象から外れる（抑制件数はレポートに出る）。
レシートの出力先は policy configuration の `receipt_root` が正本（未宣言なら一時ディレクトリ）。
これを読む PreToolUse ゲートと同じ宣言を使う。エージェントの home へは書き込まない。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

MAX_FILES = 400
LARGE_FILE_BYTES = 5 * 1024 * 1024
DATA_FILE_BYTES = 50 * 1024
SUPPRESS_MARK = "git-publish:allow"

# policy が receipt_root を宣言していないときの退避先。エージェントの home へは書き込まない。
DEFAULT_RECEIPT_ROOT = os.path.join(tempfile.gettempdir(), "agent-preflight-receipts")

# policy configuration（組織固有の判断）。スクリプトからの相対で解決する。
BUNDLED_POLICY = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "config", "policy.json",
)
# 配備された複製は正本リポジトリの外に置かれるため、相対解決では policy に届かない。
# ゲートと同じ環境変数を見て、両者が同じ policy を読む。
POLICY_ENV = "GIT_PUBLISH_POLICY"


def default_policy():
    if os.path.isfile(BUNDLED_POLICY):
        return BUNDLED_POLICY
    declared = os.environ.get(POLICY_ENV, "").strip().strip("\"'")
    return os.path.expanduser(declared) if declared else BUNDLED_POLICY

# ---------------------------------------------------------------- git helpers


def git(repo, *args, binary=False):
    p = subprocess.run(
        ["git", "-c", "core.quotepath=false", "-C", repo, *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if binary:
        return p.returncode, p.stdout, p.stderr.decode("utf-8", "replace")
    return (
        p.returncode,
        p.stdout.decode("utf-8", "replace"),
        p.stderr.decode("utf-8", "replace"),
    )


def repo_root(path):
    rc, out, _ = git(path, "rev-parse", "--show-toplevel")
    return out.strip() if rc == 0 else None


def read_blobs(repo, specs):
    """`git cat-file --batch` でまとめて blob を読む。戻り値は spec -> bytes|None。"""
    if not specs:
        return {}
    p = subprocess.run(
        ["git", "-C", repo, "cat-file", "--batch"],
        input=("\n".join(specs) + "\n").encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    out, res, i = p.stdout, {}, 0
    for spec in specs:
        nl = out.find(b"\n", i)
        if nl < 0:
            res[spec] = None
            continue
        header = out[i:nl].decode("utf-8", "replace").split(" ")
        i = nl + 1
        if len(header) >= 3 and header[-2] in ("blob", "tree", "commit", "tag"):
            size = int(header[-1])
            res[spec] = out[i : i + size] if header[-2] == "blob" else None
            i += size + 1
        else:
            res[spec] = None  # missing / ambiguous
    return res


# ------------------------------------------------------ policy configuration


class PolicyError(Exception):
    """policy configuration が無い / 壊れている / 理由の記載が無い。"""


def load_policy(path):
    """組織固有の判断を読む。**無い・壊れている場合は検査を続行しない（fail-closed）。**"""
    if not os.path.exists(path):
        raise PolicyError(f"policy configuration が無い: {path}")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        raise PolicyError(f"policy configuration を読めない: {path}: {e}")

    accounts = data.get("organization_accounts")
    if not isinstance(accounts, list):
        raise PolicyError("organization_accounts が配列でない")
    allow, reasons = set(), {}
    for i, entry in enumerate(accounts):
        if not isinstance(entry, dict):
            raise PolicyError(f"organization_accounts[{i}] がオブジェクトでない")
        ident = (entry.get("identifier") or "").strip()
        reason = (entry.get("reason") or "").strip()
        if not ident:
            raise PolicyError(f"organization_accounts[{i}] に identifier が無い")
        # 一般的な著者名の一括除外を禁止する。1件ずつ理由を書かせる。
        if len(reason) < 10:
            raise PolicyError(
                f"organization_accounts[{i}] ({ident}) に理由が無い。"
                "組織アカウントは理由付きで1件ずつ許可する"
            )
        allow.add(ident.lower())
        reasons[ident.lower()] = reason
    data["_allow"] = allow
    data["_reasons"] = reasons
    data["_path"] = path
    return data


def placeholder_matcher(policy):
    pats = policy.get("anonymized_path_placeholders") or []
    if not pats:
        raise PolicyError("anonymized_path_placeholders が空。匿名化の形を定義する")
    return re.compile("|".join(pats))


def tracked_authors(repo, policy):
    """このリポの著者名・メールを集める（本文に個人名が残っていないかの照合用）。

    **一般的な著者名の一括除外はしない。** policy configuration が理由付きで許可した
    組織アカウント識別子だけを除外する。
    """
    raw = set()
    rc, out, _ = git(repo, "log", "-n", "300", "--format=%an%n%ae%n%cn%n%ce")
    if rc == 0:
        raw.update(line.strip() for line in out.splitlines())
    for key in ("user.name", "user.email"):
        rc, out, _ = git(repo, "config", key)
        if rc == 0 and out.strip():
            raw.add(out.strip())
    allow = policy["_allow"]
    names = set()
    for n in raw:
        for cand in (n, n.split("@", 1)[0] if "@" in n else n):
            cand = cand.strip()
            if len(cand) >= 5 and cand.lower() not in allow:
                names.add(cand)
    return names


# ------------------------------------------------------------------- 検査規則
# (rule_id, severity, 正規表現, 説明, 対象パス条件 or None)
# severity: "BLOCK" / "WARN"

SECRET_RULES = [
    ("S01", r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "秘密鍵が本文に含まれている"),
    ("S02", r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b", "AWS アクセスキー"),
    ("S03", r"xox[baprs]-[0-9A-Za-z-]{10,}", "Slack トークン"),
    ("S04", r"\b(?:ghp|gho|ghu|ghs|ghr)_[0-9A-Za-z]{30,}\b|github_pat_[0-9A-Za-z_]{20,}", "GitHub トークン"),
    ("S05", r"\bAIza[0-9A-Za-z_\-]{35}\b", "Google API キー"),
    ("S06", r"\bsk-(?:ant-)?[A-Za-z0-9_\-]{24,}", "LLM API キー"),
    ("S07", r"\"(?:private_key|client_secret|refresh_token)\"\s*:", "認証 JSON の秘密値"),
    (
        # 識別子の一部でも拾う（API_TOKEN, dbPassword, client_secret など）
        "S08",
        r"(?i)[A-Za-z0-9_.\-]*(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|credential)"
        r"[A-Za-z0-9_.\-]*\s*[:=]\s*[\"'][^\"'\s]{8,}[\"']",
        "パスワード/トークンの直書き",
    ),
    (
        # クォート無しの代入（.env 形式・シェル変数）
        "S14",
        r"(?i)^[A-Za-z0-9_.\-]*(?:password|passwd|secret|token|api[_-]?key|access[_-]?key)"
        r"[A-Za-z0-9_.\-]*\s*[:=]\s*[^\s\"'#]{12,}$",
        "パスワード/トークンの直書き（クォート無し）",
    ),
    ("S09", r"(?i)authorization\s*[:=]\s*[\"']?bearer\s+[A-Za-z0-9._\-]{20,}", "Bearer トークンの直書き"),
]

# S08 / S14 が拾いやすいプレースホルダ・参照渡しは除外する
PLACEHOLDER = re.compile(
    r"(?i)(xxx|yyy|zzz|dummy|sample|example|changeme|your[-_]|placeholder|redacted|\*{3,}"
    r"|\$\{|\$env:|<[^>]+>|_here\b|todo|os\.environ|getenv|process\.env|secretmanager"
    r"|keyring|vault|secret_version|SecretString)"
)

SECRET_PATH_RULES = [
    ("S10", r"\.(?:pem|p12|pfx|jks|keystore)$", "鍵ファイルそのもの"),
    ("S11", r"(?:^|/)\.env$|(?:^|/)\.env\.(?!example|sample|template)", "環境変数ファイル（.env.example のみ可）"),
    (
        "S12",
        r"(?:^|/)(?:credentials|client_secret|sa[-_]?key|service[-_]?account|adc)[^/]*\.json$",
        "認証情報ファイル",
    ),
    ("S13", r"(?:^|/)(?:id_rsa|id_ed25519|\.npmrc|\.pypirc|\.netrc)$", "個人の認証設定ファイル"),
]

PII_RULES = [
    (
        "P01",
        r"[A-Za-z0-9._%+\-]+@(?!example\.(?:com|org|net)|test\.|localhost|users\.noreply\.github\.com|noreply\.)[A-Za-z0-9.\-]+\.[A-Za-z]{2,}",
        "メールアドレス（個人特定）。部署名・ロール名に置き換える",
    ),
    ("P02", r"\bgoogle_\d{6,}\b", "実ユーザー識別子"),
    (
        "P03",
        r"[一-龥ァ-ヶ]{2,4}さん(?:が|は|に|の|より|から|へ|と)|(?<![同仕多模異一態様客皆各ぁ-ん])様(?=[がはにのへとよ])",
        "個人への言及。ロール名（例: リポジトリ管理者）に置き換える",
    ),
]

LOCALPATH_RULES = [
    ("L01", "BLOCK", r"[A-Za-z]:[\\/]Users[\\/]", "ローカル絶対パス（Windows）。実在の利用者名が露出する"),
    ("L02", "BLOCK", r"(?:^|[\s\"'(=])/(?:c|mnt/c)/Users/", "ローカル絶対パス（Git Bash / WSL）"),
    ("L03", "BLOCK", r"(?:^|[\s\"'(=])/Users/[A-Za-z]", "ローカル絶対パス（macOS）"),
    ("L04", "WARN", r"~[\\/]\.claude[\\/]", "エージェント home に依存するパス。読者が同じ環境を持つ前提になっていないか確認する"),
]

# 利用者名の位置が匿名化プレースホルダなら、パスの「形」の説明として許容する。
# 実在の利用者名を含むものは引き続き BLOCK（policy configuration が形を定義する）。
LOCALPATH_PLACEHOLDER_IDS = {"L01", "L02", "L03"}

# 会話痕跡: 説明書として読めない表現
CONV_RULES = [
    ("C01", "BLOCK", r"今回|前回の(?:会話|やりとり)|先ほど|さきほど|ご依頼|ご要望|ご指摘|指摘対応|依頼された|言われた(?:ので|通り)", "会話の文脈に依存した表現"),
    ("C02", "BLOCK", r"(?<![A-Za-z])私(?:が|は|の|も|たち)|(?<![A-Za-z])僕|あなた(?:が|は|の|に)|ユーザーさん", "一人称・二人称"),
    ("C03", "BLOCK", r"ますね|ましょう|と思います|でしょうか|ですよね|かなと|しておきました", "会話体の語尾"),
    ("C04", "BLOCK", r"[ABC]案|第[0-9]案|Route [A-Z]\b|口頭で(?:決|合意)|MTGで決", "内部プロセス用語（読者に通じない）"),
    ("C05", "WARN", r"一旦|とりあえず|暫定で|やっぱり|ひとまず", "暫定判断の口語。決定事項と理由を書く"),
    ("C06", "WARN", r"昨日|今日|明日|一昨日|今週|先週|来週|今月|先月|来月|最近|直近", "相対日付。YYYY-MM-DD に置き換える"),
    ("C07", "WARN", r"あとで|後でやる|そのうち|やる予定|TODO(?!\s*\()", "未確定の口約束。担当と期限を書くか削除する"),
    ("C08", "WARN", r"実装済み|対応済み|設定済み|稼働中|問題なし|エラーなし|自動で.{0,8}されます", "実態未確認の断定。実測日か証跡を添える"),
    ("C09", "WARN", r"Claude|ChatGPT|Gemini|サブエージェント|コンパクション|プロンプト", "AI 作業の痕跡。成果物の説明に書き換える"),
]
# C09 を適用しない（AI 向け指示ファイルとして正当な）パス
AI_DOC_PATHS = re.compile(r"(?:^|/)(?:CLAUDE\.md|AGENTS\.md|GEMINI\.md)$|(?:^|/)\.claude/")

STRUCT_PATH_RULES = [
    ("T01", "BLOCK", r"(?:^|/)(?:test|test\d+|tmp|temp|aaa|hoge|foo|bar|hello|work|new|old|copy|untitled)\.[A-Za-z0-9]+$", "スクラッチファイル。コミットしない"),
    ("T02", "BLOCK", r"_bk|_bak|[-_]copy|[-_]final|[-_]latest|v\d+_fixed|コピー", "曖昧なバージョン名。git 履歴で管理する"),
    ("T03", "BLOCK", r"[ 　]", "ファイル名に空白"),
    ("T04", "WARN", r"(?<!\d)20\d{6}(?!\d)", "日付は YYYY-MM-DD 形式に統一する"),
    ("T05", "BLOCK", r"(?:^|/)(?:backups?|credentials|\.venv|venv|node_modules|__pycache__|\.ipynb_checkpoints)/", "コミット対象外のフォルダ。.gitignore に入れる"),
    ("T06", "BLOCK", r"-(?:success|failed)-records\.csv$|(?:^|/)(?:inputs?|outputs?|raw)/.+\.(?:csv|tsv|xlsx|xls|parquet|jsonl)$", "生データ・実行結果データ。コミットしない"),
    ("T07", "BLOCK", r"(?:^|/)settings\.local\.json$|(?:^|/)\.DS_Store$|(?:^|/)Thumbs\.db$", "個人環境ファイル"),
    ("T14", "WARN", r"[^\x00-\x7F]", "ファイル名は英語・小文字・snake_case にする（CONVENTIONS §1）"),
]


def compile_rules():
    out = {}
    for rid, pat, msg in SECRET_RULES:
        out[rid] = (re.compile(pat), "BLOCK", msg)
    for rid, pat, msg in PII_RULES:
        out[rid] = (re.compile(pat), "BLOCK", msg)
    for rid, sev, pat, msg in LOCALPATH_RULES:
        out[rid] = (re.compile(pat), sev, msg)
    for rid, sev, pat, msg in CONV_RULES:
        out[rid] = (re.compile(pat), sev, msg)
    return out


CONTENT_RULES = compile_rules()
SECRET_IDS = {rid for rid, _, _ in SECRET_RULES}

TEXT_DOC = re.compile(r"\.(?:md|markdown|txt|rst|adoc)$", re.I)
SKIP_CONTENT = re.compile(r"\.(?:png|jpe?g|gif|svg|ico|pdf|zip|gz|xlsx|xls|pptx|docx|parquet|db|sqlite3?|woff2?|ttf|eot|mp4|jar|class|pyc)$", re.I)


# ------------------------------------------------------------------- 検査本体


def collect_paths(repo, scope):
    """検査対象パスと、blob を読むための rev 接頭辞を返す。

    staged: これからコミットされる差分（index）／all: 追跡ファイル全体（index の内容）
    head:   HEAD に入っている内容（push 前検査）
    """
    if scope == "staged":
        cmd = ("diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR")
        prefix = ":"
    elif scope == "all":
        cmd = ("ls-files", "-z")
        prefix = ":"
    else:
        cmd = ("ls-tree", "-r", "--name-only", "-z", "HEAD")
        prefix = "HEAD:"
    rc, out, err = git(repo, *cmd)
    if rc != 0:
        return None, None, err.strip()
    return [p for p in out.split("\0") if p], prefix, None


def path_rule_exempt(policy):
    """共通運用ルールが明示的にコミットを認めるパス（複製本体ではなく運用記録）。

    許容するのは**復旧領域ごとの運用ログだけ**である。バックアップ本体・生データは
    引き続き BLOCK する。対象の形は policy configuration が定義し、ここには直書きしない。
    """
    pats = policy.get("operational_log_paths") or []
    if not pats:
        raise PolicyError("operational_log_paths が空。運用ログの形を定義する")
    return {"T05": tuple(re.compile(p) for p in pats)}


def check_path(path, findings, exempt):
    for rid, pat, msg in SECRET_PATH_RULES:
        if re.search(pat, path):
            findings.append((rid, "BLOCK", path, 0, "", msg))
    for rid, sev, pat, msg in STRUCT_PATH_RULES:
        if any(x.search(path) for x in exempt.get(rid, ())):
            continue
        if re.search(pat, path):
            findings.append((rid, sev, path, 0, "", msg))


def mask(text):
    """秘密値をそのままレポートに出さない。"""
    t = text.strip()
    if len(t) <= 12:
        return "(masked)"
    return t[:6] + "…" + t[-2:] + f" [{len(t)}字]"


def check_content(path, blob, findings, authors, policy, placeholder):
    if blob is None or SKIP_CONTENT.search(path):
        return 0
    if len(blob) > LARGE_FILE_BYTES:
        findings.append(("T08", "WARN", path, 0, f"{len(blob)//1024}KB", "大きなファイル。生成物ならスクリプトと対で残すか除外する"))
    if re.search(r"\.(?:csv|tsv|jsonl|parquet)$", path, re.I) and len(blob) > DATA_FILE_BYTES:
        findings.append(("T09", "BLOCK", path, 0, f"{len(blob)//1024}KB", "データファイル。サンプル（完全ダミー）に置き換える"))

    # エンコーディング（種別で要件が反転する）
    has_bom = blob.startswith(b"\xef\xbb\xbf")
    if path.endswith(".ps1") and not has_bom:
        findings.append(("E01", "BLOCK", path, 0, "", ".ps1 は BOM 必須（PowerShell 5.1 が CP932 と誤認して構文エラーになる）"))
    if re.search(r"\.(?:json|sh)$", path) and has_bom:
        findings.append(("E02", "BLOCK", path, 0, "", "この拡張子は BOM 禁止（パース不能 / shebang 破壊）"))
    if path.endswith(".sh") and b"\r\n" in blob:
        findings.append(("E03", "BLOCK", path, 0, "", ".sh の CRLF は Linux で実行不能"))

    try:
        text = blob.decode("utf-8-sig")
    except UnicodeDecodeError:
        return 0  # バイナリ相当は本文検査の対象外

    is_doc = bool(TEXT_DOC.search(path))
    is_ai_doc = bool(AI_DOC_PATHS.search(path))
    # 原文保持の実装ブリーフ・完了記録は、当時の指示語をそのまま残すことに記録としての意味がある。
    # 会話文脈（C01）だけを外す。秘密情報・個人情報・実在パスの検査は継続する。
    brief_prefixes = tuple(policy.get("conversational_rule_exempt_paths") or ())
    is_brief = bool(brief_prefixes) and path.startswith(brief_prefixes)
    suppressed = 0
    for lineno, line in enumerate(text.splitlines(), 1):
        if SUPPRESS_MARK in line:
            suppressed += 1
            continue
        for rid, (pat, sev, msg) in CONTENT_RULES.items():
            if rid == "C09" and is_ai_doc:
                continue
            if rid == "C01" and is_brief:
                continue
            m = pat.search(line)
            if not m:
                continue
            if rid in ("S08", "S14") and PLACEHOLDER.search(line):
                continue
            if rid in LOCALPATH_PLACEHOLDER_IDS and placeholder.match(line[m.end():]):
                continue
            if rid.startswith("C") and not is_doc:
                sev = "WARN"  # コード内のコメントは注意止まり
            excerpt = "(masked)" if rid in SECRET_IDS else mask(m.group(0)) if rid == "P01" else m.group(0)[:60]
            findings.append((rid, sev, path, lineno, excerpt, msg))
            break  # 1 行 1 指摘に留める
    for name in authors:
        if name in text:
            findings.append(("P04", "BLOCK", path, 0, name[:3] + "…", "個人名・アカウント名。部署名/ロール名に置き換える"))
            break
    return suppressed


def check_repo_shape(repo, all_paths, findings):
    names = set(all_paths)
    if "README.md" not in names:
        findings.append(("T10", "BLOCK", "(repo)", 0, "", "README.md がない。何のリポか・前提・使い方・出力・制約を書く"))
    if ".gitignore" not in names:
        findings.append(("T11", "BLOCK", "(repo)", 0, "", ".gitignore がない。秘密・生データ・生成物を最初から遮断する"))
    if not any(p.startswith("docs/") for p in names):
        findings.append(("T12", "WARN", "(repo)", 0, "", "docs/ がない。設計・運用・引き継ぎの置き場を作る"))
    elif "docs/HANDOVER.md" not in names:
        findings.append(("T13", "WARN", "(repo)", 0, "", "docs/HANDOVER.md がない（CONVENTIONS §0 の要件）"))


# --------------------------------------------------------------- レシート発行


def receipt_path(root_dir, repo, tree):
    key = hashlib.sha1(os.path.normcase(repo).encode("utf-8")).hexdigest()[:12]
    return os.path.join(root_dir, key, f"{tree}.json")


def target_tree(repo, scope):
    """レシートの鍵になるツリー。staged/all は index、head は HEAD のツリー。"""
    if scope == "head":
        rc, out, _ = git(repo, "rev-parse", "HEAD^{tree}")
    else:
        rc, out, _ = git(repo, "write-tree")
    return out.strip() if rc == 0 else None


class ReceiptError(Exception):
    """レシートの出力先へ書けない。実行環境の問題であり、判定の問題ではない。"""


def write_receipt(root_dir, repo, tree, payload):
    path = receipt_path(root_dir, repo, tree)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
    except OSError as e:
        raise ReceiptError(
            "レシートを書けない: %s\n"
            "  原因  : %s\n"
            "  対処  : 書き込み可能な既存ディレクトリを --receipt-dir で指定する\n"
            "          （既定は一時ディレクトリ。エージェントの home は指定できない）"
            % (path, e.__class__.__name__)
        )
    return path


# ----------------------------------------------------------------------- main


def main():
    # stdout/stderr が pipe のときも、--json と利用者向けの日本語エラーを UTF-8 で
    # 一貫して渡す。Windows の既定コードページに委ねると、機械可読出力が壊れる。
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(description="共有リポジトリ公開前の機械検査")
    ap.add_argument("--repo", default=".")
    ap.add_argument(
        "--scope",
        choices=["staged", "all", "head"],
        default="staged",
        help="staged=これからコミットする差分 / all=追跡ファイル全体 / head=HEAD の内容（push 前）",
    )
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--force", action="store_true", help="BLOCK を承知でレシートを発行する")
    ap.add_argument("--reason", default="", help="--force の理由（必須・レシートに記録される）")
    ap.add_argument(
        "--receipt-dir",
        default=None,
        help="レシートの出力先。既定は policy の receipt_root（未設定なら一時ディレクトリ）。"
        "エージェントの home へは書き込まない",
    )
    ap.add_argument(
        "--policy",
        default=None,
        help="policy configuration のパス。既定は同梱の config/policy.json、"
        "配備された複製では環境変数 GIT_PUBLISH_POLICY",
    )
    args = ap.parse_args()

    root = repo_root(args.repo)
    if not root:
        print(f"ERROR: git リポジトリではない: {args.repo}", file=sys.stderr)
        return 2
    if args.force and not args.reason.strip():
        print("ERROR: --force には --reason が必要（レシートに記録する）", file=sys.stderr)
        return 2
    try:
        policy = load_policy(args.policy or default_policy())
        placeholder = placeholder_matcher(policy)
        exempt = path_rule_exempt(policy)
    except PolicyError as e:
        # 設定が無いまま検査を続けない（判定不能なら止める）
        print(f"ERROR: policy configuration の問題: {e}", file=sys.stderr)
        return 2
    # レシートの場所は policy が正本。検査する側と、レシートを読む側（PreToolUse ゲート）が
    # 別々に場所を決めると、書いた先と読む先が食い違って永久に検査済みにならない。
    receipt_dir = args.receipt_dir or policy.get("receipt_root") or DEFAULT_RECEIPT_ROOT
    receipt_root = os.path.abspath(os.path.expanduser(receipt_dir))
    for home_dir in (".claude", ".codex"):
        marker = os.path.join(os.path.expanduser("~"), home_dir) + os.sep
        if os.path.normcase(receipt_root + os.sep).startswith(os.path.normcase(marker)):
            print(
                f"ERROR: レシートの出力先にエージェント home を指定できない: {receipt_root}",
                file=sys.stderr,
            )
            return 2

    paths, prefix, err = collect_paths(root, args.scope)
    if paths is None:
        print(f"ERROR: 対象ファイルを取得できない: {err}", file=sys.stderr)
        return 2

    if args.scope == "head":
        all_paths = list(paths)
    else:
        rc, all_out, _ = git(root, "ls-files", "-z")
        all_paths = [p for p in all_out.split("\0") if p] if rc == 0 else list(paths)

    truncated = 0
    if len(paths) > MAX_FILES:
        truncated = len(paths) - MAX_FILES
        paths = paths[:MAX_FILES]

    findings, suppressed = [], 0
    for p in paths:
        check_path(p, findings, exempt)
    blobs = read_blobs(root, [f"{prefix}{p}" for p in paths])
    authors = tracked_authors(root, policy)
    for p in paths:
        suppressed += check_content(
            p, blobs.get(f"{prefix}{p}"), findings, authors, policy, placeholder
        )
    check_repo_shape(root, all_paths, findings)

    blocks = [f for f in findings if f[1] == "BLOCK"]
    warns = [f for f in findings if f[1] == "WARN"]
    tree = target_tree(root, args.scope)

    receipt = None
    if tree and (not blocks or args.force):
        payload = {
            "repo": root,
            "tree": tree,
            "scope": args.scope,
            "policy": policy.get("policy_version", "unknown"),
            "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "files": len(paths),
            "blocks": [[f[0], f[2], f[3], f[5]] for f in blocks],
            "warns": len(warns),
            "forced": bool(args.force and blocks),
            "reason": args.reason.strip(),
        }
        try:
            receipt = write_receipt(receipt_root, root, tree, payload)
        except ReceiptError as e:
            # 検査自体は終わっている。書けないことは実行環境の問題として報告する。
            print(f"ERROR: {e}", file=sys.stderr)
            return 2

    if args.json:
        print(json.dumps(
            {
                "repo": root, "tree": tree, "scope": args.scope, "files": len(paths),
                "truncated": truncated, "suppressed": suppressed, "receipt": receipt,
                "findings": [
                    {"rule": r, "severity": s, "path": p, "line": ln, "excerpt": ex, "hint": h}
                    for r, s, p, ln, ex, h in findings
                ],
            },
            ensure_ascii=False, indent=1,
        ))
    else:
        print(f"preflight: {root}  scope={args.scope}  files={len(paths)}  tree={tree}")
        if truncated:
            print(f"  ! 対象が多いため {truncated} ファイルを未検査（--scope を絞るか分割コミットする）")
        for label, items in (("BLOCK", blocks), ("WARN", warns)):
            if not items:
                continue
            # 同じ規則×同じファイルは 1 行に集約する（読む側の負荷を下げる）
            grouped = {}
            for rid, _, path, lineno, excerpt, msg in items:
                g = grouped.setdefault((rid, path, msg), {"lines": [], "ex": excerpt})
                if lineno:
                    g["lines"].append(lineno)
            print(f"\n[{label}] {len(items)} 件 / {len(grouped)} 箇所")
            for (rid, path, msg), g in list(grouped.items())[:50]:
                lines = g["lines"]
                loc = path
                if lines:
                    shown = ",".join(str(n) for n in lines[:5])
                    loc = f"{path}:{shown}" + (f"(+{len(lines)-5})" if len(lines) > 5 else "")
                tail = f"  … {g['ex']}" if g["ex"] else ""
                print(f"  {rid} {loc}  {msg}{tail}")
            if len(grouped) > 50:
                print(f"  … 他 {len(grouped)-50} 箇所")
        if suppressed:
            print(f"\n(抑制行 {suppressed} 件: {SUPPRESS_MARK})")
        if not blocks:
            print(f"\nBLOCK なし。レシート発行: {receipt}")
        elif args.force:
            print(f"\nBLOCK {len(blocks)} 件を承知で通した（理由: {args.reason.strip()}）。レシート: {receipt}")
        else:
            print(f"\nBLOCK {len(blocks)} 件。修正して再実行する（レシート未発行のためコミットはゲートで止まる）")

    return 0 if (not blocks or args.force) else 1


if __name__ == "__main__":
    sys.exit(main())
