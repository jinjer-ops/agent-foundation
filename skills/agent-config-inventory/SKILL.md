---
name: agent-config-inventory
description: Inventory an agent configuration and report what is actually in force, separating skills, always-on rules, invocable commands, notes, and hooks. Use when guidance seems not to be followed, when deciding where a new practice belongs, before relying on a gate or check, or when auditing accumulated configuration for drift and stale claims.
metadata:
  short-description: Report what the configuration actually enforces
---

# agent-config-inventory — 効いているものと、書いてあるだけのものを分ける

## このスキルが解く問題

指示の置き場所は5種類あり、見た目は同じ Markdown でも**効き方が全く違う**。
「スキルにした」つもりのものが実際には読まれるだけのメモだったり、
「ゲートを作った」ものが設定に配線されておらず何も止めていなかったりする。
どちらも**エラーにならないので気づけない**。

このスキルは、形ごとの数を数え、**主張と実態を突き合わせる**。

## 5つの形と、実際の効き方

| 形 | 置き場所 | いつ読まれるか | 強制力 |
| --- | --- | --- | --- |
| skill | `skills/<name>/SKILL.md` | 関連と判断されたとき、または `/name` で呼ばれたとき。本体は呼ばれるまで読まれない | なし（文脈） |
| rule | `rules/*.md` | **毎セッション**（`paths` 指定時は一致するファイルを触るとき） | なし（文脈） |
| command | `commands/*.md` | `/name` で呼ばれたときのみ | なし（文脈） |
| note（自動メモ） | `projects/<p>/memory/` | 索引だけ毎回。本体は必要時に読まれる | なし（文脈） |
| **hook** | `settings.json` の `hooks` に**登録された**コマンド | ライフサイクルの固定点 | **あり（唯一）** |

**強制したいものは hook にしか置けない。** それ以外は全て「読んで従う」であり、
守られなかったときに検知されない。

## どの形にするかの判断

| 内容 | 形 |
| --- | --- |
| ほぼ毎回必要な短い事実・判断基準 | rule（短く保つ。毎回コストを払う） |
| 起動条件と完了条件がある反復手順、参照資料が長い | skill |
| 人が明示的に呼びたい定型作業 | skill（`commands/` より優先。ディレクトリ・付随ファイル・起動制御が使える） |
| 案件固有の事実、経緯、外部リソースの在り処 | note |
| **破ったら止めたいこと** | hook。加えて、その hook を**登録**する |

`commands/*.md` は今も動くが、ディレクトリを持てず、付随スクリプトを置けず、
自動起動の制御もできない。同じ名前で skill を作ると skill が優先される。

## 手順

1. **数と形を出す。**

   ```bash
   python scripts/inventory.py --settings <プロジェクトの settings.json>
   ```

   `--settings` はプロジェクト・ポリシー層を追加で見るために繰り返し指定できる。
   `--json` で機械可読。**主張が裏付けられないものが1件でもあれば終了コード1。**

2. **`CONTRADICTION` を最優先で見る。** 「hook が拒否する」と書いてあるのに登録されていない、
   という状態である。文書を直すか、hook を登録するかのどちらかを選ぶ。
   **ファイルが存在することは、効いていることの証明ではない。**
3. **`mention only` は誤検知ではない。** hook に触れているが「有効にしていない」と明記している文書は、
   正確なので直す必要はない。
4. **`SECRET-SHAPED` を確認する。** 設定に資格情報の値が埋まっている疑いがある箇所。
   値は表示しない。該当したら、値の失効・ローテーションと、設定からの除去を行う。
   **設定ファイルは `.gitignore` の対象外の場所にあることが多い。**
5. **`DEAD PATHS` を確認する。** note が指すパスが消えている。移動先を書き直すか、note を削除する。
6. 形が合っていないものを移す。移したら、**元の場所から消す**（二重管理を作らない）。

## 検査が見ないもの

- **hook が登録されていても、意図どおり止めるかは検査しない。** 登録の有無だけを見る。
  実際に止まるかは、止まるべき操作を1回試して確認する。
- `commands/` と skill の**内容の重複**は判定しない。名前の衝突は runtime が解決する（skill 優先）。
- note の**内容が古いか**は判定しない。判定できるのは、参照先パスが消えていることだけ。
- プロジェクト単位の skill・plugin・組織ポリシー層は、`--settings` で渡した範囲しか見ない。
- 資格情報の判定はキー名の形だけで行う。**通過は「秘密が無い」ことの証明ではない。**
