# -*- coding: utf-8 -*-
"""
Stage A: 日次ベースロード回帰 (月次モデルの変数セットを日次化)。
- 純Python実装 (依存ライブラリなし): 標準化 + Ridge (正規方程式をガウス消去)
- ウォークフォワード: 毎月初に拡大窓で再学習 → 当月を予測 (最低12ヶ月学習後に開始)
- ベンチマーク: persistence(前日値) / 前月平均 / ガス単回帰
- 平常日 = TTF<80 EUR かつ 前日比±30%以内 (検証ルール④で合意)
- 燃料 (Platts) は PLATTS_FILE(Secret) → data/manual からメモリ結合。コミットしない。
出力: docs/data/model_{zone}.json (β・感応度・WF予測列・指標・トルネード)
"""
import csv
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import srmc  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
log = logging.getLogger("model")
FEATS = ["gas", "carbon", "wind_gw", "solar_gw", "demand_gw", "ic_net_gw",
         "storage_pct", "sin_doy", "cos_doy"]
RIDGE_L = 1.0
MIN_TRAIN = 360
NORMAL_TTF = 80.0
NORMAL_JUMP = 0.30


# ---------- 純Python線形代数 ----------
def solve(A, b):
    n = len(A)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(M[r][c]))
        M[c], M[p] = M[p], M[c]
        if abs(M[c][c]) < 1e-12:
            return None
        for r in range(n):
            if r != c:
                f = M[r][c] / M[c][c]
                for k in range(c, n + 1):
                    M[r][k] -= f * M[c][k]
    return [M[i][n] / M[i][i] for i in range(n)]


def ridge_fit(X, y, lam=RIDGE_L):
    n, k = len(X), len(X[0])
    XtX = [[sum(X[r][i] * X[r][j] for r in range(n)) + (lam if i == j else 0)
            for j in range(k)] for i in range(k)]
    Xty = [sum(X[r][i] * y[r] for r in range(n)) for i in range(k)]
    return solve(XtX, Xty)


def zstats(v):
    m = sum(v) / len(v)
    s = (sum((x - m) ** 2 for x in v) / len(v)) ** 0.5
    return m, (s if s > 1e-9 else 1.0)


# ---------- データ ----------
def load_fuel_table():
    path = os.environ.get("PLATTS_FILE", str(ROOT / "data" / "manual" / "platts_prices.csv"))
    return srmc.load_fuel_prices(Path(path))


