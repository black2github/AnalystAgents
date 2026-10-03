"""Сравнение вариантов состава портфеля одним запуском v1.0 (ROADMAP п. 2, 03.10.2026): для списка вариантов весов (текущий, оптимумы
заходов, ручные варианты владельца, «с кандидатом») — картина под каждым сценарием и в смеси (Scenario Engine §6), вклады сценариев и
ScenarioConcentration (вариант «а»), сквозные доли тем (Theme Look-through, binding basis revenue), число позиций и оборот от опорного
варианта, нарушения лимитов владельца (через portfolio_optimizer._Problem на смеси: потолки, сектор, топ-3, общая причина, dry powder,
риск BASE, сценарные гейты, cardinality, тема), картины по условным фазам (по желанию) и таблица разностей к опорному варианту.
Ничего не оптимизирует и не решает: все числа — derived_fact из путей; decision: none.

inputs: {"variants": [{"id": str, "weights": {tk: w}, "dry_powder": w, "note": str?}], "reference_id": id (по умолчанию первый),
         "scenarios": [{"id": "BASE", "paths_files": {tk: .npz}}, {"id", "probability", "paths_files"}...]  (как portfolio_paths mixture),
         "dry_powder_return_annual": 0.04, "max_paths": null,
         "fixed_weights": {tk: w} — позиции без путей (GLD/UFO), плоская доходность; участвуют в лимитах и в сумме весов,
         "theme": {"aggregate_id": "AI_TOTAL", "shares": {tk: share}, "baseline_value": float|null, "policy_id": str} (по желанию),
         "limits_check": {<входы оптимизатора: limits, per_name_caps, roles, sectors, common_cause, regime, scenario_constraints?>} (по желанию),
         "conditional": [{"scenario_id", "phase_id", "paths_files": {tk: .npz}}] (по желанию — картины по подтверждённым фазам)}
outputs: variants[id] = {weights, dry_powder, positions_count, by_scenario{sid: Y5-метрики}, mixture{Y3/Y5/Y8}, scenario_impacts,
  scenario_concentration, theme{aggregate, value}, turnover_vs_reference, violations[], conditional{sid|phase: Y5}}; comparison =
  таблица разностей к reference (медиана, ES5, P(l30), под каждым сценарием, тема, кэш); ranking — лексикографически (медиана с допуском →
  ES5 → концентрация → оборот) только среди допустимых; decision: none.
"""
from __future__ import annotations

import numpy as np

from engine import portfolio_optimizer as po
from engine import portfolio_paths as pp

VERSION = "1.0.0"
Y5KEYS = ("median_CAGR", "P_loss_gt_30pct", "P_loss_gt_50pct", "expected_shortfall_5pct", "P_2x")


def _pv(data: dict, w: dict, wdp: float, rdp: float, n: int, key: str, yrs: int, fixed_total: float) -> np.ndarray:
    pv = np.zeros(n)
    for t, wt in w.items():
        if wt > 0:
            pv += wt * data[t][key][:n].astype(float)
    return pv + wdp * (1.0 + rdp) ** yrs + fixed_total


def _m(pv: np.ndarray, yrs: int) -> dict:
    return po._metrics(pv, yrs)


