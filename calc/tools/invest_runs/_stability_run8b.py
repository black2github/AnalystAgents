"""Заход 8, Stability Test S8b (02.10): portfolio_stability 1.3.1 вокруг ПРИНЯТОГО оптимума S8 (…-56bdcc) — тёплый старт центра от его весов
(central_start_weights), а не от текущих весов (прогон …-97e56a ушёл в другой локальный оптимум: NBIS 23 % / CRWV 3.5 %). Семейства
return_shift / terminal / correlation / scenario (§3.3) / combined / loo, 100k путей, GLD/UFO фиксированы, пороги V1. Клиентский таймаут 12 ч.
Запуск: python _stability_run8b.py"""
import json
import time
import urllib.request
from pathlib import Path

import _portfolio_run7_lib as L

S = Path(__file__).parent; RES = json.load(open(S / "_opt_run8.json", encoding="utf-8")); s8 = RES["S8"]
fixed = {tk: w for tk, w in L.wcur.items() if tk not in L.NORM}
sc = {"p_min": L.sc11["p_min"], "es5_min": L.sc11["es5_min"], "p_loss_gt_30_max": L.sc11["p_loss_gt_30_max"], "scenario_concentration_max": L.sc11["scenario_concentration_max"], "scenarios": L.scen_files, "base_paths_files": L.base_files}
inp = {"paths_files": L.FILES, "weights_current": L.wcur, "fixed_weights": fixed, "dry_powder_current": L.cash_w, "dry_powder_return_annual": 0.04, "regime": L.regime, "limits": L.limits,
       "per_name_caps": L.caps, "roles": {}, "sectors": L.sectors, "common_cause": L.cc, "objective_tolerance_pp": 0.5, "scenario_constraints": sc,
       "stability": {"families": ["return_shift", "terminal", "correlation", "scenario", "combined", "loo"], "max_paths": 100000, "search_paths": 100000, "combined_runs": 500,
                     "central_run_ref": s8["run_id"], "central_start_weights": {tk: w for tk, w in s8["weights"].items()}, "central_start_dry_powder": s8["dp"],
                     "supersedes": ["20261001T224316Z-portfolio_stability-97e56a"],
                     "scenario_probabilities": {"scenarios": L.scen_files, "base_paths_files": L.base_files, "order": ["TAIWAN_SEIZURE", "CHIP_COLD_WAR", "TAIWAN_QUARANTINE"]}}}
t1 = time.time()
req = urllib.request.Request(L.URL, data=json.dumps({"model": "portfolio_stability", "inputs": inp, "seed": 11, "save": True}).encode(), headers={"Content-Type": "application/json"})
r = json.load(urllib.request.urlopen(req, timeout=12 * 3600)); o = r["outputs"]
print(f"stability {r['run_id']} | {time.time() - t1:.0f}s | версия {o['model_version']} | runs {o.get('runs_total')} feasibility_rate {o.get('feasibility_rate')} | класс {(o.get('portfolio_stability_classification') or {}).get('class')}", flush=True)
c = (o.get("central_vs_reference") or {}).get("central") or {}
print("   центр:", {k: v for k, v in (c.get("weights") or {}).items() if v > 0}, "dp", c.get("dry_powder"), "median", c.get("median_CAGR_5Y"), "ES5", c.get("ES5"), flush=True)
print("   бумаги:", {k: v.get("class") for k, v in (o.get("company_stability_classification") or {}).items()}, flush=True)
ss = o.get("scenario_sensitivity") or {}
print("   §3.3:", ss.get("status"), "max_shift", ss.get("max_abs_weight_shift_vs_central"), [(p["label"], p["valid"], (p.get("optimizer") or {}).get("feasible"), p.get("max_abs_weight_shift_vs_central")) for p in ss.get("perturbations") or []], flush=True)
RES["stability_S8b"] = {"run_id": r["run_id"], "classification": o.get("portfolio_stability_classification"), "feasibility_rate": o.get("feasibility_rate"), "companies": o.get("company_stability_classification"), "central": c, "scenario_sensitivity": {k: ss.get(k) for k in ("status", "max_abs_weight_shift_vs_central", "burdens_at_central", "up10_status")}}
json.dump(RES, open(S / "_opt_run8.json", "w", encoding="utf-8"), indent=1); print("DONE", flush=True)
