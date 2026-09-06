---
name: codex-implement
description: 設計側（Codex）が書いたブリーフの指揮下で実装する。docs/codex-briefs/ACTIVE.md が存在するリポジトリでの実装・修正・テスト、ブリーフ・引き継ぎ書・受入基準に沿った作業、既存の未コミット差分を保全しながらの実装に使う。仕様を独自に再設計せず、判断が必要な点は BLOCKED_FOR_CODEX として止める。Use when a repository has an active implementation brief that must be treated as the sole specification.
metadata:
  short-description: Codex ブリーフ指揮下の実装
---

# Codex 指揮下で実装する

## 適用条件

作業対象のリポジトリに `docs/codex-briefs/ACTIVE.md`（または利用者が指定したブリーフ）がある場合、
**そのブリーフを最上位の実装指示として扱う。** 会話の要約や記憶より優先する。

## 手順

1. リポジトリの `CLAUDE.md` と対象ブリーフを**全文**読む。抜粋で判断しない。
2. `git status --short` と、ブリーフに記載された既存差分を確認する。
   **既存の未コミット変更は設計側または利用者の成果物である。**
   `git reset`、`git checkout --`、ファイルの作り直しで消去しない。
3. ブリーフの**許可パス・実装順・受入基準だけ**に従って実装し、テストする。
   許可パス外は変更しない。
4. 本番組織へのデプロイ、データ更新、削除は行わない。
   検証先はブリーフに記載された sandbox のみとする。
5. 完了時は、ブリーフの完了記録テンプレート（`HANDOFF_COMPLETE` 等）に従い、
   **変更ファイル・実行したコマンドと結果・未解決事項**を事実だけで追記して停止する。

## 止まる条件

次に出会ったら推測で進めず、`BLOCKED_FOR_CODEX` として理由を記録して停止する。

- 設計上の判断が必要な選択肢
- 許可パス外の変更が必要になった
- ブリーフと実物（コード・組織設定・データ）が食い違う
- 仕様上の不明点

レビュー用の複数エージェント起動や、指示されていない広範な再監査は行わない。
