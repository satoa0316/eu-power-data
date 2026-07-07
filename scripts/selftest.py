# -*- coding: utf-8 -*-
"""ネットワーク不要の自己テスト。設計書90シート「6. スポットチェック」を再現する。
実行: python scripts/selftest.py (全てOKなら exit 0)"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import config as C
import srmc
from label_marginal_fuel import classify_slot

bands = srmc.bands(dict(C.PLACEHOLDER_PRICES), "EUR", ["lignite", "ccgt", "coal", "ocgt"])
cap = {t: gw * 1000 for t, gw in C.ZONES["DE_LU"]["capacity_gw"].items()}

# 模擬発電 (90シート5章の趣旨): 通常時はガス8GW/褐炭6GW/石炭3GW稼働, OCGT非稼働
GEN_RUN = {"gas_total": 8000, "lignite": 6000, "coal": 3000}

cases = [
    # (説明, price, gen, nbr_min, 期待label, 期待unresolved)
    ("00:00 OCGT帯・OCGT非稼働・隣国価格なし → UNRESOLVED(ocgt)", 134.57, GEN_RUN, None, "ocgt", True),
    ("00:00 同上だが隣国収斂|Δ|1.5 → import_set",               134.57, GEN_RUN, 1.5,  "import_set", False),
    ("05:45 CCGT/石炭重複帯・両方稼働 → タイブレークで石炭",     101.84, GEN_RUN, None, "coal", False),
    ("09:30 4.22 → res_surplus",                                  4.22,  GEN_RUN, None, "res_surplus", False),
    ("13:30 負値 → res_surplus",                                 -1.20,  GEN_RUN, None, "res_surplus", False),
    ("18:45 146.43 OCGT帯・非稼働 → UNRESOLVED(ocgt)",          146.43, GEN_RUN, None, "ocgt", True),
    ("170.0 OCGT上限+5超 → scarcity",                            170.0,  GEN_RUN, None, "scarcity", False),
    ("60.0 帯の谷間・隣国収斂 → import_set",                      60.0,  GEN_RUN, 0.8,  "import_set", False),
]

ng = 0
for desc, p, gen, nbr, exp_l, exp_u in cases:
    st1, lbl, unres = classify_slot(p, bands, gen, cap, nbr)
    ok = (lbl == exp_l and unres == exp_u)
    print(f"{'OK' if ok else 'NG'}  {desc}  → stage1={st1} label={lbl} unresolved={unres}")
    ng += (not ok)

print(f"\nSRMC帯: {bands}")
sys.exit(1 if ng else 0)
