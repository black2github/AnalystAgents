"""Партия 18, тяжёлая часть (одобрено владельцем 10.10.2026, пакет A): нормативные 500k под Joint Schema v1.1 для ETN v1.0.3 / MSFT v1.0.2 /
NET v1.0.1 / PLTR v1.0.1 (новые каналы INTEREST_RATES / CAPITAL_MARKETS) → _norm_runs_joint11.json; очистка их путей под сценариями / фазами и
файлов-смеси (пересчёт — _scenario_paths_for.py и экспорт в заходе). Запуск: python _party18_norm.py"""
import json
import urllib.request
from pathlib import Path

import yaml

S = Path(__file__).parent; WS = Path("C:/openclaw-lab/data/workspace-invest"); URL = "http://127.0.0.1:18791/run"
TK = {"ETN": ("etn", "mc_calibration_v1.0.3.yaml"), "MSFT": ("msft", "mc_calibration_v1.0.2.yaml"), "NET": ("net", "mc_calibration_v1.0.1.yaml"), "PLTR": ("pltr", "mc_calibration_v1.0.1.yaml")}
spec = yaml.safe_load((WS / "methodology" / "Joint_Simulation_Layer_Schema_v1.1.yaml").read_text(encoding="utf-8"))
norm = json.load(open(S / "_norm_runs_joint11.json", encoding="utf-8")); NEW = {}
for tk, (fd, fname) in TK.items():
    if NEW.get(tk):
        continue
    cal = yaml.safe_load((WS / "portfolio" / fd / fname).read_text(encoding="utf-8"))
    eq0 = yaml.safe_load((WS / "portfolio" / fd / "calibration_v1.0.yaml").read_text(encoding="utf-8"))["calibration_v1.0"]["market"]["equity_value"]
    r = json.load(urllib.request.urlopen(urllib.request.Request(URL, data=json.dumps({"model": "company_mc", "inputs": {"calibration": cal, "equity_value_0": eq0, "convergence_check": True, "robustness": True, "robustness_paths": 100000, "store_paths": True, "joint_layer_spec": spec}, "seed": 20260920, "save": True}).encode(), headers={"Content-Type": "application/json"}), timeout=3600))
    o = r["outputs"]; b = o["base"]; q = b["return"]["CAGR_5Y_quantiles"]; rb = o.get("robustness") or {}
    print(f"{tk} {fname} НОРМАТИВ Joint v1.1 {r['run_id']}: CAGR5 {b['return']['median_CAGR_5Y']:+.4f} q5..q95 {q['0.05']:+.3f}..{q['0.95']:+.3f} P(l30) {b['downside']['P_loss_gt_30pct_5Y']:.4f} P(2x) {b['return']['P_2x_5Y']:.3f} ES5 {b['downside']['expected_shortfall_5pct_5Y']:+.3f} gap RV {b['gap_metrics']['RV_Growth_Gap']:+.4f} price {b['gap_metrics']['Price_Expectation_Gap']:.3f} | robustness {rb.get('pass')} {rb.get('same_sign_share')}/{rb.get('within_delta_tolerance_share')} | warnings {(o.get('joint_simulation') or {}).get('mapping_warnings')}", flush=True)
    norm[tk] = r["run_id"]; NEW[tk] = r["run_id"]
    json.dump(norm, open(S / "_norm_runs_joint11.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)
json.dump(NEW, open(S / "_party18_norm_runs.json", "w", encoding="utf-8"), indent=1)
for name in ("_scenario_normative2.json", "_scenario_round3.json"):
    d = json.load(open(S / name, encoding="utf-8"))
    for sid in list(d):
        if isinstance(d[sid], dict):
            for tk in TK:
                d[sid].pop(tk, None)
    json.dump(d, open(S / name, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
d = json.load(open(S / "_conditional_runs_partB.json", encoding="utf-8"))
for k in d:
    if "|" in k:
        for tk in TK:
            d[k]["companies"].pop(tk, None)
json.dump(d, open(S / "_conditional_runs_partB.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
m = json.load(open(S / "_mixture_files_p10_p07_p175.json", encoding="utf-8"))
for tk in TK:
    m.pop(tk, None)
json.dump(m, open(S / "_mixture_files_p10_p07_p175.json", "w", encoding="utf-8"), indent=1)
print("карты очищены для", list(TK), "; DONE", flush=True)
