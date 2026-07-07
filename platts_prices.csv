# -*- coding: utf-8 -*-
"""
SRMC帯の計算 (05シートC01b / 90シート検算式)
  SRMC = 燃料(th)/η + CO2価格×排出係数/η + VOM
検算 (仮置き価格 TTF32/API2 105/EUA78, EURUSD1.09):
  褐炭 78.3-95.5 / CCGT 84.3-103.6 / 石炭 90.7-110.0 / OCGT 121.4-161.2
"""
import csv
import logging
from datetime import date as _date
from pathlib import Path

import config as C

log = logging.getLogger("srmc")


def load_fuel_prices(path: Path):
    """Platts CSV (04シート形式) を読み、date→dict のマップを返す。
    シンボル行・単位行・サンプル注記などデータでない行はスキップ。"""
    rows = {}
    if not path or not Path(path).exists():
        log.warning("燃料価格CSVなし (%s) → 仮置き価格を使用", path)
        return rows
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            d = (r.get("date") or "").strip()
            if len(d) != 10 or d[4] != "-":
                continue  # ヘッダ補助行 (名称/単位/シンボル) を無視
            try:
                rows[d] = {k: float(v) for k, v in r.items()
                           if k != "date" and v not in (None, "", "-")}
            except ValueError:
                log.warning("燃料価格CSV: %s 行に数値でない値 → スキップ", d)
    log.info("燃料価格CSV読込: %d日分 (%s)", len(rows), path)
    return rows


def prices_for(day: str, table: dict) -> dict:
    """当日値→無ければ直近過去値 (forward-fill)→無ければ仮置き。"""
    p = dict(C.PLACEHOLDER_PRICES)
    src = "placeholder"
    if table:
        past = sorted(k for k in table if k <= day)
        if past:
            p.update(table[past[-1]])
            src = past[-1] + ("" if past[-1] == day else " (ffill)")
    p["_source"] = src
    return p


def fuel_th(fuel: str, p: dict, currency: str) -> float:
    """燃料の熱量あたり価格を現地通貨/MWh(th)で返す。"""
    if fuel == "lignite":
        return C.LIGNITE_FUEL_TH  # EUR前提 (DEのみ)
    if fuel == "gas":
        if currency == "GBP":
            return p["nbp_da"] / 100.0 / C.THERM_TO_MWH        # p/therm → £/MWh(th)
        return p["ttf_da"]                                      # €/MWh(th)
    if fuel == "coal":
        eur = p["api2_fm"] / p["eurusd"] / C.API2_KCAL_CONV     # $/t → €/MWh(th)
        return eur / p["gbpeur"] if currency == "GBP" else eur
    raise KeyError(fuel)


def carbon_price(p: dict, currency: str) -> float:
    return (p["uka_dec"] + C.CPS_GBP) if currency == "GBP" else p["eua_dec"]


def bands(day_prices: dict, currency: str, techs) -> dict:
    """技術→[lo, hi] のSRMC帯。lo=高効率側, hi=低効率側。"""
    co2 = carbon_price(day_prices, currency)
    out = {}
    for t in techs:
        a = C.TECH[t]
        f = fuel_th(a["fuel"], day_prices, currency)
        vals = [f / eta + co2 * a["ef"] / eta + a["vom"] for eta in a["eta"]]
        out[t] = [round(min(vals), 1), round(max(vals), 1)]
    return out


if __name__ == "__main__":  # 検算: 90シートの帯を再現できるか
    logging.basicConfig(level=logging.INFO)
    b = bands(dict(C.PLACEHOLDER_PRICES), "EUR", ["lignite", "ccgt", "coal", "ocgt"])
    expect = {"lignite": [78.3, 95.5], "ccgt": [84.3, 103.6],
              "coal": [90.7, 110.0], "ocgt": [121.4, 161.2]}
    for k, v in expect.items():
        ok = abs(b[k][0] - v[0]) < 0.15 and abs(b[k][1] - v[1]) < 0.15
        print(f"{k:8s} calc={b[k]} expect={v} {'OK' if ok else 'NG'}")
        assert ok, f"検算不一致: {k}"
    gb = bands(dict(C.PLACEHOLDER_PRICES), "GBP", ["ccgt", "ocgt"])
    print("GB(参考)", gb, "… CCGT中心 η0.52 ≈ £77.4 (設計図⑤と整合するはず)")
