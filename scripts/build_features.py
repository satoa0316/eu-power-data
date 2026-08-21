# -*- coding: utf-8 -*-
"""
日次フィーチャーストア構築。
公開リポジトリにコミットするのは非ライセンス系列のみ (DA・需給・在庫・季節)。
Platts系 (ガス・炭素) は train_model が実行時にSecret/ローカルCSVからメモリ結合する。
優先順位: fundamentals(取得) > seed(xlsx由来) > labels日平均。
"""
import csv
import logging
import math
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
log = logging.getLogger("feat")
ZONES = ["GB", "DE_LU", "FR", "NL", "BE", "ES", "IT"]


def _read_csv(p: Path, key="date"):
    if not p.exists():
        return {}
    with open(p, newline="", encoding="utf-8") as f:
        return {r[key]: r for r in csv.DictReader(f)}


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def run():
    seeds_da = _read_csv(ROOT / "data" / "static" / "seed_da_daily.csv")
    seeds_st = _read_csv(ROOT / "data" / "static" / "seed_storage.csv")
    agsi = _read_csv(ROOT / "data" / "mart" / "gas_storage.csv") if \
        (ROOT / "data" / "mart" / "gas_storage.csv").exists() else {}
    # AGSIはdate+countryの縦持ち → EU full%を日次化
    agsi_eu = {}
    if agsi:
        with open(ROOT / "data" / "mart" / "gas_storage.csv", newline="") as f:
            for r in csv.DictReader(f):
                if r.get("country") == "EU" and r.get("full_pct"):
                    agsi_eu[r["date"][:10]] = _num(r["full_pct"])

    for zone in ZONES:
        fund = _read_csv(ROOT / "data" / "raw" / "fundamentals" / f"fund_{zone}.csv")
        # labelsの日平均 (DAのフォールバック)
        lab_da = {}
        labp = ROOT / "data" / "mart" / f"labels_{zone}.csv"
        if labp.exists():
            acc = {}
            with open(labp, newline="") as f:
                for r in csv.DictReader(f):
                    acc.setdefault(r["date"], []).append(float(r["price"]))
            lab_da = {d: sum(v) / len(v) for d, v in acc.items()}
        days = sorted(set(fund) | set(lab_da) |
                      {d for d in seeds_da if _num(seeds_da[d].get(f"da_base_{zone}"))})
        if not days:
            continue
        rows = []
        for d in days:
            if d < "2021-06-01":
                continue
            f0 = fund.get(d, {})
            da = _num(f0.get("da_base"))
            if da is None:
                da = _num(seeds_da.get(d, {}).get(f"da_base_{zone}"))
            if da is None:
                da = lab_da.get(d)
            if da is None:
                continue
            st = agsi_eu.get(d)
            if st is None and d in seeds_st:  # mcm→充填proxy (DE容量≈245TWh≒24,600mcm)
                v = _num(seeds_st[d].get("storage_de_mcm"))
                st = round(v / 24600 * 100, 1) if v else None
            doy = date.fromisoformat(d).timetuple().tm_yday
            rows.append({"date": d, "da_base": round(da, 2),
                         "demand_gw": f0.get("demand_gw", ""),
                         "wind_gw": f0.get("wind_gw", ""),
                         "solar_gw": f0.get("solar_gw", ""),
                         "ic_net_gw": f0.get("ic_net_gw", ""),
                         "storage_pct": "" if st is None else st,
                         "sin_doy": round(math.sin(2 * math.pi * doy / 365), 4),
                         "cos_doy": round(math.cos(2 * math.pi * doy / 365), 4)})
        out = ROOT / "data" / "mart" / f"features_daily_{zone}.csv"
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader(); w.writerows(rows)
        log.info("features %s: %d日 (%s〜%s)", zone, len(rows), rows[0]["date"], rows[-1]["date"])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
