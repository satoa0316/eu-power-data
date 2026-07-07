# -*- coding: utf-8 -*-
"""
① 限界燃料ラベリング 本体 (C01c実装)
2段判定: Stage1=SRMC帯照合(±TOL) → Stage2=稼働裏取り(>500MW かつ <設備92%)
+ 輸入収斂判定 (|ΔDA|<2€ → import_set) + scarcity/res_surplus。

使い方:
  python scripts/label_marginal_fuel.py --start 2026-06-01 --end 2026-07-05 --zones DE_LU,GB
引数なし → 昨日1日分・全ゾーン (日次cron用)。

出力:
  data/mart/labels_{zone}.csv          コマ別ラベル (追記・重複排除)
  data/mart/daily_shares_{zone}.csv    日次シェア+統計
  docs/data/marginal_fuel_daily_{zone}.json  ダッシュボード用 (全履歴)
"""
import argparse
import csv
import json
import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent))
import config as C  # noqa: E402
import srmc  # noqa: E402
import fetch_energy_charts as ec  # noqa: E402
import fetch_elexon as ex  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
MART = ROOT / "data" / "mart"
DOCS = ROOT / "docs" / "data"
log = logging.getLogger("label")
WD_JP = "月火水木金土日"


# ---------------- 判定ロジック ----------------
def classify_slot(price, bands, gen, capacity_mw, neighbor_delta_min):
    """1コマの判定。返り値: (stage1, label, unresolved:bool)
    gen: {"lignite": MW, "coal": MW, "gas_total": MW} (無いキーはNone扱い)
    neighbor_delta_min: 隣国価格との最小絶対差 (Noneなら判定不能)"""
    if price <= C.SURPLUS_CEIL:
        return "res_surplus", "res_surplus", False

    ocgt_hi = bands.get("ocgt", [0, 1e9])[1]
    if price > ocgt_hi + C.SCARCITY_MARGIN:
        return "scarcity", "scarcity", False

    # Stage1: 帯照合
    cands = [t for t, (lo, hi) in bands.items() if lo - C.TOL <= price <= hi + C.TOL]

    # Stage2: 稼働裏取り
    def running(t):
        cap = capacity_mw.get(t)
        if t in ("ccgt", "ocgt"):
            g = gen.get("gas_total")
            if g is None:
                return None  # 裏取り不能
            if t == "ccgt":
                return g > C.RUN_MIN_MW and (cap is None or g < cap * C.PARTLOAD_MAX)
            ccgt_cap = capacity_mw.get("ccgt") or 0
            return g > ccgt_cap * C.OCGT_PROXY  # 代理判定 (config参照)
        g = gen.get(t)
        if g is None:
            return None
        return g > C.RUN_MIN_MW and (cap is None or g < cap * C.PARTLOAD_MAX)

    confirmed = [t for t in cands if running(t)]
    if confirmed:
        # タイブレーク: 最高SRMC帯 (帯中央値) = メリットオーダー論理
        best = max(confirmed, key=lambda t: (bands[t][0] + bands[t][1]) / 2)
        stage1 = "|".join(cands)
        return stage1, best, False

    # 帯内だが該当機非稼働 / 帯の谷間 → 輸入収斂チェック
    if neighbor_delta_min is not None and neighbor_delta_min < C.IMPORT_CONV:
        return "|".join(cands) or "gap", "import_set", False

    # UNRESOLVED: ラベルは最近傍の帯 (プロトタイプ準拠: 白帯表示用)
    if cands:
        guess = max(cands, key=lambda t: (bands[t][0] + bands[t][1]) / 2)
    else:
        guess = min(bands, key=lambda t: min(abs(price - bands[t][0]), abs(price - bands[t][1])))
    return "|".join(cands) or "gap", guess, True


