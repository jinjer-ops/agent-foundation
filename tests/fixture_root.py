# -*- coding: utf-8 -*-
"""テストが使う一時ディレクトリの作成先を決める。

標準の一時ディレクトリへ書けない実行環境があるため、作成先を差し替えられるようにする。
生成物は**その実行が作った一意な子ディレクトリの中だけ**に作り、後片付けもその子だけを対象にする。
指定した作成先そのものは消さない。
"""
from __future__ import annotations

import atexit
import os
import shutil
import stat
import sys
import tempfile
import uuid

FIXTURE_ROOT_ENV = "PREFLIGHT_FIXTURE_ROOT"
_SESSION = {"dir": None}


def _drop_readonly(func, path, _exc):
    """git のオブジェクトは read-only で作られる。属性を外して再試行する。"""
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except OSError:
        pass


def remove_tree(path):
    """作成した木を実際に消す。

    `ignore_errors=True` だけでは、read-only な git オブジェクトが残ったまま
    「消えた」ように見える。属性を外して再試行し、消えたかどうかを呼び出し側が確認できるようにする。
    """
    if not os.path.exists(path):
        return
    try:
        shutil.rmtree(path, onexc=_drop_readonly)      # Python 3.12 以降
    except TypeError:
        shutil.rmtree(path, onerror=_drop_readonly)    # Python 3.11 以前


def make_unique_directory(root, prefix):
    """`root` の直下に、この実行専用のディレクトリを1つ作る。

    `tempfile.mkdtemp()` は、Windows の一部の拒否環境で PermissionError を候補名の
    衝突として繰り返し扱い、利用者への案内に到達しないことがある。衝突だけを再試行し、
    それ以外の OS エラーは呼び出し側へそのまま渡す。
    """
    for _ in range(100):
        # fixture 内にはさらに git の object path が続く。深い明示 root でも Windows の
        # パス上限を避けるため、衝突時の再試行と組み合わせて接尾辞は8文字に保つ。
        path = os.path.join(root, prefix + uuid.uuid4().hex[:8])
        try:
            os.mkdir(path)
            return path
        except FileExistsError:
            continue
    raise OSError("一意な fixture ディレクトリを作れない")


def _guidance(root, cause, explicit):
    where = "環境変数 %s" % FIXTURE_ROOT_ENV if explicit else "標準の一時ディレクトリ"
    return (
        "fixture の作成先が使えない: %s\n"
        "  指定元: %s\n"
        "  原因  : %s\n"
        "  対処  : 書き込み可能な既存ディレクトリを指定する。\n"
        "          環境変数        %s=<dir>\n"
        "          直接実行のとき  python tests/test_preflight.py --fixture-root <dir>\n"
        "          （ディレクトリは事前に作成しておく。存在しない場所は指定できない）"
        % (root, where, cause, FIXTURE_ROOT_ENV)
    )


def resolve_fixture_root():
    """fixture を作る親ディレクトリを決め、実際に書けることを確かめて返す。

    未指定なら標準の一時ディレクトリを使う。使えない場合は、何を設定すべきかを示して
    RuntimeError を投げる（判定前に不明な例外で落とさない）。
    """
    explicit = bool(os.environ.get(FIXTURE_ROOT_ENV, "").strip())
    root = os.path.abspath(os.path.expanduser(
        os.environ.get(FIXTURE_ROOT_ENV, "").strip() or tempfile.gettempdir()
    ))
    if not os.path.isdir(root):
        raise RuntimeError(_guidance(root, "ディレクトリが存在しない", explicit))
    probe = None
    try:
        probe = make_unique_directory(root, "preflight-probe-")
        # case は session の子に作るため、root 直下だけでなく一段深い作成権限まで確認する。
        make_unique_directory(probe, "preflight-probe-child-")
    except OSError as e:
        raise RuntimeError(_guidance(root, "書き込みできない（%s）" % e.__class__.__name__, explicit))
    finally:
        # 子の作成に失敗した場合も、root 直下へ作れた probe だけは残さない。
        if probe:
            try:
                remove_tree(probe)
            except OSError:
                pass
    return root


def session_dir():
    """この実行だけが使う一意なディレクトリ。生成物はすべてこの中に作る。"""
    if _SESSION["dir"] is None:
        root = resolve_fixture_root()
        _SESSION["dir"] = make_unique_directory(root, "preflight-fixtures-")
        # 後片付けの対象は、この実行が作ったこの1つだけ。指定された root 自体は消さない。
        atexit.register(remove_tree, _SESSION["dir"])
    return _SESSION["dir"]
