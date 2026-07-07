# -*- coding: utf-8 -*-
"""
energy-charts API フェッチャー (J01ジョブ相当)。キー不要・CC BY 4.0。
出典クレジット: Bundesnetzagentur | SMARD.de / energy-charts.info (CC BY 4.0)
"""
import logging
import time

import requests

BASE = "https://api.energy-charts.info"
log = logging.getLogger("ec")
_session = requests.Session()
_session.headers["User-Agent"] = "eu-power-data/1.0 (github actions; analysis pipeline)"


def _get(path: str, params: dict, retries: int = 4):
    url = f"{BASE}{path}"
    for i in range(retries):
        try:
            r = _session.get(url, params=params, timeout=60)
            if r.status_code == 200:
                return r.json()
            log.warning("HTTP %s %s %s (try %d)", r.status_code, path, params, i + 1)
        except requests.RequestException as e:
            log.warning("接続エラー %s %s: %s (try %d)", path, params, e, i + 1)
        time.sleep(3 * (i + 1))
    raise RuntimeError(f"energy-charts取得失敗: {path} {params}")


def da_price(bzn: str, start: str, end: str):
    """DA価格。返り値: (unix_seconds[], price[], unit)"""
    j = _get("/price", {"bzn": bzn, "start": start, "end": end})
    return j["unix_seconds"], j["price"], j.get("unit", "EUR/MWh")


def da_price_safe(bzn: str, start: str, end: str):
    """隣国価格用: 失敗しても None を返して続行。"""
    try:
        ts, pr, _ = da_price(bzn, start, end)
        return dict(zip(ts, pr))
    except Exception as e:  # noqa: BLE001
        log.warning("隣国 %s の価格取得失敗 → import_set判定から除外: %s", bzn, e)
        return None


def public_power(country: str, start: str, end: str):
    """発電ミックス実績。返り値: (unix_seconds[], {production_type_name: [MW,...]})"""
    j = _get("/public_power", {"country": country, "start": start, "end": end})
    types = {pt["name"]: pt["data"] for pt in j["production_types"]}
    return j["unix_seconds"], types
