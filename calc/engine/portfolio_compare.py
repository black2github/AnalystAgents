"""Сравнение вариантов состава портфеля одним запуском v1.0 (ROADMAP п. 2, 03.10.2026): для списка вариантов весов (текущий, оптимумы
заходов, ручные варианты владельца, «с кандидатом») — картина под каждым сценарием и в смеси (Scenario Engine §6), вклады сценариев и
ScenarioConcentration (вариант «а»), сквозные доли тем (Theme Look-through, binding basis revenue), число позиций и оборот от опорного
варианта, нарушения лимитов владельца (через portfolio_optimizer._Problem на смеси: потолки, сектор, топ-3, общая причина, dry powder,
риск BASE, сценарные гейты, cardinality, тема), картины по условным фазам (по желанию) и таблица разностей к опорному варианту.
Ничего не решает: все числа — derived_fact из путей; decision: none.
1.1.0 — режим universe (решение владельца 03.10.2026): вариант задаётся СПИСКОМ БУМАГ без весов ({"id", "universe": [tk], "note"});
сравнитель сам вызывает portfolio_optimizer по шаблону optimizer_inputs: (1) оптимум на смеси сценариев с лимитами владельца и
сценарными гейтами — это и есть веса варианта (часть бумаг получает 0 = «не покупать / продать»); (2) по желанию — оптимум под каждым
сценарием (пути сценария, probability = 1, без сценарных гейтов) и под условными фазами (conditional) → таблица «бумага × сценарий»
(variants[id].optimized). Текущие позиции вне вселенной считаются проданными в кэш в стартовой точке (оборот их учитывает).
Бумаги без путей во вселенной — ошибка (нет калибровки). Долго: один вызов оптимизатора ≈ 20–60 мин на полных путях; универсум
с 4 сценариями — часы; запускать по одобрению владельца (universe_options.max_paths / search_paths — ускорение).

inputs: {"variants": [{"id": str, "weights": {tk: w}, "dry_powder": w, "note": str?} | {"id", "universe": [tk], "note"}], "reference_id": id,
         "optimizer_inputs": {<полные входы portfolio_optimizer: paths_files (все бумаги с путями), weights_current, fixed_weights,
             dry_powder_current, dry_powder_return_annual, regime, limits (с cardinality / theme_policy), per_name_caps, roles, sectors,
             common_cause, scenario_constraints (scenarios + base_paths_files), search, starts>} (обязателен при universe-вариантах),
         "universe_options": {"per_scenario": true, "conditional": false, "max_paths": null, "search_paths": null,
             "search": {"random_starts": 0, "basin_kicks": 0}, "scenario_search": {…}} (по желанию),
         "scenarios": [{"id": "BASE", "paths_files": {tk: .npz}}, {"id", "probability", "paths_files"}...]  (как portfolio_paths mixture),
         "dry_powder_return_annual": 0.04, "max_paths": null,
         "fixed_weights": {tk: w} — позиции без путей (GLD/UFO), плоская доходность; участвуют в лимитах и в сумме весов,
         "theme": {"aggregate_id": "AI_TOTAL", "shares": {tk: share}, "baseline_value": float|null, "policy_id": str} (по желанию),
         "limits_check": {<входы оптимизатора: limits, per_name_caps, roles, sectors, common_cause, regime, scenario_constraints?>} (по желанию),
         "conditional": [{"scenario_id", "phase_id", "paths_files": {tk: .npz}}] (по желанию — картины по подтверждённым фазам)}
outputs: variants[id] = {weights, dry_powder, positions_count, by_scenario{sid: Y5-метрики}, mixture{Y3/Y5/Y8}, scenario_impacts,
  scenario_concentration, theme{aggregate, value}, turnover_vs_reference, violations[], conditional{sid|phase: Y5},
  optimized{universe, mixture{weights, dry_powder, feasible, …}, by_scenario{sid: {weights, dry_powder, median_CAGR_5Y, ES5}},
  conditional{key: …}, weights_by_scenario{tk: {mixture, sid…}}, excluded_from_universe}}; comparison =
  таблица разностей к reference (медиана, ES5, P(l30), под каждым сценарием, тема, кэш); ranking — лексикографически (медиана с допуском →
  ES5 → концентрация → оборот) только среди допустимых; decision: none.
"""
from __future__ import annotations

import numpy as np

from engine import portfolio_optimizer as po
from engine import portfolio_paths as pp

VERSION = "1.1.1"
Y5KEYS = ("median_CAGR", "P_loss_gt_30pct", "P_loss_gt_50pct", "expected_shortfall_5pct", "P_2x")


