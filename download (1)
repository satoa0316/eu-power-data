name: static-assets (OPSD設備台帳)

on:
  workflow_dispatch:   # 手動のみ。初回に1回押せばOK (更新はENTSO-E突合時に再実行)

permissions:
  contents: write

jobs:
  opsd:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -r requirements.txt
      - name: OPSD台帳 → 容量・ηテーブル生成
        run: python scripts/fetch_opsd_plants.py
      - name: コミット
        run: |
          git config user.name  "data-bot"
          git config user.email "actions@users.noreply.github.com"
          git add data/static
          git diff --cached --quiet && { echo "変更なし"; exit 0; }
          git commit -m "static: OPSD fleet capacity/eta table"
          git pull --rebase origin "${GITHUB_REF_NAME}" || true
          git push
