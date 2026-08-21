# -*- coding: utf-8 -*-
"""
日次ファンダメンタルズ (需要・風力・太陽光・DA日平均・IC) の取得。
ensure_history() が fund_{zone}.csv の欠落日を検出し、不足チャンクだけ取得する
自己埋め方式 — 毎日の実行で少しずつ2021-06まで遡及が完了する (ワークフロー変更不要)。
"""
import csv
import logging
from datetime import date, timedelta
from pathlib import Path
from statistics import mean

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "raw" / "fundamentals"
HIST_START = date(2021, 6, 1)
log = logging.getLogger("fund")
S = requests.Session(); S.headers["User-Agent"] = "eu-power-data/3.0"

# Wave1: GB/DE ｜ Wave2: FR/NL/BE/ES/IT (energy-chartsで同一メッシュ)
FUND_ZONES = {
    "DE_LU": {"src": "ec", "cc": "de", "bzn": "DE-LU"},
    "GB":    {"src": "elexon"},
    "FR":    {"src": "ec", "cc": "fr", "bzn": "FR"},
    "NL":    {"src": "ec", "cc": "nl", "bzn": "NL"},
    "BE":    {"src": "ec", "cc": "be", "bzn": "BE"},
    "ES":    {"src": "ec", "cc": "es", "bzn": "ES"},
    "IT":    {"src": "ec", "cc": "it", "bzn": "IT-North"},  # PUN相当は要検討(論点#6)
}
COLS = ["date", "da_base", "demand_gw", "wind_gw", "solar_gw", "ic_net_gw", "gen_total_gw"]


def _read(zone):
    p = OUT / f"fund_{zone}.csv"
    if not p.exists():
        return {}
    with open(p, newline="", encoding="utf-8") as f:
        return {r["date"]: r for r in csv.DictReader(f)}


def _write(zone, table):
    p = OUT / f"fund_{zone}.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS, restval="", extrasaction="ignore")
        w.writeheader()
        for d in sorted(table):
            w.writerows([dict(table[d], date=d)])


def _daily_avg(unix, vals, count_by_day):
    from datetime import datetime, timezone
    acc = {}
    for t, v in zip(unix, vals):
        if v is None:
            continue
        d = datetime.fromtimestamp(t, timezone.utc).date().isoformat()
        acc.setdefault(d, []).append(v)
    return {d: mean(v) for d, v in acc.items() if len(v) >= count_by_day}


# ---------------- energy-charts (DE + Wave2) ----------------
def _ec_chunk(zone, cfg, d0: date, d1: date, table):
    p = {"start": d0.isoformat(), "end": d1.isoformat()}
    try:
        pw = S.get("https://api.energy-charts.info/public_power",
                   params=dict(p, country=cfg["cc"]), timeout=120).json()
        types = {t["name"]: t["data"] for t in pw["production_types"]}
        ux = pw["unix_seconds"]
        def agg(names):
            series = [types[n] for n in names if n in types]
            if not series:
                return {}
            comb = [sum((s[i] or 0) for s in series) for i in range(len(ux))]
            return _daily_avg(ux, comb, 20)
        load = agg(["Load"])
        wind = agg(["Wind onshore", "Wind offshore"])
        sol = agg(["Solar"])
        gen = agg([n for n in types if n not in
                   ("Load", "Residual load", "Renewable share of load",
                    "Renewable share of generation")])
        pr = S.get("https://api.energy-charts.info/price",
                   params=dict(p, bzn=cfg["bzn"]), timeout=120).json()
        da = _daily_avg(pr["unix_seconds"], pr["price"], 20)
        for d in set(load) | set(da):
            row = table.setdefault(d, {})
            if d in da: row["da_base"] = round(da[d], 2)
            if d in load: row["demand_gw"] = round(load[d] / 1000, 2)
            if d in wind: row["wind_gw"] = round(wind[d] / 1000, 2)
            if d in sol: row["solar_gw"] = round(sol[d] / 1000, 2)
            if d in load and d in gen:  # IC純輸入 ≈ 需要 − 総発電 (正=純輸入)
                row["ic_net_gw"] = round((load[d] - gen[d]) / 1000, 2)
                row["gen_total_gw"] = round(gen[d] / 1000, 2)
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("EC %s %s〜%s 失敗: %s", zone, d0, d1, e)
        return False