# ---------------- ゾーン別データ取得 ----------------
def slots_de_lu(day: str, zone_cfg):
    tz = ZoneInfo(zone_cfg["tz"])
    d0 = date.fromisoformat(day)
    d1 = (d0 + timedelta(days=1)).isoformat()
    ts, pr, _ = ec.da_price(zone_cfg["ec_bzn"], day, d1)
    gts, gtypes = ec.public_power(zone_cfg["ec_country"], day, d1)
    # 発電を技術キーへ集約
    gen_by_ts = {}
    agg = {}
    for name, series in gtypes.items():
        k = C.EC_TYPE_MAP.get(name)
        if k:
            agg.setdefault(k, []).append(series)
    for i, t in enumerate(gts):
        gen_by_ts[t] = {k: sum((s[i] or 0) for s in ss if s[i] is not None)
                        for k, ss in agg.items()}
    gser = sorted(gen_by_ts)

    def gen_at(t):  # 直近以前の発電コマ
        import bisect
        j = bisect.bisect_right(gser, t) - 1
        return gen_by_ts[gser[j]] if j >= 0 else {}

    nbr = {b: ec.da_price_safe(b, day, d1) for b in zone_cfg["neighbors"]}
    nbr = {b: m for b, m in nbr.items() if m}

    out = []
    for t, p in zip(ts, pr):
        if p is None:
            continue
        loc = datetime.fromtimestamp(t, tz)
        if loc.date().isoformat() != day:
            continue
        deltas = [abs(p - m[t]) for m in nbr.values() if m.get(t) is not None]
        out.append({"ts": t, "local": loc.isoformat(), "price": float(p),
                    "gen": gen_at(t), "nbr_min": min(deltas) if deltas else None})
    return out


def slots_gb(day: str, zone_cfg, fx):
    tz = ZoneInfo(zone_cfg["tz"])
    prices = ex.mid_price(day)
    gens = ex.gen_per_type(day)
    d0 = date.fromisoformat(day)
    d1 = (d0 + timedelta(days=1)).isoformat()
    nbr = {b: ec.da_price_safe(b, day, d1) for b in zone_cfg["neighbors"]}
    nbr = {b: m for b, m in nbr.items() if m}
    gbpeur = fx.get("gbpeur", 1.17)

    gkeys = sorted(gens)

    def gen_at(iso):
        import bisect
        j = bisect.bisect_right(gkeys, iso) - 1
        if j < 0:
            return {}
        raw = gens[gkeys[j]]
        out = {}
        for name, mw in raw.items():
            k = C.ELEXON_TYPE_MAP.get(name)
            if k and mw is not None:
                out[k] = out.get(k, 0) + mw
        return out

    out = []
    for iso, p in sorted(prices.items()):
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        loc = dt.astimezone(tz)
        if loc.date().isoformat() != day:
            continue
        t = int(dt.timestamp())
        deltas = []
        for m in nbr.values():
            v = m.get(t)
            if v is not None:
                deltas.append(abs(p - v / gbpeur))  # EUR→£換算して比較
        out.append({"ts": t, "local": loc.isoformat(), "price": float(p),
                    "gen": gen_at(iso), "nbr_min": min(deltas) if deltas else None})
    return out


