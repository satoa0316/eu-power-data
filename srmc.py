# -*- coding: utf-8 -*-
"""
Elexon Insights API フェッチャー (J02ジョブ相当)。キー不要。
- 価格: Market Index (MID, N2EX/APX 出来高加重, £/MWh, 30分)
- 発電: actual per-type (B1620, 30分, psrType別)
初回実行でレスポンス形式が想定と違う場合はログを貼れば即修正 (引き継ぎ.md 6章の運用)。
"""
import logging
import time
from collections import defaultdict

import requests

BASE = "https://data.elexon.co.uk/bmrs/api/v1"
log = logging.getLogger("elexon")
_session = requests.Session()
_session.headers["User-Agent"] = "eu-power-data/1.0 (github actions; analysis pipeline)"


def _get(path: str, params: dict, retries: int = 4):
    url = f"{BASE}{path}"
    p = dict(params, format="json")
    for i in range(retries):
        try:
            r = _session.get(url, params=p, timeout=60)
            if r.status_code == 200:
                return r.json()
            log.warning("HTTP %s %s (try %d): %s", r.status_code, path, i + 1, r.text[:200])
        except requests.RequestException as e:
            log.warning("接続エラー %s: %s (try %d)", path, e, i + 1)
        time.sleep(3 * (i + 1))
    raise RuntimeError(f"Elexon取得失敗: {path} {params}")


def mid_price(day_iso: str):
    """当該暦日(ロンドン時間)のMID出来高加重価格。返り値: {startTime(ISO): £/MWh}"""
    j = _get("/balancing/pricing/market-index",
             {"from": f"{day_iso}T00:00Z", "to": f"{day_iso}T23:59Z"})
    acc = defaultdict(lambda: [0.0, 0.0])  # start -> [Σp*v, Σv]
    for rec in j.get("data", []):
        st = rec.get("startTime")
        pr, vol = rec.get("price"), rec.get("volume") or 0.0
        if st is None or pr is None:
            continue
        acc[st][0] += pr * (vol or 1.0)
        acc[st][1] += (vol or 1.0)
    return {st: (s / v) for st, (s, v) in acc.items() if v > 0}


def gen_per_type(day_iso: str):
    """当該暦日の発電実績 per-type。返り値: {startTime: {psrType: MW}}"""
    j = _get("/generation/actual/per-type",
             {"from": f"{day_iso}T00:00Z", "to": f"{day_iso}T23:59Z"})
    out = defaultdict(dict)
    for rec in j.get("data", []):
        st = rec.get("startTime")
        inner = rec.get("data")
        if isinstance(inner, list):  # {startTime, data:[{psrType, quantity}]}
            for d in inner:
                out[st][d.get("psrType")] = d.get("quantity")
        else:  # フラット形式 {startTime, psrType, quantity}
            out[st][rec.get("psrType")] = rec.get("quantity")
    return out
