"""Заход 10 (одобрен владельцем 03.10.2026 вместе с DR-2026-10-03-01/V1): проверка оптимумов B (CARDINALITY_8) и C (CARDINALITY_6) захода 9
глобальным поиском optimizer 1.4.0 (random_starts 8, basin_kicks 6, exploration_paths 50 000, polish_top 3) — те же смесь, пороги V1,
концентрация hard 70, тема AI_TOTAL ≤ база, GLD/UFO фиксированы, старты current/equal/empty/given (S8 …-56bdcc). Отчёт: сдвиг весов и
цели против захода 9 (_opt_run9.json), число различных локальных оптимумов, improvement_vs_standard_pp. Результаты: _opt_run10.json.
Запуск (отдельным процессом, ≈ 2 × 45–60 мин): python _portfolio_run10.py [--only B,C]"""
import json
import sys
import time
from pathlib import Path

import _portfolio_run7_lib as L

S = Path(__file__).parent
R8 = json.load(open(S / "_opt_run8.json", encoding="utf-8")); s8 = R8["S8"]
R9 = json.load(open(S / "_opt_run9.json", encoding="utf-8"))
ONLY = set(sys.argv[sys.argv.index("--only") + 1].split(",")) if "--only" in sys.argv else None
res_path = S / "_opt_run10.json"
given = {tk: w for tk, w in s8["weights"].items() if tk in L.NORM}
card = L.l11["cardinality"]
conc = L.l11.get("scenario_concentration") or {}
RES = json.load(open(res_path, encoding="utf-8")) if res_path.exists() else {}
TH = json.load(open(S / "_theme_lookthrough.json", encoding="utf-8"))
theme_policy = {"policy_id": "AI_THEME_NOT_INCREASE_V1", "aggregate_id": "AI_TOTAL", "shares": {tk: v for tk, v in TH["shares"].items() if tk in L.NORM}, "baseline_value": TH["baseline_2026_09_21"], "tolerance": 1e-6, "baseline_status": "MATERIALIZED"}
SEARCH = {"random_starts": 8, "basin_kicks": 6, "exploration_paths": 50_000, "polish_top": 3}
mp = card["min_position_weight"]
variants = [(f"B: CARDINALITY_8 — {card['positions_min']}…{card['positions_max']} бумаг, мин. {mp:.0%}, глобальный поиск", {"positions_min": card["positions_min"], "positions_max": card["positions_max"], "min_position_weight": mp, "excludes": card["excludes"]}, "CARDINALITY_8"),
            (f"C: CARDINALITY_6 — {card['positions_min']} бумаг, мин. {mp:.0%}, глобальный поиск", {"positions_min": card["positions_min"], "positions_max": card["positions_min"], "min_position_weight": mp, "excludes": card["excludes"]}, "CARDINALITY_6")]
for label, cd, variant_id in variants:
    k = label[:1]
    if (ONLY and k not in ONLY) or k in RES:
        continue
    limits = dict(L.limits); limits["theme_policy"] = theme_policy; limits["cardinality"] = cd
    sc = {"p_min": L.sc11["p_min"], "es5_min": L.sc11["es5_min"], "p_loss_gt_30_max": L.sc11["p_loss_gt_30_max"], "scenario_concentration_max": conc.get("hard_max", L.sc11["scenario_concentration_max"]),
          "scenarios": L.scen_files, "base_paths_files": L.base_files}
    t0 = time.time()
    rid, o = L.optimize(label, thresholds=True, hedge=False, extra={"starts": ["current", "equal", "empty", "given"], "start_weights": given, "start_dry_powder": s8["dp"], "limits": limits, "scenario_constraints": sc,
                                                                    "cardinality_variant": variant_id, "search": SEARCH})
    y5 = o["portfolio_return_distribution"]["Y5"]; d5 = o["portfolio_downside"]["Y5"]
    print(f"   search: {o.get('search')} | theme: {o.get('theme_lookthrough')} | cardinality: {o.get('cardinality')} | {time.time() - t0:.0f}s", flush=True)
    RES[k] = {"run_id": rid, "label": label, "variant_id": variant_id, "search": o.get("search"), "theme_lookthrough": o.get("theme_lookthrough"), "weights": o["proposed_weights"], "dp": o["dry_powder_weight"], "feasible": o["feasible"],
              "median_CAGR_5Y": y5["median_CAGR"], "ES5": d5["expected_shortfall_5pct"], "P_loss_gt_30pct": d5["P_loss_gt_30pct"], "binding": o["binding_constraints"], "violations": o["violations_at_optimum"], "cardinality": o.get("cardinality"),
              "scenario_constraints": o["scenario_constraints"]["at_optimum"], "turnover": o["turnover_from_current"], "elapsed_s": round(time.time() - t0)}
    if k in R9:                                                                       # сдвиг против захода 9 (покоординатный поиск 1.3.0)
        w9, w10 = R9[k]["weights"], o["proposed_weights"]
        RES[k]["vs_run9"] = {"run_id": R9[k]["run_id"], "delta_median_pp": round(100 * (y5["median_CAGR"] - R9[k]["median_CAGR_5Y"]), 3), "delta_ES5_pp": round(100 * (d5["expected_shortfall_5pct"] - R9[k]["ES5"]), 2),
                             "weight_deltas": {tk: round(w10.get(tk, 0.0) - w9.get(tk, 0.0), 4) for tk in sorted(set(w9) | set(w10)) if abs(w10.get(tk, 0.0) - w9.get(tk, 0.0)) > 1e-9},
                             "max_abs_weight_delta": round(max(abs(w10.get(tk, 0.0) - w9.get(tk, 0.0)) for tk in set(w9) | set(w10)), 4)}
        print(f"   против захода 9: {RES[k]['vs_run9']}", flush=True)
    json.dump(RES, open(res_path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print("DONE", flush=True)
