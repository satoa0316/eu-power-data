# -*- coding: utf-8 -*-
"""
OPSD Conventional Power Plants → 国別×技術別の設備容量・フリートη テーブル生成。
(次アクション2番「設備容量・フリートηの国別テーブル整備」のベース)

注意: OPSDは2020年断面。独原子力全廃(2023)・石炭閉鎖分は含まれない廃止プラントがあるため、
shutdown/retrofit列でフィルタしつつ、最終的にENTSO-E installed capacityとの突合が必要。
出典: Open Power System Data. Data Package Conventional power plants. (MIT/CC-BY, 原典は各国当局)
"""
import csv
import io
import logging
import sys
from collections import defaultdict
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "static"
log = logging.getLogger("opsd")

URLS = {
    "DE": "https://data.open-power-system-data.org/conventional_power_plants/latest/conventional_power_plants_DE.csv",
    "EU": "https://data.open-power-system-data.org/conventional_power_plants/latest/conventional_power_plants_EU.csv",
}
# fuel/energy_source 名 → 技術キー (ガスはtechnology列でCCGT/OCGT振り分け)
FUEL_MAP = {"Lignite": "lignite", "Hard coal": "coal", "Natural gas": "gas",
            "Fossil fuels": "gas"}
TARGET_COUNTRIES = {"DE", "FR", "GB", "UK", "BE", "NL", "ES", "IT"}


def _pick(row, *names):
    for n in names:
        v = row.get(n)
        if v not in (None, ""):
            return v
    return None


def tech_of(fuel, technology):
    t = FUEL_MAP.get(fuel)
    if t != "gas":
        return t
    tech = (technology or "").lower()
    if "combined cycle" in tech:
        return "ccgt"
    if "gas turbine" in tech or "open cycle" in tech:
        return "ocgt"
    return "ccgt_or_steam"  # 蒸気/不明ガス — 別掲


def main():
    logging.basicConfig(level=logging.INFO)
    OUT.mkdir(parents=True, exist_ok=True)
    agg = defaultdict(lambda: [0.0, 0.0, 0.0])  # (country,tech) -> [capMW, Σcap*eta, Σcap(η有)]
    for name, url in URLS.items():
        log.info("取得: %s", url)
        r = requests.get(url, timeout=120)
        r.raise_for_status()
        reader = csv.DictReader(io.StringIO(r.text))
        n = 0
        for row in reader:
            country = (_pick(row, "country", "country_code") or name).strip().upper()
            if name == "DE":
                country = "DE"
            if country == "UK":
                country = "GB"
            if country not in TARGET_COUNTRIES:
                continue
            status = (_pick(row, "status") or "").lower()
            if status in ("shutdown", "shutdown_temporary", "decommissioned"):
                continue
            fuel = _pick(row, "fuel", "energy_source", "energy_source_level_2")
            tech = tech_of(fuel, _pick(row, "technology"))
            if not tech:
                continue
            try:
                cap = float(_pick(row, "capacity_net_bnetza", "capacity", "capacity_gross_uba") or 0)
            except ValueError:
                continue
            if cap <= 0:
                continue
            eta = _pick(row, "efficiency_data", "efficiency_estimate", "efficiency_source")
            key = (country, tech)
            agg[key][0] += cap
            try:
                e = float(eta)
                if 0.15 < e < 0.75:
                    agg[key][1] += cap * e
                    agg[key][2] += cap
            except (TypeError, ValueError):
                pass
            n += 1
        log.info("%s: %d ユニット集計", name, n)

    out = OUT / "fleet_capacity_eta.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["country", "tech", "capacity_mw", "eta_capacity_weighted",
                    "eta_coverage_share", "source"])
        for (c, t), (cap, se, sc) in sorted(agg.items()):
            w.writerow([c, t, round(cap, 1),
                        round(se / sc, 3) if sc else "",
                        round(sc / cap, 2) if cap else "",
                        "OPSD conventional_power_plants (2020断面, 要ENTSO-E突合)"])
    log.info("出力: %s", out)


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001
        log.exception("OPSD取得失敗 — 列名変更の可能性。ログをスレッドに貼ってください")
        sys.exit(1)