# ---------------- Elexon (GB) ----------------
def _ex_get(path, params):
    r = S.get(f"https://data.elexon.co.uk/bmrs/api/v1{path}",
              params=dict(params, format="json"), timeout=120)
    r.raise_for_status()
    return r.json().get("data", [])


def _ex_chunk(zone, d0: date, d1: date, table):
    try:
        dem = {}
        for rec in _ex_get("/demand/outturn", {"settlementDateFrom": d0.isoformat(),
                                               "settlementDateTo": d1.isoformat()}):
            d = str(rec.get("settlementDate"))[:10]
            v = rec.get("initialDemandOutturn")
            if v is not None:
                dem.setdefault(d, []).append(v)
        mid = {}
        for rec in _ex_get("/balancing/pricing/market-index",
                           {"from": f"{d0}T00:00Z", "to": f"{d1}T23:59Z"}):
            d = str(rec.get("startTime"))[:10]
            if rec.get("price") is not None and (rec.get("volume") or 0) > 0:
                mid.setdefault(d, []).append((rec["price"], rec["volume"]))
        gen = {}
        for rec in _ex_get("/generation/actual/per-type",
                           {"from": f"{d0}T00:00Z", "to": f"{d1}T23:59Z"}):
            d = str(rec.get("startTime"))[:10]
            inner = rec.get("data") if isinstance(rec.get("data"), list) else [rec]
            w = sum((x.get("quantity") or 0) for x in inner if "Wind" in str(x.get("psrType")))
            s = sum((x.get("quantity") or 0) for x in inner if "Solar" in str(x.get("psrType")))
            g = sum((x.get("quantity") or 0) for x in inner)
            gen.setdefault(d, []).append((w, s, g))
        for d in set(dem) | set(mid):
            row = table.setdefault(d, {})
            if d in dem and len(dem[d]) >= 20:
                row["demand_gw"] = round(mean(dem[d]) / 1000, 2)
            if d in mid:
                sv = sum(v for _, v in mid[d])
                row["da_base"] = round(sum(p * v for p, v in mid[d]) / sv, 2)
            if d in gen and len(gen[d]) >= 20:
                row["wind_gw"] = round(mean(x[0] for x in gen[d]) / 1000, 2)
                row["solar_gw"] = round(mean(x[1] for x in gen[d]) / 1000, 2)
                row["gen_total_gw"] = round(mean(x[2] for x in gen[d]) / 1000, 2)
                if "demand_gw" in row:
                    row["ic_net_gw"] = round(row["demand_gw"] - row["gen_total_gw"], 2)
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("Elexon %s〜%s 失敗: %s", d0, d1, e)
        return False


def ensure_history(max_chunks: int = 50):
    """欠落期間を検出し、max_chunksまで埋める。毎日呼ばれ数日で遡及完了する。"""
    yday = date.today() - timedelta(days=1)
    used = 0
    for zone, cfg in FUND_ZONES.items():
        table = {d: dict(r) for d, r in _read(zone).items()}
        have = set(table)
        # 欠落日 → チャンク化 (EC=180日 / Elexon=25日)
        span = 180 if cfg["src"] == "ec" else 25
        missing = []
        d = HIST_START
        while d <= yday:
            if d.isoformat() not in have:
                missing.append(d)
            d += timedelta(days=1)
        if not missing:
            continue
        chunks, cur = [], [missing[0], missing[0]]
        for d in missing[1:]:
            if (d - cur[1]).days <= 3 and (d - cur[0]).days < span:
                cur[1] = d
            else:
                chunks.append(tuple(cur)); cur = [d, d]
        chunks.append(tuple(cur))
        chunks.sort(key=lambda c: c[0], reverse=True)  # 直近優先
        done = 0
        for d0, d1 in chunks:
            if used >= max_chunks:
                break
            ok = (_ec_chunk(zone, cfg, d0, d1, table) if cfg["src"] == "ec"
                  else _ex_chunk(zone, d0, d1, table))
            used += 1
            done += ok
        _write(zone, table)
        log.info("fundamentals %s: %d日保有 / 残り欠落チャンク %d",
                 zone, len(table), max(0, len(chunks) - done))
    log.info("fundamentals: 今回 %d チャンク取得", used)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ensure_history()
