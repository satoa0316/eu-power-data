# -*- coding: utf-8 -*-
"""GIE AGSI ガス在庫 (J06)。Secret AGSI_KEY 設定時のみ daily.yml から呼ばれる。"""
import csv
import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "mart" / "gas_storage.csv"
COUNTRIES = ["EU", "DE", "FR", "GB", "BE", "NL", "ES", "IT"]
log = logging.getLogger("agsi")


def main():
    logging.basicConfig(level=logging.INFO)
    key = os.environ.get("AGSI_KEY")
    if not key:
        log.info("AGSI_KEY未設定 → スキップ")
        return
    day = (date.today() - timedelta(days=1)).isoformat()
    rows = []
    for c in COUNTRIES:
        try:
            r = requests.get("https://agsi.gie.eu/api",
                             params={"country": c, "date": day, "size": 1},
                             headers={"x-key": key}, timeout=60)
            r.raise_for_status()
            d = (r.json().get("data") or [{}])[0]
            rows.append({"date": d.get("gasDayStart", day), "country": c,
                         "full_pct": d.get("full"), "storage_twh": d.get("gasInStorage"),
                         "injection": d.get("injection"), "withdrawal": d.get("withdrawal")})
        except Exception as e:  # noqa: BLE001
            log.warning("%s 取得失敗: %s", c, e)
    if not rows:
        sys.exit(1)
    existing = []
    if OUT.exists():
        with open(OUT, newline="", encoding="utf-8") as f:
            existing = list(csv.DictReader(f))
    seen = {(r["date"], r["country"]): r for r in existing}
    for r in rows:
        seen[(str(r["date"]), r["country"])] = {k: str(v) for k, v in r.items()}
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["date", "country", "full_pct", "storage_twh",
                                          "injection", "withdrawal"], extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(seen.values(), key=lambda r: (r["date"], r["country"])))
    log.info("在庫 %d カ国分を追記 → %s", len(rows), OUT)


if __name__ == "__main__":
    main()
