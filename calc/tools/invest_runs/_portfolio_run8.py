"""Заход 8 отбора (02.10): оптимум отбора для Decision Request владельцу. 1) portfolio_optimizer 1.1.1 на файлах-смеси захода 6
(mix-p10-p07-p175: TS 0.10 / CW 0.07 / Q 0.175 / BASE 0.655) со сценарно-условными ограничениями V1 (approved_limits_v1_1), GLD/UFO
фиксированы (GLD 2.2 % — до принятой Hedge_Instrument_Model, партия 10 §9), старты current/equal/empty/given (оптимум C2 захода 7
…-5a6da6). 2) нормативная смесь §6 на оптимуме (отчётный риск, концентрация). 3) Portfolio Stability Test 1.3.0 на оптимуме:
семейства return_shift / terminal (прокси) / correlation / scenario (§3.3, вероятности владельца) / combined / loo, 100k путей,
central_run_ref = прогон п. 1; без пересимуляции. Результаты: _opt_run8.json. Запуск: python _portfolio_run8.py"""
import json
import time
from pathlib import Path

import _portfolio_run7_lib as L

S = Path(__file__).parent
R7 = json.load(open(S / "_opt_run7.json", encoding="utf-8"))
given = {tk: w for tk, w in R7["C2"]["weights"].items() if tk in L.NORM}
RES = {}
t0 = time.time()
rid, o = L.optimize("S8: смесь 4 сценариев, пороги V1, GLD fixed, старты current/equal/empty/given(C2)", thresholds=True, hedge=False,
                    extra={"starts": ["current", "equal", "empty", "given"], "start_weights": given, "start_dry_powder": R7["C2"]["dp"]})
diff = {tk: round(o["proposed_weights"].get(tk, 0.0) - R7["C2"]["weights"].get(tk, 0.0), 4) for tk in set(o["proposed_weights"]) | set(R7["C2"]["weights"])}
print("Δ весов S8−C2:", {k: v for k, v in diff.items() if abs(v) >= 0.005}, "| Δdp", round(o["dry_powder_weight"] - R7["C2"]["dp"], 4), flush=True)
print("cands", [(c["start"], c["feasible"], round(c["median_CAGR_5Y"], 4), round(c["ES5"], 4)) for c in o["candidates"]], f"| {time.time() - t0:.0f}s", flush=True)
RES["S8"] = {"run_id": rid, "weights": o["proposed_weights"], "dp": o["dry_powder_weight"], "feasible": o["feasible"], "binding": o["binding_constraints"],
             "median_CAGR_5Y": o["portfolio_return_distribution"]["Y5"]["median_CAGR"], "ES5": o["portfolio_downside"]["Y5"]["expected_shortfall_5pct"],
             "scenario_constraints": o["scenario_constraints"]["at_optimum"], "start_used": o["start_used"], "turnover": o["turnover_from_current"]}
json.dump(RES, open(S / "_opt_run8.json", "w", encoding="utf-8"), indent=1)
# 2) смесь §6 на оптимуме
wopt = {tk: w for tk, w in o["proposed_weights"].items() if tk in L.NORM and w > 0}; s = sum(wopt.values()) + o["dry_powder_weight"]
r = L.post({"model": "portfolio_paths", "inputs": {"scenarios": [{"id": "BASE", "paths_files": L.base_files}] + L.scen_files, "weights": {tk: w / s for tk, w in wopt.items()}, "dry_powder_weight": o["dry_powder_weight"] / s, "dry_powder_return_annual": 0.04}, "seed": 0, "save": True})
y5 = r["outputs"]["horizons"]["Y5"]; scn = r["outputs"]["scenario_concentration"]
print(f"смесь §6 на S8 {r['run_id']}: Y5 median {y5['median_CAGR']:+.4f} P(l30) {y5['P_loss_gt_30pct']:.4f} ES5 {y5['expected_shortfall_5pct']:+.4f} | impacts " + str({k: (round(v["MedianImpact_Y5"], 4), round(v["ES5Impact_Y5"], 4)) for k, v in r["outputs"]["scenario_impacts"].items()}) + f" | concentration {scn['status']} {scn['value']} warning {scn['warning']}", flush=True)
RES["mixture_S8"] = {"run_id": r["run_id"], "Y5": y5, "concentration": scn}
json.dump(RES, open(S / "_opt_run8.json", "w", encoding="utf-8"), indent=1)
# 3) Stability Test на оптимуме S8
fixed = {tk: w for tk, w in L.wcur.items() if tk not in L.NORM}
sc = {"p_min": L.sc11["p_min"], "es5_min": L.sc11["es5_min"], "p_loss_gt_30_max": L.sc11["p_loss_gt_30_max"], "scenario_concentration_max": L.sc11["scenario_concentration_max"], "scenarios": L.scen_files, "base_paths_files": L.base_files}
inp = {"paths_files": L.FILES, "weights_current": L.wcur, "fixed_weights": fixed, "dry_powder_current": L.cash_w, "dry_powder_return_annual": 0.04, "regime": L.regime, "limits": L.limits,
       "per_name_caps": L.caps, "roles": {}, "sectors": L.sectors, "common_cause": L.cc, "objective_tolerance_pp": 0.5, "scenario_constraints": sc,
       "stability": {"families": ["return_shift", "terminal", "correlation", "scenario", "combined", "loo"], "max_paths": 100000, "search_paths": 100000, "combined_runs": 500,
                     "central_run_ref": rid, "scenario_probabilities": {"scenarios": L.scen_files, "base_paths_files": L.base_files, "order": ["TAIWAN_SEIZURE", "CHIP_COLD_WAR", "TAIWAN_QUARANTINE"]}}}
t1 = time.time()
r = L.post({"model": "portfolio_stability", "inputs": inp, "seed": 11, "save": True})
if r.get("error"):
    print("stability ERROR", r["error"][:600], flush=True)
else:
    o = r["outputs"]
    print(f"stability {r['run_id']} | {time.time() - t1:.0f}s | версия {o['model_version']} | runs {o.get('runs_total')} feasibility_rate {o.get('feasibility_rate')} | классификация портфеля {o.get('portfolio_stability_classification')}", flush=True)
    print("   центр vs нормативный:", o.get("central_vs_reference") or o.get("central_run_comparison"), flush=True)
    print("   бумаги:", {k: v for k, v in (o.get("company_stability_classification") or {}).items()}, flush=True)
    ss = o.get("scenario_sensitivity") or {}
    print("   §3.3:", ss.get("status"), "max_abs_weight_shift", ss.get("max_abs_weight_shift_vs_central"), "burdens", ss.get("burdens_at_central"), "up10", ss.get("up10_status"), flush=True)
    for pr in ss.get("perturbations") or []:
        print("     ", pr["label"], "valid", pr["valid"], "opt", (pr.get("optimizer") or {}).get("feasible"), "shift", pr.get("max_abs_weight_shift_vs_central"), flush=True)
    RES["stability_S8"] = {"run_id": r["run_id"], "classification": o.get("portfolio_stability_classification"), "feasibility_rate": o.get("feasibility_rate"), "companies": o.get("company_stability_classification"), "scenario_sensitivity_status": ss.get("status"), "max_abs_weight_shift": ss.get("max_abs_weight_shift_vs_central")}
    json.dump(RES, open(S / "_opt_run8.json", "w", encoding="utf-8"), indent=1)
print("DONE", flush=True)
