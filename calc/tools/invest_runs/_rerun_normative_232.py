"""Перепрогон нормативных company_mc для 8 калиброванных компаний на движке 2.3.2 (собственные розыгрыши от (seed, ticker)):
калибровка — интегрированная (portfolio/<tk>/mc_calibration_*.yaml, последняя версия), equity_value_0 — из прежнего нормативного
прогона (та же рыночная база), seed 20260920, 500k, robustness 100k, store_paths. Печатает сравнение с прежним прогоном."""
import glob
import json
import sys
import urllib.request
from pathlib import Path

import yaml

WS = Path("C:/openclaw-lab/data/workspace-invest"); URL = "http://127.0.0.1:18791/run"
PREV = {"SPCX": "20260923T143532Z-company_mc-0484ce", "NBIS": "20260923T143929Z-company_mc-28c1e0", "NVDA": "20260923T144500Z-company_mc-4a7d0d",
        "HOOD": "20260923T211400Z-company_mc-6fb7ec", "RKLB": "20260923T211620Z-company_mc-dbbce2", "LLY": "20260923T220341Z-company_mc-e5a5c8",
        "META": "20260924T062553Z-company_mc-410567", "ASML": "20260924T062843Z-company_mc-7106fc"}
FOLDER = {"SPCX": "spacex"}
TKS = [a for a in sys.argv[1:] if a in PREV] or list(PREV)
spec = yaml.safe_load((WS / "methodology" / "Joint_Simulation_Layer_Schema_v1.0.yaml").read_text(encoding="utf-8"))


def post(payload):
    req = urllib.request.Request(URL, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=7200))


for tk in TKS:
    fd = WS / "portfolio" / FOLDER.get(tk, tk.lower())
    cands = sorted(glob.glob(str(fd / "mc_calibration_v*.yaml")), key=lambda p: [int(x) for x in Path(p).stem.split("_v")[-1].split(".")])
    cal_path = Path(cands[-1]); cal = yaml.safe_load(cal_path.read_text(encoding="utf-8"))
    prev = json.load(open(WS / "portfolio/_runs" / f"{PREV[tk]}.json", encoding="utf-8")); E0 = prev["inputs"]["equity_value_0"]; pb = prev["outputs"]["base"]
    r = post({"model": "company_mc", "inputs": {"calibration": cal, "equity_value_0": E0, "joint_layer_spec": spec, "convergence_check": True, "robustness": True, "robustness_paths": 100000, "store_paths": True}, "seed": 20260920, "save": True})
    o = r.get("outputs", {}); b = o.get("base", {}); rb = o.get("robustness") or {}
    if r.get("error"):
        print(tk, "ERROR", r["error"]); continue
    print(f"{tk} {cal_path.name} run {r['run_id']} (движок {o.get('model_version')}, crossover {(b.get('valuation_crossover') or {}).get('mode')}): "
          f"CAGR5 {b['return']['median_CAGR_5Y']:+.4f} (было {pb['return']['median_CAGR_5Y']:+.4f}) | P(loss>30) {b['downside']['P_loss_gt_30pct_5Y']:.4f} (было {pb['downside']['P_loss_gt_30pct_5Y']:.4f}) | "
          f"ES5 {b['downside']['expected_shortfall_5pct_5Y']:.3f} (было {pb['downside']['expected_shortfall_5pct_5Y']:.3f}) | P(2x) {b['return']['P_2x_5Y']:.3f} (было {pb['return']['P_2x_5Y']:.3f}) | "
          f"robustness {rb.get('pass')} ({rb.get('same_sign_share')}/{rb.get('within_delta_tolerance_share')}) | conv {(o.get('convergence') or {}).get('stable')} | warnings {b.get('mapping_warnings')}")
