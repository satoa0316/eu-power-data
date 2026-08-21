# -*- coding: utf-8 -*-
"""
予報アーカイブ (②の要件「当時何が見えていたか」の蓄積)。
実績は後から遡及できるが予報は取り逃すと消えるため、日次で必ず保存する。
label_marginal_fuel.main() の末尾から呼ばれる (ワークフロー変更不要)。失敗しても本体は止めない。

保存先: data/raw/forecasts/{kind}_{zone}.csv (追記・重複排除)
全行に publish_time (API側の発行時刻) と captured_at (取得時刻UTC) を付与。
"""
import csv
import logging
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "raw" / "forecasts"
log = logging.getLogger("fcst")
S = requests.Session()
S.headers["User-Agent"] = "eu-power-data/2.0"


def _append_dedupe(path: Path, rows, keys):
    if not rows:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    seen = {}
    cols = list(rows[0].keys())
    if path.exists():
        with open(path, newline="", encoding="utf-8") as f:
            rd = csv.DictReader(f)
            cols = rd.fieldnames or cols
            for r in rd:
                seen[tuple(r.get(k, "") for k in keys)] = r
    for r in rows:
        r = {k: ("" if v is None else str(v)) for k, v in r.items()}
        seen[tuple(r.get(k, "") for k in keys)] = r
        for c in r:
            if c not in cols:
                cols.append(c)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, restval="", extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(seen.values(), key=lambda r: tuple(r.get(k, "") for k in keys)))
    return len(rows)


def _elexon(path, params=None):
    r = S.get(f"https://data.elexon.co.uk/bmrs/api/v1{path}",
              params=dict(params or {}, format="json"), timeout=60)
    r.raise_for_status()
    j = r.json()
    return j.get("data", j) if isinstance(j, dict) else j


def gb_demand_forecast(cap):
    """NDF/TSDF 最新版 (30分コマ、publishTime付き)"""
    rows = []
    for kind, ep in [("NDF", "/forecast/demand/day-ahead/latest"),
                     ("TSDF", "/forecast/demand/total/day-ahead")]:
        try:
            for rec in _elexon(ep) or []:
                rows.append({"kind": kind,
                             "target_time": rec.get("startTime") or rec.get("settlementDate"),
                             "settlement_period": rec.get("settlementPeriod"),
                             "value_mw": rec.get("demand") or rec.get("transmissionSystemDemand")
                                         or rec.get("nationalDemand"),
                             "publish_time": rec.get("publishTime"),
                             "captured_at": cap})
        except Exception as e:  # noqa: BLE001
            log.warning("GB需要予測 %s 失敗: %s", kind, e)
    return rows


def gb_wind_forecast(cap):
    rows = []
    try:
        for rec in _elexon("/forecast/generation/wind/latest") or []:
            rows.append({"target_time": rec.get("startTime"),
                         "value_mw": rec.get("generation"),
                         "publish_time": rec.get("publishTime"),
                         "captured_at": cap})
    except Exception as e:  # noqa: BLE001
        log.warning("GB風力予測 失敗: %s", e)
    return rows


def gb_indgen_margin(cap):
    """INDGEN/MELNGC (日先 需給指標)"""
    rows = []
    for kind, ep in [("INDGEN", "/forecast/indicated/day-ahead"),
                     ("MELNGC", "/forecast/availability/daily")]:
        try:
            for rec in _elexon(ep) or []:
                v = (rec.get("indicatedGeneration") or rec.get("outputUsable")
                     or rec.get("marginMw") or rec.get("value"))
                rows.append({"kind": kind, "target_time": rec.get("startTime") or rec.get("forecastDate"),
                             "settlement_period": rec.get("settlementPeriod"),
                             "value_mw": v, "publish_time": rec.get("publishTime"),
                             "captured_at": cap})
        except Exception as e:  # noqa: BLE001
            log.warning("GB %s 失敗: %s", kind, e)
    return rows


def de_res_forecast(cap):
    """DE 風力・太陽光の予測 (energy-charts)。エンドポイント差異があればログで報告される。"""
    rows = []
    try:
        r = S.get("https://api.energy-charts.info/public_power_forecast",
                  params={"country": "de", "production_type": "solar"}, timeout=60)
        for pt, name in [(r, "solar")]:
            if pt.status_code == 200:
                j = pt.json()
                for t, v in zip(j.get("unix_seconds", []), j.get("forecast_values", j.get("data", []))):
                    rows.append({"kind": name, "target_ts": t, "value_mw": v,
                                 "publish_time": j.get("forecast_production_time", ""),
                                 "captured_at": cap})
        for name in ["wind_onshore", "wind_offshore"]:
            r2 = S.get("https://api.energy-charts.info/public_power_forecast",
                       params={"country": "de", "production_type": name}, timeout=60)
            if r2.status_code == 200:
                j = r2.json()
                for t, v in zip(j.get("unix_seconds", []), j.get("forecast_values", j.get("data", []))):
                    rows.append({"kind": name, "target_ts": t, "value_mw": v,
                                 "publish_time": j.get("forecast_production_time", ""),
                                 "captured_at": cap})
    except Exception as e:  # noqa: BLE001
        log.warning("DE予測取得 失敗 (エンドポイント要確認): %s", e)
    return rows


def run():
    cap = datetime.now(timezone.utc).isoformat(timespec="seconds")
    n = 0
    n += _append_dedupe(OUT / "demand_fcst_GB.csv", gb_demand_forecast(cap),
                        ["kind", "target_time", "publish_time"])
    n += _append_dedupe(OUT / "wind_fcst_GB.csv", gb_wind_forecast(cap),
                        ["target_time", "publish_time"])
    n += _append_dedupe(OUT / "margin_fcst_GB.csv", gb_indgen_margin(cap),
                        ["kind", "target_time", "publish_time"])
    n += _append_dedupe(OUT / "res_fcst_DE.csv", de_res_forecast(cap),
                        ["kind", "target_ts", "publish_time"])
    log.info("予報アーカイブ: %d行 追加", n)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
