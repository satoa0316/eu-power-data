# -*- coding: utf-8 -*-
"""
サプライカーブ第0版 (②の中核前段): labels CSVから
残余需要(GW) × DA価格 × 限界燃料ラベル の散布データを docs/data/supply_curve_{zone}.json へ。
価格予測の骨格 = このカーブをレジーム別に推定し、残余需要「予測」を通すこと。
"""
import csv
import json
import logging
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
log = logging.getLogger("curve")


def run():
    for zone in ["DE_LU", "GB"]:
        src = ROOT / "data" / "mart" / f"labels_{zone}.csv"
        if not src.exists():
            continue
        pts = []
        with open(src, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                res = r.get("residual_mw")
                if not res:
                    continue
                pts.append({"d": r["date"], "h": r["local"][11:16],
                            "x": round(float(res) / 1000, 2),  # GW
                            "y": round(float(r["price"]), 1),
                            "l": r["label"], "u": r["unresolved"] == "True"})
        out = ROOT / "docs" / "data" / f"supply_curve_{zone}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"zone": zone, "n": len(pts), "points": pts},
                                  ensure_ascii=False), encoding="utf-8")
        log.info("サプライカーブ %s: %d点 → %s", zone, len(pts), out)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