def load_features(zone, fuel_table):
    p = ROOT / "data" / "mart" / f"features_daily_{zone}.csv"
    if not p.exists():
        return []
    cur = "GBP" if zone == "GB" else "EUR"
    rows = []
    with open(p, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            d = r["date"]
            fp = srmc.prices_for(d, fuel_table)
            if fp["_source"] == "placeholder":
                continue  # 燃料不明日は学習に使わない
            src_day = fp["_source"].split(" ")[0]
            if abs((_ord(d) - _ord(src_day))) > 7:
                continue  # ffillが7日超なら除外 (古い燃料値の混入防止)
            row = {"date": d, "y": float(r["da_base"]),
                   "gas": srmc.fuel_th("gas", fp, cur),
                   "carbon": srmc.carbon_price(fp, cur),
                   "ttf": fp["ttf_da"]}
            for k in ["wind_gw", "solar_gw", "demand_gw", "ic_net_gw", "storage_pct",
                      "sin_doy", "cos_doy"]:
                row[k] = float(r[k]) if r.get(k) not in ("", None) else None
            rows.append(row)
    return rows


def _ord(d):
    from datetime import date
    return date.fromisoformat(d).toordinal()


# ---------- 学習・検証 ----------
def run_zone(zone, fuel_table):
    data = load_features(zone, fuel_table)
    if len(data) < MIN_TRAIN + 30:
        log.info("%s: データ不足 (%d日) → スキップ", zone, len(data))
        return None
    # 使う特徴 = 学習期間の80%以上で値があるもの
    usable = [f for f in FEATS if f in ("gas", "carbon", "sin_doy", "cos_doy") or
              sum(1 for r in data if r.get(f) is not None) / len(data) > 0.8]
    # 欠損はffill
    lastv = {}
    for r in data:
        for f in usable:
            if r.get(f) is None:
                r[f] = lastv.get(f)
            else:
                lastv[f] = r[f]
    data = [r for r in data if all(r.get(f) is not None for f in usable)]

    months = sorted({r["date"][:7] for r in data})
    preds = []
    beta_phys_last, mu_last = {}, {}
    for mi, m in enumerate(months):
        train = [r for r in data if r["date"][:7] < m]
        test = [r for r in data if r["date"][:7] == m]
        if len(train) < MIN_TRAIN or not test:
            continue
        stats = {f: zstats([r[f] for r in train]) for f in usable}
        my, sy = zstats([r["y"] for r in train])
        X = [[(r[f] - stats[f][0]) / stats[f][1] for f in usable] + [1.0] for r in train]
        yv = [(r["y"] - my) / sy for r in train]
        beta = ridge_fit(X, yv)
        if beta is None:
            continue
        # ガス単回帰ベンチ
        gX = [[(r["gas"] - stats["gas"][0]) / stats["gas"][1], 1.0] for r in train]
        gb = ridge_fit(gX, yv, 0.0)
        prev_month_avg = (sum(r["y"] for r in train[-30:]) / min(30, len(train)))
        for i, r in enumerate(test):
            x = [(r[f] - stats[f][0]) / stats[f][1] for f in usable] + [1.0]
            yhat = sum(b * v for b, v in zip(beta, x)) * sy + my
            gyhat = (gb[0] * (r["gas"] - stats["gas"][0]) / stats["gas"][1] + gb[1]) * sy + my
            prev = test[i - 1]["y"] if i > 0 else train[-1]["y"]
            normal = (r["ttf"] < NORMAL_TTF and abs(r["y"] - prev) / max(abs(prev), 1) < NORMAL_JUMP)
            preds.append({"date": r["date"], "y": r["y"], "pred": round(yhat, 2),
                          "persist": prev, "pmavg": round(prev_month_avg, 2),
                          "gasonly": round(gyhat, 2), "normal": normal})
        beta_phys_last = {f: beta[j] * sy / stats[f][1] for j, f in enumerate(usable)}
        mu_last = {f: stats[f][0] for f in usable}

    if not preds:
        return None

    def mae(key, subset):
        e = [abs(p["y"] - p[key]) for p in subset]
        return round(sum(e) / len(e), 2) if e else None
    allp = preds
    norm = [p for p in preds if p["normal"]]
    metrics = {
        "n_days": len(allp), "n_normal": len(norm),
        "mae_all": {k: mae(k, allp) for k in ["pred", "persist", "pmavg", "gasonly"]},
        "mae_normal": {k: mae(k, norm) for k in ["pred", "persist", "pmavg", "gasonly"]},
        "period": [allp[0]["date"], allp[-1]["date"]],
        "features_used": list(beta_phys_last.keys()),
    }
    tornado = [{"var": f, "plus10": round(beta_phys_last[f] * mu_last[f] * 0.10, 2),
                "beta_phys": round(beta_phys_last[f], 4)}
               for f in beta_phys_last if f not in ("sin_doy", "cos_doy")]
    tornado.sort(key=lambda t: -abs(t["plus10"]))
    out = {"zone": zone, "stage": "A (日次・変数は月次モデル同等)",
           "metrics": metrics, "tornado": tornado,
           "walkforward": {"dates": [p["date"] for p in preds][-400:],
                           "actual": [p["y"] for p in preds][-400:],
                           "pred": [p["pred"] for p in preds][-400:]},
           "note": "学習=Secret燃料カバー期間。2022危機期はSecret圧縮対応後に拡張 (合意済み)。"}
    op = ROOT / "docs" / "data" / f"model_{zone}.json"
    op.parent.mkdir(parents=True, exist_ok=True)
    op.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    log.info("%s StageA: 全日MAE model %.2f vs persist %.2f | 平常日 model %.2f vs persist %.2f (n=%d/%d) 特徴=%s",
             zone, metrics["mae_all"]["pred"], metrics["mae_all"]["persist"],
             metrics["mae_normal"]["pred"] or -1, metrics["mae_normal"]["persist"] or -1,
             len(norm), len(allp), metrics["features_used"])
    return metrics


def run():
    fuel = load_fuel_table()
    for zone in ["GB", "DE_LU", "FR", "NL", "BE", "ES", "IT"]:
        try:
            run_zone(zone, fuel)
        except Exception:  # noqa: BLE001
            log.exception("model %s 失敗 → 続行", zone)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
