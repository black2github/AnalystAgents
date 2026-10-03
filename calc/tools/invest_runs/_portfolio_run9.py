"""Заход 9 отбора (по одобрению владельца): варианты лимита числа бумаг — DR-2026-10-02-01/В1 (6…8 бумаг, мин. вес 3 %; GLD/UFO вне счёта).
Три прогона portfolio_optimizer 1.2.0 на файлах-смеси захода 6 с порогами V1 и концентрацией warning 60 / hard 70, GLD/UFO фиксированы,
старты current/equal/empty/given (S8 …-56bdcc): A) без лимита (контроль, = S8), B) positions_max 8 / min 3 %, C) positions_max 6 / min 3 %;
positions_min 6 в B и C. Отчёт: веса, медиана, ES5, картина под сценариями, «цена ограничения» (Δ медианы и ES5 к A). Результаты:
_opt_run9.json. Запуск: python _portfolio_run9.py   (≈ 3 × 20–25 мин)"""
import json
import sys
import time
from pathlib import Path

import _portfolio_run7_lib as L

S = Path(__file__).parent
R8 = json.load(open(S / "_opt_run8.json", encoding="utf-8")); s8 = R8["S8"]
# возобновление: --a-run <run_id> — вариант A уже посчитан сайдкаром (клиент был остановлен), взять из _runs; --only B,C — считать только эти
A_RUN = sys.argv[sys.argv.index("--a-run") + 1] if "--a-run" in sys.argv else None
ONLY = set(sys.argv[sys.argv.index("--only") + 1].split(",")) if "--only" in sys.argv else None
res_path = S / "_opt_run9.json"
given = {tk: w for tk, w in s8["weights"].items() if tk in L.NORM}
card = L.l11["cardinality"]
conc = L.l11.get("scenario_concentration") or {}
RES = json.load(open(res_path, encoding="utf-8")) if res_path.exists() else {}
if A_RUN and "A" not in RES:
    rr = json.load(open(L.WS / "portfolio/_runs" / f"{A_RUN}.json", encoding="utf-8")); o = rr["outputs"]; y5 = o["portfolio_return_distribution"]["Y5"]; d5 = o["portfolio_downside"]["Y5"]
    RES["A"] = {"run_id": A_RUN, "label": "A: без лимита числа бумаг (контроль)", "weights": o["proposed_weights"], "dp": o["dry_powder_weight"], "feasible": o["feasible"], "median_CAGR_5Y": y5["median_CAGR"],
                "ES5": d5["expected_shortfall_5pct"], "P_loss_gt_30pct": d5["P_loss_gt_30pct"], "binding": o["binding_constraints"], "violations": o["violations_at_optimum"], "cardinality": o.get("cardinality"),
                "scenario_constraints": o["scenario_constraints"]["at_optimum"], "turnover": o["turnover_from_current"]}
    json.dump(RES, open(res_path, "w", encoding="utf-8"), indent=1, ensure_ascii=False); print("A взят из _runs:", A_RUN, {k: v for k, v in o["proposed_weights"].items() if v > 0}, flush=True)
TH = json.load(open(S / "_theme_lookthrough.json", encoding="utf-8"))                     # 1.3.0: политика темы ИИ (Optimizer v1.1 §16), база 21.09 материализована
theme_policy = {"policy_id": "AI_THEME_NOT_INCREASE_V1", "aggregate_id": "AI_TOTAL", "shares": {tk: v for tk, v in TH["shares"].items() if tk in L.NORM}, "baseline_value": TH["baseline_2026_09_21"], "tolerance": 1e-6, "baseline_status": "MATERIALIZED"}
mp = card["min_position_weight"]
variants = [("A: без лимитов числа бумаг и мин. веса (контроль = S8)", None, "UNCONSTRAINED_REFERENCE"),
            (f"B: CARDINALITY_8 — {card['positions_min']}…{card['positions_max']} бумаг, мин. {mp:.0%}", {"positions_min": card["positions_min"], "positions_max": card["positions_max"], "min_position_weight": mp, "excludes": card["excludes"]}, "CARDINALITY_8"),
            (f"C: CARDINALITY_6 — {card['positions_min']} бумаг, мин. {mp:.0%}", {"positions_min": card["positions_min"], "positions_max": card["positions_min"], "min_position_weight": mp, "excludes": card["excludes"]}, "CARDINALITY_6"),
            (f"D: NO_CARDINALITY_LIMIT — без лимита числа, мин. {mp:.0%} (Optimizer v1.1 §15.1)", {"positions_min": None, "positions_max": None, "min_position_weight": mp, "excludes": card["excludes"]}, "NO_CARDINALITY_LIMIT")]
for label, cd, variant_id in variants:
    if (ONLY and label[:1] not in ONLY) or label[:1] in RES:
        continue
    limits = dict(L.limits); limits["theme_policy"] = theme_policy
    if cd:
        limits["cardinality"] = cd
    t0 = time.time()
    sc = {"p_min": L.sc11["p_min"], "es5_min": L.sc11["es5_min"], "p_loss_gt_30_max": L.sc11["p_loss_gt_30_max"], "scenario_concentration_max": conc.get("hard_max", L.sc11["scenario_concentration_max"]),
          "scenarios": L.scen_files, "base_paths_files": L.base_files}                       # концентрация: жёсткий лимит 70 % (DR-2026-10-02-01/В2)
    rid, o = L.optimize(label, thresholds=True, hedge=False, extra={"starts": ["current", "equal", "empty", "given"], "start_weights": given, "start_dry_powder": s8["dp"], "limits": limits, "scenario_constraints": sc, "cardinality_variant": variant_id})
    y5 = o["portfolio_return_distribution"]["Y5"]; d5 = o["portfolio_downside"]["Y5"]
    print(f"   theme: {o.get('theme_lookthrough')} | cardinality: {o.get('cardinality')} | cands {[(c['start'], c['feasible'], round(c['median_CAGR_5Y'], 4)) for c in o['candidates']]} | {time.time() - t0:.0f}s", flush=True)
    RES[label[:1]] = {"run_id": rid, "label": label, "variant_id": variant_id, "theme_lookthrough": o.get("theme_lookthrough"), "weights": o["proposed_weights"], "dp": o["dry_powder_weight"], "feasible": o["feasible"], "median_CAGR_5Y": y5["median_CAGR"], "ES5": d5["expected_shortfall_5pct"],
                      "P_loss_gt_30pct": d5["P_loss_gt_30pct"], "binding": o["binding_constraints"], "violations": o["violations_at_optimum"], "cardinality": o.get("cardinality"),
                      "scenario_constraints": o["scenario_constraints"]["at_optimum"], "turnover": o["turnover_from_current"]}
    json.dump(RES, open(res_path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
ref = RES.get("D") or RES.get("A")                                                        # цена ограничения — против NO_CARDINALITY_LIMIT (§15.1), иначе против A
for k in ("B", "C"):
    if k in RES and ref:
        RES[k]["constraint_price_vs_no_cardinality_limit"] = {"reference": ref["run_id"], "MedianCost_pp": 100 * (RES[k]["median_CAGR_5Y"] - ref["median_CAGR_5Y"]), "ES5Cost_pp": 100 * (RES[k]["ES5"] - ref["ES5"])}
        print(f"цена ограничения {k} против {ref['label'][:1]}: Δмедиана {100 * (RES[k]['median_CAGR_5Y'] - ref['median_CAGR_5Y']):+.2f} п.п., ΔES5 {100 * (RES[k]['ES5'] - ref['ES5']):+.1f} п.п.", flush=True)
json.dump(RES, open(res_path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print("DONE", flush=True)