# ---------------- 出力 ----------------
def merge_csv(path: Path, rows, key):
    """既存CSVと結合し key で重複排除して書き戻す。"""
    existing = {}
    if path.exists():
        with open(path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                existing[r[key]] = r
    for r in rows:
        existing[str(r[key])] = {k: str(v) for k, v in r.items()}
    allrows = sorted(existing.values(), key=lambda r: r[key])
    cols = list(rows[0].keys()) if rows else list(next(iter(existing.values())).keys())
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(allrows)


def jp_date(day: str) -> str:
    d = date.fromisoformat(day)
    return f"{day} ({WD_JP[d.weekday()]})"


def build_dashboard_json(zone, labels_csv: Path, out_json: Path, bands, prices):
    days = {}
    with open(labels_csv, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            days.setdefault(r["date"], []).append(r)
    payload_days = []
    for day in sorted(days):
        rows = sorted(days[day], key=lambda r: r["local"])
        pr = [round(float(r["price"]), 2) for r in rows]
        lb = [r["label"] for r in rows]
        un = [r["unresolved"] == "True" for r in rows]
        n = len(rows)
        shares = {l: round(lb.count(l) / n, 3) for l in sorted(set(lb))}
        payload_days.append({
            "date": jp_date(day),
            "qh": {"price": pr, "label": lb, "unresolved": un},
            "shares": shares,
            "stats": {"da_avg": round(sum(pr) / n, 1), "da_min": min(pr),
                      "da_max": max(pr), "unresolved_rate": round(sum(un) / n, 3)},
        })
    payload = {"zone": zone.replace("_", "-"),
               "fuel_assumptions": {"ttf": prices.get("ttf_da"), "api2": prices.get("api2_fm"),
                                    "eua": prices.get("eua_dec"), "uka": prices.get("uka_dec"),
                                    "note": prices.get("_source", "")},
               "bands": bands, "days": payload_days}
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    log.info("ダッシュボードJSON更新: %s (%d日分)", out_json, len(payload_days))


# ---------------- メイン ----------------
def process(zone: str, day: str, fuel_table):
    cfg = C.ZONES[zone]
    prices = srmc.prices_for(day, fuel_table)
    bands = srmc.bands(prices, cfg["currency"], cfg["techs"])
    cap_mw = {t: gw * 1000 for t, gw in cfg["capacity_gw"].items()}
    slots = slots_de_lu(day, cfg) if cfg["source"] == "energy_charts" else slots_gb(day, cfg, prices)
    if not slots:
        raise RuntimeError(f"{zone} {day}: 価格コマが0件 (未公表 or API仕様変更?)")
    rows = []
    for s in slots:
        st1, lbl, unres = classify_slot(s["price"], bands, s["gen"], cap_mw, s["nbr_min"])
        rows.append({"ts_utc": s["ts"], "date": day, "local": s["local"],
                     "price": s["price"], "stage1": st1, "label": lbl,
                     "unresolved": unres,
                     "gas_total_mw": s["gen"].get("gas_total", ""),
                     "lignite_mw": s["gen"].get("lignite", ""),
                     "coal_mw": s["gen"].get("coal", ""),
                     "nbr_delta_min": "" if s["nbr_min"] is None else round(s["nbr_min"], 2),
                     "fuel_px_src": prices["_source"]})
    merge_csv(MART / f"labels_{zone}.csv", rows, "ts_utc")
    n = len(rows)
    unres_rate = sum(1 for r in rows if r["unresolved"]) / n
    imp = sum(1 for r in rows if r["label"] == "import_set") / n
    share_row = {"date": day, "n_slots": n,
                 "unresolved_rate": round(unres_rate, 3), "import_set_share": round(imp, 3)}
    for l in sorted({r["label"] for r in rows}):
        share_row[f"share_{l}"] = round(sum(1 for r in rows if r["label"] == l) / n, 3)
    merge_csv(MART / f"daily_shares_{zone}.csv", [share_row], "date")
    build_dashboard_json(zone, MART / f"labels_{zone}.csv",
                         DOCS / f"marginal_fuel_daily_{zone}.json", bands, prices)
    log.info("%s %s: %dコマ / UNRESOLVED %.0f%% / import_set %.0f%% / 帯=%s",
             zone, day, n, unres_rate * 100, imp * 100, bands)


def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    yday = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()
    ap.add_argument("--start", default=yday)
    ap.add_argument("--end", default=None)
    ap.add_argument("--zones", default=",".join(C.ZONES))
    ap.add_argument("--platts", default=os.environ.get("PLATTS_FILE",
                    str(ROOT / "data" / "manual" / "platts_prices.csv")))
    a = ap.parse_args()
    end = a.end or a.start
    fuel_table = srmc.load_fuel_prices(Path(a.platts))
    zones = [z.strip() for z in a.zones.split(",") if z.strip()]

    ok, fail = 0, 0
    d = date.fromisoformat(a.start)
    while d <= date.fromisoformat(end):
        for z in zones:
            try:
                process(z, d.isoformat(), fuel_table)
                ok += 1
            except Exception:  # noqa: BLE001
                log.exception("失敗: %s %s → 続行", z, d)
                fail += 1
        d += timedelta(days=1)

    # DE_LUはダッシュボード既定ファイル名にもコピー
    de = DOCS / "marginal_fuel_daily_DE_LU.json"
    if de.exists():
        (DOCS / "marginal_fuel_daily.json").write_text(de.read_text(encoding="utf-8"),
                                                       encoding="utf-8")
    log.info("完了: 成功 %d / 失敗 %d", ok, fail)
    sys.exit(0 if ok > 0 or fail == 0 else 1)


if __name__ == "__main__":
    main()
