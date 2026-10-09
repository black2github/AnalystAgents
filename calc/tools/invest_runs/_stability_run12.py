"""Пакет C (одобрен владельцем 10.10.2026): Stability Test portfolio_stability 1.3.2 вокруг оптимума вселенной U18 захода 12 (тёплый старт центра
от его весов), лимиты v1.0/v1.1 включая cardinality и тему, семейства return_shift / terminal / correlation / scenario (§3.3) / combined / loo,
100k путей, GLD/UFO фиксированы. Входы (пути-смеси, потолки, сектора, лимиты) — из _opt_run12.json. Результат → _opt_run12.json["stability_U18"].
Время: ≈ 5 ч (S8b). Запуск: python _stability_run12.py"""
import json
import time
import urllib.request
from pathlib import Path

import _portfolio_run7_lib as L

S = Path(__file__).parent; R = json.load(open(S / "_opt_run12.json", encoding="utf-8")); u = R["variants"]["U18"]["optimized"]["mixture"]
inp = {"paths_files": R["files"], "weights_current": L.wcur, "fixed_weights": R["fixed_opt"], "dry_powder_current": L.cash_w, "dry_powder_return_annual": 0.04, "regime": L.regime, "limits": R["limits"],
       "per_name_caps": R["caps"], "roles": {}, "sectors": R["sectors"], "common_cause": L.cc, "objective_tolerance_pp": 0.5, "scenario_constraints": R["scenario_constraints"],
       "stability": {"families": ["return_shift", "terminal", "correlation", "scenario", "combined", "loo"], "max_paths": 100000, "search_paths": 100000, "combined_runs": 500,
                     "central_run_ref": R["run_id"], "central_start_weights": {tk: w for tk, w in u["weights"].items()}, "central_start_dry_powder": u["dry_powder"],
                     "scenario_probabilities": {"scenarios": L.scen_files, "base_paths_files": L.base_files, "order": ["TAIWAN_SEIZURE", "CHIP_COLD_WAR", "TAIWAN_QUARANTINE"]}}}
t1 = time.time()
req = urllib.request.Request(L.URL, data=json.dumps({"model": "portfolio_stability", "inputs": inp, "seed": 11, "save": True}).encode(), headers={"Content-Type": "application/json"})
r = json.load(urllib.request.urlopen(req, timeout=12 * 3600)); o = r["outputs"]
print(f"stability U18 {r['run_id']} | {time.time() - t1:.0f}s | версия {o['model_version']} | runs {o.get('runs_total')} feasibility_rate {o.get('feasibility_rate')} | класс {(o.get('portfolio_stability_classification') or {}).get('class')} {(o.get('portfolio_stability_classification') or {}).get('turnover_p50')}", flush=True)
c = (o.get("central_vs_reference") or {}).get("central") or {}
print("   центр:", {k: v for k, v in (c.get("weights") or {}).items() if v > 0}, "dp", c.get("dry_powder"), "median", c.get("median_CAGR_5Y"), "ES5", c.get("ES5"), flush=True)
print("   бумаги:", {k: v.get("class") for k, v in (o.get("company_stability_classification") or {}).items()}, flush=True)
ss = o.get("scenario_sensitivity") or {}
print("   §3.3:", ss.get("status"), "max_shift", ss.get("max_abs_weight_shift_vs_central"), [(p["label"], p["valid"], (p.get("optimizer") or {}).get("feasible"), p.get("max_abs_weight_shift_vs_central")) for p in ss.get("perturbations") or []], flush=True)
R["stability_U18"] = {"run_id": r["run_id"], "classification": o.get("portfolio_stability_classification"), "feasibility_rate": o.get("feasibility_rate"), "companies": o.get("company_stability_classification"), "central": c, "scenario_sensitivity": {k: v for k, v in ss.items() if k != "perturbations"}, "loo": o.get("leave_one_out")}
json.dump(R, open(S / "_opt_run12.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False); print("DONE", flush=True)
