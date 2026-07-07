# -*- coding: utf-8 -*-
"""
【欧州電力分析】設定 — 出典: データ基盤設計書 90_検証データ記録 / 05_計算層定義 (2026-07-06)
全ての前提値は設計書と一致させること。変更したら設計書側にも反映する。
"""

# ---- 判定パラメータ (90シート「4. 判定パラメータ」) ----
TOL = 5.0             # SRMC帯の許容幅 ±EUR(or GBP)/MWh
SURPLUS_CEIL = 15.0   # これ以下は res_surplus
RUN_MIN_MW = 500.0    # Stage2: 稼働中とみなす最低出力
PARTLOAD_MAX = 0.92   # Stage2: 設備のこれ未満なら部分負荷 (=限界たり得る)
IMPORT_CONV = 2.0     # 輸入収斂: |DA自国 - DA隣国| < 2.0 で import_set
SCARCITY_MARGIN = TOL # DA > OCGT帯上限 + これ で scarcity

# ---- 技術前提 (90シート「3. 技術前提」/ 05シートC01b) ----
# eta: (高効率, 低効率) / ef: tCO2/MWh(th) / vom: 現地通貨/MWh / fuel: 燃料キー
TECH = {
    "lignite": {"eta": (0.43, 0.35), "ef": 0.364, "vom": 3.0, "fuel": "lignite"},
    "ccgt":    {"eta": (0.58, 0.47), "ef": 0.202, "vom": 2.0, "fuel": "gas"},
    "coal":    {"eta": (0.44, 0.36), "ef": 0.340, "vom": 3.5, "fuel": "coal"},
    "ocgt":    {"eta": (0.40, 0.30), "ef": 0.202, "vom": 2.0, "fuel": "gas"},
}
LIGNITE_FUEL_TH = 4.0      # EUR/MWh(th) 慣用値 (市場価格なし)
API2_KCAL_CONV = 8.141     # MWh(th)/t (6,000kcal/kg NAR)
THERM_TO_MWH = 0.0293071   # MWh/therm
CPS_GBP = 18.0             # GB Carbon Price Support 固定 £/t

# ---- ゾーン定義 ----
# capacity_gw は仮置き (本番は ENTSO-E installed capacity / OPSD で更新 → data/static/capacity_override.csv)
ZONES = {
    "DE_LU": {
        "source": "energy_charts",
        "ec_bzn": "DE-LU", "ec_country": "de",
        "tz": "Europe/Berlin", "currency": "EUR",
        "techs": ["lignite", "ccgt", "coal", "ocgt"],
        "capacity_gw": {"lignite": 14.0, "ccgt": 26.0, "coal": 7.0, "ocgt": 4.0},
        # 隣国 (energy-charts の bzn 名)。import_set 判定に使用
        "neighbors": ["FR", "NL", "BE", "AT", "CH", "CZ", "PL", "DK1", "DK2", "SE4", "NO2"],
    },
    "GB": {
        "source": "elexon",
        "tz": "Europe/London", "currency": "GBP",
        "techs": ["ccgt", "coal", "ocgt"],
        "capacity_gw": {"ccgt": 30.0, "coal": 1.0, "ocgt": 2.0},  # 仮置き。要更新
        # 隣国価格は energy-charts (EUR) → gbpeur で £換算して比較
        "neighbors": ["FR", "NL", "BE", "NO2", "DK1"],
    },
}

# energy-charts の production_type 名 → 技術キー のマッピング
# 注意: energy-charts/ENTSO-E ではガスは "Fossil gas" 1本で CCGT/OCGT の区別なし。
# → OCGT の Stage2 は「ガス出力が CCGT容量×OCGT_PROXY を超過」で代理判定 (要キャリブレーション)
EC_TYPE_MAP = {
    "Fossil brown coal / lignite": "lignite",
    "Fossil hard coal": "coal",
    "Fossil gas": "gas_total",
    "Fossil coal-derived gas": "gas_total",
}
ELEXON_TYPE_MAP = {
    "Fossil Gas": "gas_total",
    "Fossil Hard coal": "coal",
    "Fossil Oil": "oil",
}
OCGT_PROXY = 0.90  # gas_total > ccgt容量×これ → OCGT稼働とみなす代理閾値

# メリットオーダー: タイブレークは「稼働中候補のうち最高SRMC帯」(90シート)。
# 帯の中央値で比較するため順序テーブルは不要だが、同値時の安定ソート用に序列を定義。
MERIT_ORDER = ["lignite", "ccgt", "coal", "ocgt"]

# ---- 燃料価格CSV (04_Platts入力シートと同一列名) ----
PLATTS_COLUMNS = ["date", "ttf_da", "ttf_fm", "nbp_da", "nbp_fm", "psv_da", "pvb_da",
                  "the_da", "peg_da", "ztp_da", "jkm_fm", "api2_fm", "eua_dec",
                  "uka_dec", "brent", "eurusd", "gbpeur"]

# 仮置き価格 (90シート「2. 燃料・炭素・為替」— Platts実値と要差替)
PLACEHOLDER_PRICES = {
    "ttf_da": 32.0, "nbp_da": 78.0, "api2_fm": 105.0,
    "eua_dec": 78.0, "uka_dec": 45.0, "eurusd": 1.09, "gbpeur": 1.17,
}
