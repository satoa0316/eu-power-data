name: daily-fetch-label

on:
  schedule:
    - cron: "40 5 * * *"   # 毎日 05:40 UTC — 前日分の確定値を取得・ラベリング
  workflow_dispatch:        # 手動実行 (バックフィルはここから日付を入れて実行)
    inputs:
      start:
        description: "開始日 YYYY-MM-DD (空欄=昨日)"
        required: false
      end:
        description: "終了日 YYYY-MM-DD (空欄=開始日と同じ)"
        required: false
      zones:
        description: "対象ゾーン (カンマ区切り)"
        required: false
        default: "DE_LU,GB"

permissions:
  contents: write

concurrency:
  group: pipeline
  cancel-in-progress: false

jobs:
  run:
    runs-on: ubuntu-latest
    timeout-minutes: 60
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: 依存ライブラリ
        run: pip install -r requirements.txt

      - name: Platts価格をSecretから展開 (未設定なら仮置きで続行)
        env:
          PLATTS_CSV: ${{ secrets.PLATTS_CSV }}
        run: |
          if [ -n "$PLATTS_CSV" ]; then
            printf '%s\n' "$PLATTS_CSV" > /tmp/platts_prices.csv
            echo "PLATTS_FILE=/tmp/platts_prices.csv" >> "$GITHUB_ENV"
            echo "✔ Secretの燃料価格を使用 (リポジトリには保存されません)"
          else
            echo "PLATTS_CSV未設定 → data/manual/platts_prices.csv (仮置き) を使用"
          fi

      - name: 限界燃料ラベリング実行
        run: |
          ARGS=""
          [ -n "${{ github.event.inputs.start }}" ] && ARGS="--start ${{ github.event.inputs.start }}"
          [ -n "${{ github.event.inputs.end }}" ]   && ARGS="$ARGS --end ${{ github.event.inputs.end }}"
          [ -n "${{ github.event.inputs.zones }}" ] && ARGS="$ARGS --zones ${{ github.event.inputs.zones }}"
          python scripts/label_marginal_fuel.py $ARGS

      - name: ガス在庫取得 (AGSIキー設定時のみ)
        env:
          AGSI_KEY: ${{ secrets.AGSI_KEY }}
        run: python scripts/fetch_agsi.py

      - name: 結果をリポジトリへコミット
        run: |
          git config user.name  "data-bot"
          git config user.email "actions@users.noreply.github.com"
          git add data docs
          if git diff --cached --quiet; then
            echo "変更なし — コミットせず終了"
            exit 0
          fi
          git commit -m "data: auto update $(date -u +%FT%H:%MZ)"
          git pull --rebase origin "${GITHUB_REF_NAME}" || true
          git push