def _pv(data: dict, w: dict, wdp: float, rdp: float, n: int, key: str, yrs: int, fixed_total: float) -> np.ndarray:
    pv = np.zeros(n)
    for t, wt in w.items():
        if wt > 0:
            pv += wt * data[t][key][:n].astype(float)
    return pv + wdp * (1.0 + rdp) ** yrs + fixed_total


def _m(pv: np.ndarray, yrs: int) -> dict:
    return po._metrics(pv, yrs)


def _restrict(files: dict, uni: list) -> dict:
    return {t: files[t] for t in uni if t in files}


def _opt_summary(o: dict) -> dict:
    y5 = o["portfolio_return_distribution"]["Y5"]; d5 = o["portfolio_downside"]["Y5"]
    return {"weights": {t: round(float(w), 6) for t, w in o["proposed_weights"].items() if float(w) > 1e-9}, "dry_powder": float(o["dry_powder_weight"]), "feasible": o["feasible"], "start_used": o.get("start_used"),
            "median_CAGR_5Y": y5["median_CAGR"], "ES5": d5["expected_shortfall_5pct"], "P_loss_gt_30pct": d5["P_loss_gt_30pct"], "binding_constraints": o.get("binding_constraints"),
            "violations_at_optimum": o.get("violations_at_optimum"), "turnover_from_current": o.get("turnover_from_current"), "search": o.get("search"), "cardinality": o.get("cardinality"), "theme_lookthrough": o.get("theme_lookthrough")}


def _optimize_universe(v: dict, tmpl: dict, opts: dict, scen: list, cond: list, seed: int, prog=None) -> dict:
    """Вселенная без весов → оптимум на смеси (веса варианта) + оптимумы под сценариями / условными фазами."""
    uni = [str(t) for t in (v.get("universe") or [])]
    if not uni:
        raise ValueError(f"вариант {v['id']}: universe пуст")
    files = tmpl.get("paths_files") or {}
    missing = [t for t in uni if t not in files]
    if missing:
        raise ValueError(f"вариант {v['id']}: нет путей (калибровки) для {missing} — бумаги без модели во вселенную не входят")
    fixed = {k: float(x) for k, x in (tmpl.get("fixed_weights") or {}).items()}
    cur = {k: float(x) for k, x in (tmpl.get("weights_current") or {}).items()}
    excluded = {t: w for t, w in cur.items() if t not in uni and t not in fixed and w > 0}
    inp = {k: x for k, x in tmpl.items() if k not in ("paths_files", "weights_current", "dry_powder_current", "scenario_constraints", "limits", "search")}
    inp["paths_files"] = _restrict(files, uni)
    inp["weights_current"] = {t: w for t, w in cur.items() if t in uni or t in fixed}
    inp["dry_powder_current"] = float(tmpl.get("dry_powder_current", 0.0)) + sum(excluded.values())      # вне вселенной — продано в кэш
    limits = dict(tmpl.get("limits") or {})
    card = dict(limits.get("cardinality") or {})
    if card and card.get("positions_min") is not None and int(card["positions_min"]) > len(uni):
        card["positions_min"] = len(uni); limits["cardinality"] = card
    if limits.get("theme_policy"):
        tp = dict(limits["theme_policy"]); tp["shares"] = {t: x for t, x in (tp.get("shares") or {}).items() if t in uni or t in fixed}; limits["theme_policy"] = tp
    inp["limits"] = limits
    sc = tmpl.get("scenario_constraints")
    if sc:
        inp["scenario_constraints"] = {**sc, "scenarios": [{**s, "paths_files": _restrict(s.get("paths_files") or {}, uni)} for s in (sc.get("scenarios") or [])], "base_paths_files": _restrict(sc.get("base_paths_files") or {}, uni)}
    inp["search"] = opts.get("search") if opts.get("search") is not None else (tmpl.get("search") or {"random_starts": 0, "basin_kicks": 0})
    for k in ("max_paths", "search_paths"):
        if opts.get(k):
            inp[k] = int(opts[k])
    o_mix = po.run(inp, seed)
    if prog:
        prog.tick(note=f"{v['id']}: оптимум на смеси")
    res = {"universe": uni, "excluded_from_universe": excluded, "mixture": _opt_summary(o_mix), "by_scenario": {}, "conditional": {}}
    given = {t: float(w) for t, w in o_mix["proposed_weights"].items()}; given_dp = float(o_mix["dry_powder_weight"])
    base = {k: x for k, x in inp.items() if k != "scenario_constraints"}
    base.update({"starts": ["current", "equal", "empty", "given"], "start_weights": given, "start_dry_powder": given_dp, "search": opts.get("scenario_search") or {"random_starts": 0, "basin_kicks": 0}})
    if opts.get("per_scenario", True):
        for s in scen:
            sfiles = _restrict(s.get("paths_files") or {}, uni)
            if len(sfiles) < len(uni):
                res["by_scenario"][s["id"]] = {"error": f"нет путей для {[t for t in uni if t not in sfiles]}"}; continue
            try:
                res["by_scenario"][s["id"]] = _opt_summary(po.run({**base, "paths_files": sfiles}, seed))
                if prog:
                    prog.tick(note=f"{v['id']}: оптимум под {s['id']}")
            except Exception as e:  # noqa: BLE001 — оптимум под сценарием необязателен; причина — в выход
                res["by_scenario"][s["id"]] = {"error": str(e)[:200]}
    if opts.get("conditional", False):
        for c in cond:
            key = f"{c['scenario_id']}|{c['phase_id']}"; cfiles = _restrict(c.get("paths_files") or {}, uni)
            if len(cfiles) < len(uni):
                res["conditional"][key] = {"error": f"нет путей для {[t for t in uni if t not in cfiles]}"}; continue
            try:
                res["conditional"][key] = _opt_summary(po.run({**base, "paths_files": cfiles}, seed))
                if prog:
                    prog.tick(note=f"{v['id']}: оптимум под фазой {key}")
            except Exception as e:  # noqa: BLE001
                res["conditional"][key] = {"error": str(e)[:200]}
    cols = {"mixture": res["mixture"]} | {k: x for k, x in res["by_scenario"].items() if "weights" in x} | {k: x for k, x in res["conditional"].items() if "weights" in x}
    res["weights_by_scenario"] = {t: {c: round(float(x["weights"].get(t, 0.0)), 4) for c, x in cols.items()} for t in uni}
    res["dry_powder_by_scenario"] = {c: round(float(x["dry_powder"]), 4) for c, x in cols.items()}
    return res


