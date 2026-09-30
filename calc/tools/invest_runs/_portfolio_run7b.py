"""Заход 7, прогон C2 (30.09): C (пороги V1 + GLD хедж ≤ 10 %) с дополнительным тёплым стартом «given» от оптимума A/B (веса захода 6 +
GLD 2.2 %). Причина: прогон C от стартов current/equal/empty застрял в локальном оптимуме хуже A (медиана 18.4 % против 19.2 %), хотя точка A
допустима в задаче C. Запуск: python _portfolio_run7b.py"""
import json
from pathlib import Path

import _portfolio_run7_lib as L

S = Path(__file__).parent
R7 = json.load(open(S / "_opt_run7.json", encoding="utf-8"))
given = {tk: w for tk, w in R7["A"]["weights"].items()}; given["GLD"] = L.wcur["GLD"]
rid, o = L.optimize("C2: пороги V1 + GLD хедж ≤ 10 %, старты current/equal/empty/given(A)", thresholds=True, hedge=True,
                    extra={"starts": ["current", "equal", "empty", "given"], "start_weights": given, "start_dry_powder": R7["A"]["dp"]})
diff = {tk: round(o["proposed_weights"].get(tk, 0.0) - R7["A"]["weights"].get(tk, 0.0), 4) for tk in set(o["proposed_weights"]) | set(R7["A"]["weights"])}
print("Δ весов C2−A:", {k: v for k, v in diff.items() if abs(v) >= 0.005}, "| Δdp", round(o["dry_powder_weight"] - R7["A"]["dp"], 4), flush=True)
print("cands", [(c["start"], c["feasible"], round(c["median_CAGR_5Y"], 4), round(c["ES5"], 4)) for c in o["candidates"]], flush=True)
wopt = {tk: w for tk, w in o["proposed_weights"].items() if tk in L.NORM and w > 0}; s = sum(wopt.values()) + o["dry_powder_weight"]
r = L.post({"model": "portfolio_paths", "inputs": {"scenarios": [{"id": "BASE", "paths_files": L.base_files}] + L.scen_files, "weights": {tk: w / s for tk, w in wopt.items()}, "dry_powder_weight": o["dry_powder_weight"] / s, "dry_powder_return_annual": 0.04}, "seed": 0, "save": True})
y5 = r["outputs"]["horizons"]["Y5"]; scn = r["outputs"]["scenario_concentration"]
print(f"смесь §6 на оптимуме C2 {r['run_id']}: Y5 median {y5['median_CAGR']:+.4f} P(l30) {y5['P_loss_gt_30pct']:.4f} ES5 {y5['expected_shortfall_5pct']:+.4f} | concentration {scn['status']} {scn['value']}", flush=True)
R7["C2"] = {"run_id": rid, "weights": o["proposed_weights"], "dp": o["dry_powder_weight"], "feasible": o["feasible"], "mixture": r["run_id"]}
json.dump(R7, open(S / "_opt_run7.json", "w", encoding="utf-8"), indent=1); print("DONE", flush=True)
