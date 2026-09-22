# ACT GOLD長浜 スロット台データ収集システム(フェーズ1)

みんレポ(min-repo.com)からACT GOLD長浜のスロット台データを毎日自動収集し、
Supabaseに保存するシステムです。まずは「データを確実に集める」ことだけに
集中したフェーズ1の実装です(分析・予測はデータが揃ってから次のフェーズで行います)。

## 使っているもの

- **Supabase**: プロジェクト名 `act-gold-nagahama` (project ref: `tyrdfvqtgunafwmyrjxm`)
  - テーブルは作成済みです(`slot_daily_data`, `collection_log`)
- **GitHub Actions**: 毎日の自動収集 + 手動実行のバックフィル
- **Playwright (Python)**: min-repo.comがJavaScript描画のサイトのため、ヘッドレスブラウザで取得

## セットアップ手順

### 1. Secretsを設定する

リポジトリの `Settings` → `Secrets and variables` → `Actions` → `New repository secret` から、
以下の2つを登録してください。

| Name | Value |
|---|---|
| `SUPABASE_URL` | `https://tyrdfvqtgunafwmyrjxm.supabase.co` |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabaseダッシュボード → 対象プロジェクト → `Project Settings` → `API Keys` → `service_role` の値(secretなので画面上でコピーしてください。私からは取得できません) |

### 2. 動作確認(1日分だけ試す)

リポジトリの `Actions` タブ → `Backfill (ACT GOLD長浜)` → `Run workflow` から、
まず1日分だけで試すのがおすすめです。

- `start_date`: `2026-09-20`
- `end_date`: `2026-09-20`

### 3. 本番バックフィル(過去2か月分)

- `start_date`: `2026-07-22`
- `end_date`: `2026-09-21`

### 4. 日次自動収集

`daily-collect.yml` は毎日 23:50 JST に自動実行されるよう設定済みです。

## うまくいかない場合

各ワークフローは失敗時にスクリーンショット/HTMLをActionsの実行結果に
「Artifacts」として添付するようにしてあります。共有してもらえれば原因を調べます。

## 既知の制約・注意点

- 現時点ではスロットデータのみです(パチンコは対象外)。
- サイトの「前日」リンクを辿ってバックフィルするため、みんレポ側が
  過去62日分すべてを保持していない場合、途中で止まります。
- 台番号の欠番・0G/0枚のデータはそのまま保存します(削除・補完しません)。
