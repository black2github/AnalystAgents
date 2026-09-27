"""Гипотеза: у RKLB (архетип C) рост маржи ПОВЫШАЕТ P(loss>30) — переключение базы оценки revenue_bridge → FCF_multiple у порога
зрелости даёт обрыв стоимости. Проверка: три прогона по 30k путей — база, сдвиг узлов сервисной маржи −5 п.п. и +5 п.п.;
смотрим доли базы оценки и P(loss>30)."""
import copy
import json
import urllib.request
from pathlib import Path

import yaml

WS = Path("C:/openclaw-lab/data/workspace-invest"); PK = WS / "from_imma" / "HOOD_RKLB_Calibrations_v1"; URL = "http://127.0.0.1:18791/run"
spec = yaml.safe_load((WS / "methodology" / "Joint_Simulation_Layer_Schema_v1.0.yaml").read_text(encoding="utf-8"))
cal = yaml.safe_load((PK / "RKLB_mc_calibration_v1.0.yaml").read_text(encoding="utf-8"))
eq0 = yaml.safe_load((PK / "RKLB_calibration_v1.0.yaml").read_text(encoding="utf-8"))["calibration_v1.0"]["market"]["equity_value"]


def shift_margin(c, d):
    sm = c["cash_model"]["service_margin"]
    for k, v in sm.items():
        if isinstance(v, dict) and "distribution" in v:
            for kk in ("min", "mode", "max", "mean"):
                if kk in v:
                    v[kk] = round(float(v[kk]) + d, 6)
    return c


for label, d in (("base", 0.0), ("margin -5pp", -0.05), ("margin +5pp", 0.05)):
    c = shift_margin(copy.deepcopy(cal), d)
    req = urllib.request.Request(URL, data=json.dumps({"model": "company_mc", "inputs": {"calibration": c, "equity_value_0": eq0, "joint_layer_spec": spec, "paths": 30000, "convergence_check": False, "robustness": False}, "seed": 20260920, "save": False}).encode(), headers={"Content-Type": "application/json"})
    o = json.load(urllib.request.urlopen(req, timeout=1800))["outputs"]; b = o["base"]
    print(f"{label:12} P(loss>30) {b['downside']['P_loss_gt_30pct_5Y']:.3f} | medCAGR5 {b['return']['median_CAGR_5Y']:+.3f} | P2x {b['return']['P_2x_5Y']:.3f} | basis Y5 {json.dumps({k: round(v, 3) for k, v in b['valuation_basis_share']['Y5'].items() if v})} | Y8 {json.dumps({k: round(v, 3) for k, v in b['valuation_basis_share']['Y8'].items() if v})}")