def run(inputs: dict, seed: int) -> dict:
    variants = inputs.get("variants") or []
    if not variants:
        raise ValueError("variants пуст")
    ids = [str(v["id"]) for v in variants]
    if len(set(ids)) != len(ids):
        raise ValueError("id вариантов должны быть уникальны")
    ref_id = str(inputs.get("reference_id") or ids[0])
    if ref_id not in ids:
        raise ValueError(f"reference_id {ref_id} нет среди вариантов")
    scen = inputs.get("scenarios") or []
    sids = [sc["id"] for sc in scen]
    if "BASE" not in sids:
        raise ValueError("scenarios: обязателен BASE")
    rdp = float(inputs.get("dry_powder_return_annual", 0.0))
    fixed = {k: float(v) for k, v in (inputs.get("fixed_weights") or {}).items()}
    fixed_total = float(sum(fixed.values()))
    tick = sorted({t for v in variants for t, w in (v.get("weights") or {}).items() if float(w) > 0 and t not in fixed})
    # пути: загрузка один раз на сценарий
    loaded = {}
    for sc in scen:
        files = sc.get("paths_files") or {}
        miss = [t for t in tick if t not in files]
        if miss:
            raise ValueError(f"сценарий {sc['id']}: нет файлов путей для {miss}")
        loaded[sc["id"]] = {t: pp.load_paths(files[t]) for t in tick}
    n = min(len(d[t]["r5"]) for d in loaded.values() for t in tick)
    if inputs.get("max_paths"):
        n = min(n, int(inputs["max_paths"]))
    ref_ids = loaded["BASE"][tick[0]]["path_id"][:n]
    for sid, d in loaded.items():
        for t in tick:
            if not np.array_equal(d[t]["path_id"][:n], ref_ids):
                raise ValueError(f"сценарий {sid}, {t}: пути не выровнены по path_id с BASE")
    probs = {sc["id"]: float(sc["probability"]) for sc in scen if sc["id"] != "BASE" and sc.get("probability") is not None}
    pending = [sc["id"] for sc in scen if sc["id"] != "BASE" and sc.get("probability") is None]
    if not pending:
        probs["BASE"] = 1.0 - sum(probs.values())
    cond = inputs.get("conditional") or []
    cond_loaded = {}
    for c in cond:
        key = f"{c['scenario_id']}|{c['phase_id']}"
        cond_loaded[key] = {t: pp.load_paths(c["paths_files"][t]) for t in tick if t in (c.get("paths_files") or {})}
    theme = inputs.get("theme") or None
    # проверка лимитов — задача оптимизатора на смеси (без поиска), нарушения по точке
    P = None
    lc = inputs.get("limits_check")
    if lc and not pending:
        mix = pp.build_mixture_data(loaded, {s: p for s, p in probs.items() if s != "BASE"}, [s for s in sids if s != "BASE"], n)
        p_inputs = {"paths_files": {t: "" for t in tick}, "weights_current": {**(next(v for v in variants if str(v["id"]) == ref_id).get("weights") or {}), **fixed}, "fixed_weights": fixed,
                    "dry_powder_current": float(next(v for v in variants if str(v["id"]) == ref_id).get("dry_powder", 0.0)), "dry_powder_return_annual": rdp, **lc, "search": {"random_starts": 0, "basin_kicks": 0}}
        try:
            P = po._Problem(p_inputs, data=mix)
        except Exception as e:  # noqa: BLE001 — проверка лимитов необязательна; причина отказа попадает в выход
            P = None; lc_error = str(e)[:200]
    out_v = {}
    ref = next(v for v in variants if str(v["id"]) == ref_id)
    ref_w = {t: float(ref.get("weights", {}).get(t, 0.0)) for t in tick}; ref_dp = float(ref.get("dry_powder", 0.0))
    for v in variants:
        vid = str(v["id"]); w = {t: float(v.get("weights", {}).get(t, 0.0)) for t in tick}; wdp = float(v.get("dry_powder", 0.0))
        tot = sum(w.values()) + wdp + fixed_total
        if abs(tot - 1.0) > 1e-4:
            raise ValueError(f"вариант {vid}: веса + dry powder + fixed = {tot:.6f} ≠ 1")
        by = {}
        for sid in sids:
            by[sid] = {h: _m(_pv(loaded[sid], w, wdp, rdp, n, key, yrs, fixed_total), yrs) for h, key, yrs in (("Y3", "r3", 3), ("Y5", "r5", 5), ("Y8", "r8", 8))}
        mixture = None; impacts = None; conc = None
        if not pending:
            mixture = {}
            for h, key, yrs in (("Y3", "r3", 3), ("Y5", "r5", 5), ("Y8", "r8", 8)):
                pvs = np.concatenate([_pv(loaded[sid], w, wdp, rdp, n, key, yrs, fixed_total) for sid in sids]); ws = np.concatenate([np.full(n, probs[sid] / n) for sid in sids])
                mixture[h] = pp._wmetrics(pvs, ws, yrs)
            b = by["BASE"]["Y5"]; impacts = {}
            for sid in sids:
                if sid == "BASE":
                    continue
                m = by[sid]["Y5"]
                impacts[sid] = {"probability": probs[sid], "MedianImpact_Y5": probs[sid] * (m["median_CAGR"] - b["median_CAGR"]), "ES5Impact_Y5": probs[sid] * (m["expected_shortfall_5pct"] - b["expected_shortfall_5pct"]),
                                "adverse_ES_burden_B": probs[sid] * max(0.0, b["expected_shortfall_5pct"] - m["expected_shortfall_5pct"])}
            conc = pp.scenario_concentration({sid: x["adverse_ES_burden_B"] for sid, x in impacts.items()})
        cond_out = {}
        for key, d in cond_loaded.items():
            miss = [t for t in tick if w[t] > 0 and t not in d]
            cond_out[key] = ({"error": f"нет путей для {miss}"} if miss else _m(_pv(d, w, wdp, rdp, min(n, min(len(d[t]["r5"]) for t in d)), "r5", 5, fixed_total), 5))
        th = None
        if theme:
            sh = theme.get("shares") or {}
            tv = float(sum(w[t] * float(sh.get(t, 0.0)) for t in tick) + sum(float(x) * float(sh.get(t, 0.0)) for t, x in fixed.items()))
            th = {"aggregate_id": theme.get("aggregate_id"), "value": tv, "baseline_value": theme.get("baseline_value"),
                  "within_policy": (tv <= float(theme["baseline_value"]) + 1e-6) if theme.get("baseline_value") is not None else None}
        viol = None
        if P is not None:
            wv = np.array([w.get(t, 0.0) for t in P.tick])
            try:
                viol = [{k: x[k] for k in ("constraint", "value", "bound", "excess")} for x in P.violations(wv, wdp)]
            except Exception as e:  # noqa: BLE001
                viol = [{"constraint": "limits_check_error", "value": None, "bound": None, "excess": None, "message": str(e)[:160]}]
        turnover = float(0.5 * (sum(abs(w[t] - ref_w[t]) for t in tick) + abs(wdp - ref_dp)))
        out_v[vid] = {"note": v.get("note"), "weights": {t: round(x, 6) for t, x in w.items() if x > 0}, "dry_powder": wdp, "fixed_weights": fixed,
                      "positions_count": int(sum(1 for x in w.values() if x > 1e-9)),
                      "by_scenario_Y5": {sid: {k: by[sid]["Y5"][k] for k in Y5KEYS} | {"q05": by[sid]["Y5"]["CAGR_quantiles"]["0.05"], "q95": by[sid]["Y5"]["CAGR_quantiles"]["0.95"]} for sid in sids},
                      "by_scenario_all_horizons": by, "mixture": mixture, "scenario_impacts": impacts, "scenario_concentration": conc,
                      "conditional_phases_Y5": cond_out or None, "theme": th, "turnover_vs_reference": turnover, "violations": viol,
                      "feasible": (None if viol is None else (len(viol) == 0))}
    # таблица разностей к опорному и ранжирование
    R = out_v[ref_id]
    comparison = {}
    for vid, o in out_v.items():
        if vid == ref_id:
            continue
        row = {"positions_count": o["positions_count"] - R["positions_count"], "cash_pp": 100 * (o["dry_powder"] - R["dry_powder"]), "turnover_vs_reference": o["turnover_vs_reference"]}
        if o["mixture"] and R["mixture"]:
            row["mixture_Y5"] = {k: 100 * (o["mixture"]["Y5"][k] - R["mixture"]["Y5"][k]) for k in ("median_CAGR", "expected_shortfall_5pct", "P_loss_gt_30pct")}
        row["by_scenario_Y5"] = {sid: {k: 100 * (o["by_scenario_Y5"][sid][k] - R["by_scenario_Y5"][sid][k]) for k in ("median_CAGR", "expected_shortfall_5pct", "P_loss_gt_30pct")} for sid in sids}
        if o["theme"] and R["theme"]:
            row["theme_pp"] = 100 * (o["theme"]["value"] - R["theme"]["value"])
        comparison[vid] = row
    tol = float(inputs.get("objective_tolerance_pp", 0.5)) / 100.0

    def better(a, b):
        ma, mb = a["mixture"]["Y5"]["median_CAGR"], b["mixture"]["Y5"]["median_CAGR"]
        if ma > mb + tol:
            return True
        if mb > ma + tol:
            return False
        ea, eb = a["mixture"]["Y5"]["expected_shortfall_5pct"], b["mixture"]["Y5"]["expected_shortfall_5pct"]
        if abs(ea - eb) > 1e-4:
            return ea > eb
        ca, cb = (a["scenario_concentration"] or {}), (b["scenario_concentration"] or {})
        if ca.get("applicable") and cb.get("applicable") and abs(ca["value"] - cb["value"]) > 1e-4:
            return ca["value"] < cb["value"]
        return a["turnover_vs_reference"] < b["turnover_vs_reference"]
    ranking = None
    if not pending:
        elig = [vid for vid, o in out_v.items() if o["feasible"] in (None, True)]
        order = []
        for vid in elig:
            pos = 0
            while pos < len(order) and not better(out_v[vid], out_v[order[pos]]):
                pos += 1
            order.insert(pos, vid)
        ranking = {"order": order, "rule": "лексикографически (Optimizer v1.1 §2): медиана CAGR 5Y смеси с допуском 0.5 п.п. → ES5 → ScenarioConcentration → оборот; только допустимые (или без проверки лимитов)",
                   "excluded_infeasible": [vid for vid, o in out_v.items() if o["feasible"] is False]}
    return {"model_version": VERSION, "paths": int(n), "companies": tick, "scenarios": [{"id": s, "probability": (probs.get(s) if not pending else None)} for s in sids],
            "probability_status": ("owner_judgment" if not pending else "pending_owner_judgment"), "pending": pending, "reference_id": ref_id,
            "limits_check": ("applied" if P is not None else ("not_requested" if not lc else f"unavailable: {locals().get('lc_error', 'pending probabilities')}")),
            "variants": out_v, "comparison_vs_reference": comparison, "ranking": ranking,
            "assumptions": ["позиции без путей (fixed_weights) — плоская доходность 1.0", "смесь §6 — взвешенная эмпирическая, impacts диагностические (§7)",
                            "тема — Σ w·share по выручке (Theme Look-through v1.0)", "нарушения лимитов — по точке, без поиска; разрыв ≠ приказ"],
            "decision": "none"}
