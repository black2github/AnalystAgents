"""Диагностика стресс-чувствительности по старой абсолютной сетке (spec v1.1.2: не критерий, только диагностика):
±10 п.п. роста, ±5 п.п. маржи, ±20 % мультипликатора, 100k путей; save=false (справочный прогон)."""
import copy
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

import yaml

WS = Path("C:/openclaw-lab/data/workspace-invest"); PK = WS / "from_imma" / "MSFT_PLTR_NET_ETN_Calibrations_v1"; URL = "http://127.0.0.1:18791/run"


def post(payload):
    req = urllib.request.Request(URL, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=3600) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        print("HTTP", e.code, body[:1500])
        return {"error": body[:300]}


spec = yaml.safe_load((WS / "methodology" / "Joint_Simulation_Layer_Schema_v1.0.yaml").read_text(encoding="utf-8"))
for tk in [a for a in sys.argv[1:] if a in ("MSFT", "PLTR", "NET", "ETN")] or ["MSFT", "PLTR", "NET", "ETN"]:
    cal = yaml.safe_load((WS / "from_imma" / "ETN_mc_v1.0.1" / f"{tk}_mc_calibration_v1.0.1.yaml").read_text(encoding="utf-8"))
    eq0 = yaml.safe_load((PK / f"{tk}_calibration_v1.0.yaml").read_text(encoding="utf-8"))["calibration_v1.0"]["market"]["equity_value"]
    c = copy.deepcopy(cal)
    rt = c.setdefault("robustness_tests", {}).setdefault("Scenario_Robustness", {})
    rt["perturbations"] = {"growth_modes_pp": [-0.10, 0.10], "margin_nodes_pp": [-0.05, 0.05], "terminal_multiple_pct": [-0.20, 0.20]}
    r = post({"model": "company_mc", "inputs": {"calibration": c, "equity_value_0": eq0, "joint_layer_spec": spec, "paths": 100000, "convergence_check": False, "robustness": True, "robustness_paths": 100000}, "seed": 20260920, "save": True})
    rb = (r.get("outputs") or {}).get("robustness") or {}
    print(f"{tk} v1.0.1 стресс-диагностика (старая сетка, 100k, 2.3.1): знак {rb.get('same_sign_share')}, допуск {rb.get('within_delta_tolerance_share')} | " +
          "; ".join(f"{x['perturbation']}{x['value']:+}: ΔP2x {x['dP_2x_5Y']:+.3f} ΔPl30 {x['dP_loss_gt_30pct_5Y']:+.3f} medCAGR {x['median_CAGR_5Y']:+.3f}" for x in rb.get("runs", [])))
    if r.get("error"):
        print("ERROR", r["error"])
