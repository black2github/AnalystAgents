"""Заход 9 отбора (по одобрению владельца): варианты лимита числа бумаг — DR-2026-10-02-01/В1 (6…8 бумаг, мин. вес 3 %; GLD/UFO вне счёта).
Три прогона portfolio_optimizer 1.2.0 на файлах-смеси захода 6 с порогами V1 и концентрацией warning 60 / hard 70, GLD/UFO фиксированы,
старты current/equal/empty/given (S8 …-56bdcc): A) без лимита (контроль, = S8), B) positions_max 8 / min 3 %, C) positions_max 6 / min 3 %;
positions_min 6 в B и C. Отчёт: веса, медиана, ES5, картина под сценариями, «цена ограничения» (Δ медианы и ES5 к A). Результаты:
_opt_run9.json. Запуск: python _portfolio_run9.py   (≈ 3 × 20–25 мин)"""
import json
import time
from pathlib import Path

import _portfolio_run7_lib as L

S = Path(__file__).parent
R8 = json.load(open(S / "_opt_run8.json", encoding="utf-8")); s8 = R8["S8"]
given = {tk: w for tk, w in s8["weights"].items() if tk in L.NORM}
card = L.l11["cardinality"]
conc = L.l11.get("scenario_concentration") or {}
RES = {}
variants = [("A: без лимита числа бумаг (контроль)", None), (f"B: {card['positions_min']}…{card['positions_max']} бумаг, мин. {card['min_position_weight']:.0%}", {"positions_min": card["positions_min"], "positions_max": card["positions_max"], "min_position_weight": card["min_position_weight"], "excludes": card["excludes"]}),
            (f"C: {card['positions_min']} бумаг, мин. {card['min_position_weight']:.0%}", {"positions_min": card["positions_min"], "positions_max": card["positions_min"], "min_position_weight": card["min_position_weight"], "excludes": card["excludes"]})]
for label, cd in variants:
    limits = dict(L.limits)
    if cd:
        limits["cardinality"] = cd
    t0 = time.time()
    sc = {"p_min": L.sc11["p_min"], "es5_min": L.sc11["es5_min"], "p_loss_gt_30_max": L.sc11["p_loss_gt_30_max"], "scenario_concentration_max": conc.get("hard_max", L.sc11["scenario_concentration_max"]),
          "scenarios": L.scen_files, "base_paths_files": L.base_files}                       # концентрация: жёсткий лимит 70 % (DR-2026-10-02-01/В2)
    rid, o = L.optimize(label, thresholds=True, hedge=False, extra={"starts": ["current", "equal", "empty", "given"], "start_weights": given, "start_dry_powder": s8["dp"], "limits": limits, "scenario_constraints": sc})
    y5 = o["portfolio_return_distribution"]["Y5"]; d5 = o["portfolio_downside"]["Y5"]
    print(f"   cardinality: {o.get('cardinality')} | cands {[(c['start'], c['feasible'], round(c['median_CAGR_5Y'], 4)) for c in o['candidates']]} | {time.time() - t0:.0f}s", flush=True)
    RES[label[:1]] = {"run_id": rid, "label": label, "weights": o["proposed_weights"], "dp": o["dry_powder_weight"], "feasible": o["feasible"], "median_CAGR_5Y": y5["median_CAGR"], "ES5": d5["expected_shortfall_5pct"],
                      "P_loss_gt_30pct": d5["P_loss_gt_30pct"], "binding": o["binding_constraints"], "violations": o["violations_at_optimum"], "cardinality": o.get("cardinality"),
                      "scenario_constraints": o["scenario_constraints"]["at_optimum"], "turnover": o["turnover_from_current"]}
    json.dump(RES, open(S / "_opt_run9.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)
a = RES.get("A")
for k in ("B", "C"):
    if k in RES and a:
        print(f"цена ограничения {k}−A: Δмедиана {100 * (RES[k]['median_CAGR_5Y'] - a['median_CAGR_5Y']):+.2f} п.п., ΔES5 {100 * (RES[k]['ES5'] - a['ES5']):+.1f} п.п.", flush=True)
print("DONE", flush=True)