def run(inputs: dict, seed: int) -> dict:
    variants = [dict(v) for v in (inputs.get("variants") or [])]
    if not variants:
        raise ValueError("variants пуст")
    ids = [str(v["id"]) for v in variants]
    if len(set(ids)) != len(ids):
        raise ValueError("id вариантов должны быть уникальны")
    tmpl = inputs.get("optimizer_inputs") or {}
    uopts = inputs.get("universe_options") or {}
    optimized = {}
    n_uni = sum(1 for v in variants if v.get("universe") is not None)
    prog = None
    if n_uni:
        from engine.progress import Progress
        per = 1 + (len(inputs.get("scenarios") or []) if uopts.get("per_scenario", True) else 0) + (len(inputs.get("conditional") or []) if uopts.get("conditional", False) else 0)
        prog = Progress("portfolio_compare", inputs, total=n_uni * per); prog.stage_start("universes", n_uni * per, note=f"вселенных {n_uni}, вызовов оптимизатора на вселенную {per}")
    for v in variants:                                                       # 1.1.0: вселенная → веса через оптимизатор (до загрузки путей)
        if v.get("universe") is not None:
            if not tmpl:
                raise ValueError(f"вариант {v['id']}: universe требует optimizer_inputs")
            optimized[str(v["id"])] = r = _optimize_universe(v, tmpl, uopts, inputs.get("scenarios") or [], inputs.get("conditional") or [], seed, prog)
            v["weights"] = dict(r["mixture"]["weights"]); v["dry_powder"] = r["mixture"]["dry_powder"]
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
                      "feasible": (None if viol is None else (len(viol) == 0)), "optimized": optimized.get(vid)}
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
    if prog:
        prog.finish("вселенные посчитаны; картины и ранжирование")
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
            "universe_mode": ({"variants": list(optimized), "options": {"per_scenario": uopts.get("per_scenario", True), "conditional": uopts.get("conditional", False), "max_paths": uopts.get("max_paths"), "search_paths": uopts.get("search_paths"), "search": uopts.get("search"), "scenario_search": uopts.get("scenario_search")},
                              "note": "веса варианта = оптимум на смеси с лимитами владельца и сценарными гейтами; оптимумы под сценариями — без гейтов (probability = 1); 0 = не покупать / продать под этим сценарием; позиции вне вселенной считаются проданными в кэш в стартовой точке"} if optimized else None),
            "assumptions": ["позиции без путей (fixed_weights) — плоская доходность 1.0", "смесь §6 — взвешенная эмпирическая, impacts диагностические (§7)",
                            "тема — Σ w·share по выручке (Theme Look-through v1.0)", "нарушения лимитов — по точке, без поиска; разрыв ≠ приказ"],
            "decision": "none"}
