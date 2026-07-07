# 【欧州電力分析】自動データ取得・限界燃料ラベリング

欧州電力の①限界燃料の見える化 (SRMCラダー2段判定) を、GitHub Actionsで毎朝自動実行するリポジトリです。
対象: DE-LU / GB (energy-charts + Elexon、キー不要ソースで即稼働)。

## セットアップ (ブラウザだけ・15分)

1. **箱を作る**: GitHubにログイン → 右上「+」→「New repository」→ 名前を入力 (例 `eu-power-data`) →「Create repository」
2. **ファイルを入れる**: リポジトリ画面の「uploading an existing file」リンク → このZIPを解凍した中身を**フォルダごとドラッグ&ドロップ** →「Commit changes」
   - ⚠ `.github` フォルダが隠しフォルダ扱いで漏れやすいので注意 (漏れると自動実行されません)
3. **Actionsを有効化**: 上部「Actions」タブ → 「I understand my workflows, enable them」が出たらクリック
4. **動作確認 (手動実行)**: Actionsタブ → 左の「daily-fetch-label」→ 右の「Run workflow」→ そのまま緑ボタン
   - ✅ 緑チェック: 成功。`docs/data/` にJSONが増え、以後**毎朝05:40 UTCに自動実行**
   - ❌ 赤バツ: 失敗。その実行を開いてログをコピーし、Claudeのスレッドに貼る → 修正版を受け取って上書きアップロード
5. **URLをClaudeに伝える**: リポジトリのURL (例 `https://github.com/あなたのID/eu-power-data`) をスレッドに貼る → Claudeがデータを直接読んで分析を継続

## バックフィル (過去分の一括取得)

Actionsタブ → daily-fetch-label → Run workflow で日付を入力:
`start: 2026-06-01` / `end: 2026-07-05` → 実行。約35日分を順に処理します (10-20分程度)。

## Secrets (任意 — 後から追加でOK)

Settings → Secrets and variables → Actions → New repository secret

| 名前 | 中身 | 効果 |
|---|---|---|
| `PLATTS_CSV` | `data/manual/platts_prices.csv` と同じ形式のCSV**全文**を貼る | 仮置き燃料価格をPlatts実値に差替え。**実値は必ずここへ (リポジトリ本体に置くとライセンス違反)** |
| `AGSI_KEY` | GIE AGSIのAPIキー (https://agsi.gie.eu/account で即時発行) | 欧州ガス在庫の日次取得が追加で動く |
| `ENTSOE_API_KEY` | ENTSO-Eキー (メール申請・2-3営業日) | 予約枠。ENTSO-E二重化 (J03) 実装時に使用 |

## ダッシュボード (任意)

Settings → Pages → Branch: `main`・フォルダ: `/docs` → Save。
数分後 `https://あなたのID.github.io/eu-power-data/` で①限界燃料モニターが見られます (毎朝自動更新)。

## 初回だけ押すもの

Actionsタブ → 「static-assets (OPSD設備台帳)」→ Run workflow。
OPSDのプラント台帳から国別×技術別の設備容量・フリートη表 (`data/static/fleet_capacity_eta.csv`) を生成します (2020年断面のため要ENTSO-E突合、次アクション2番のベース)。

## 出力ファイル

| パス | 内容 |
|---|---|
| `data/mart/labels_{zone}.csv` | コマ別ラベル (ts_utc / price / stage1 / label / unresolved / 稼働MW / 隣国価格差) |
| `data/mart/daily_shares_{zone}.csv` | 日次シェア・UNRESOLVED率・import_set率 |
| `docs/data/marginal_fuel_daily_{zone}.json` | ダッシュボード用 (全履歴) |
| `data/mart/gas_storage.csv` | AGSI在庫 (キー設定時のみ) |
| `data/static/fleet_capacity_eta.csv` | OPSD由来 容量・η表 |

## 前提値の出典

SRMC式・効率レンジ・判定パラメータ (TOL±5 / 余剰上限15 / 稼働>500MW / <92% / 収斂<2) は
**データ基盤設計書 90_検証データ記録・05_計算層定義** と一致 (`scripts/config.py`)。
検算: `python scripts/srmc.py` と `python scripts/selftest.py` が設計書の検算例・スポットチェックを再現します。

データ出典: energy-charts.info / SMARD (Bundesnetzagentur, CC BY 4.0)・Elexon Insights・GIE AGSI・Open Power System Data。
