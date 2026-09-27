"""Срез 2 Stability Test: пересимуляция вместо прокси.
company_mc 2.4.0 — simulate_paths(inputs, seed): пути компании в памяти (r3/r5/r8/maxdd5/path_id) с теми же общими шоками
(global_seed, chunk) + inputs.perturbation {growth_shift, margin_shift, mult_factor, rho_shift, milestone_prob_shift}; run() не меняется.
milestone_mc — P.milestone_prob_shift (абсолютный сдвиг вероятности вехи, клип [0,1]).
portfolio_stability 1.2.0 — stability.resimulate {calibrations, equity_value_0, joint_layer_spec, global_seed, chunk}: семейства
terminal_margin (точная маржа ±5 п.п. через margin_shift вместо прокси), milestone (±10 п.п. вероятности вех у компаний с
milestone_model), driver_knockout (материальные драйверы: knockout у компаний с положительной экспозицией — снятие
structural_support, отрицательная экспозиция бонуса не получает); критерий §7 driver_knockout_feasible_replacement оценивается."""
from pathlib import Path

ROOT = Path("C:/openclaw-lab/calc")


def patch(path, reps):
    p = ROOT / path; s = p.read_text(encoding="utf-8")
    for a, b in reps:
        assert s.count(a) == 1, (path, a[:70]); s = s.replace(a, b)
    p.write_text(s, encoding="utf-8", newline="\n"); print("patched", path)


# ---------------------------------------------------------------- milestone_mc: сдвиг вероятности вехи
patch("engine/milestone_mc.py", [
    ('''def simulate_milestones(draw, cal: dict, eff: dict):''', '''def simulate_milestones(draw, cal: dict, eff: dict, prob_shift: float = 0.0):'''),
    ('''        p = float(m["probability"])
        logit = math.log(p / (1 - p)) if 0 < p < 1 else (30.0 if p >= 1 else -30.0)''',
     '''        p = min(1.0, max(0.0, float(m["probability"]) + float(prob_shift)))   # prob_shift — возмущение Stability (срез 2), по умолчанию 0
        logit = math.log(p / (1 - p)) if 0 < p < 1 else (30.0 if p >= 1 else -30.0)'''),
    ('''    ach, failed = simulate_milestones(draw, cal, eff)
    onset_id = mm["service_onset_milestone"]''', '''    ach, failed = simulate_milestones(draw, cal, eff, float(P.get("milestone_prob_shift", 0.0)))
    onset_id = mm["service_onset_milestone"]'''),
])

# ---------------------------------------------------------------- company_mc: simulate_paths
patch("engine/company_mc.py", [
    ('''def run(inputs: dict, seed: int) -> dict:
    cal = copy.deepcopy(_normalize(inputs["calibration"]))
    E0 = float(inputs["equity_value_0"]); sim = cal["simulation"]
    paths = int(inputs.get("paths") or sim["paths"]); seed_used = int(inputs.get("seed_override") or sim.get("seed", seed))
    chunk = int(inputs.get("chunk", 50000)); quantiles = sim.get("store_summary_quantiles", [0.05, 0.25, 0.5, 0.75, 0.95])
    P0 = {"growth_shift": 0.0, "margin_shift": 0.0, "mult_factor": 1.0, "rho_shift": 0.0}
    C, fixed = _factor_corr(cal.get("dependencies") or {})
    # срез 2: совместный слой
    joint = None; knockout_applied = []
    js = cal.get("joint_simulation"); mapping = cal.get("driver_parameter_mapping") or []
    if mapping:
        spec = inputs.get("joint_layer_spec")
        if not spec:
            raise ValueError("driver_parameter_mapping задан, но inputs.joint_layer_spec (Joint_Simulation_Layer_Schema) не передан")
        drivers = list((js or {}).get("active_drivers") or [m["driver_id"] for m in mapping])
        adverse = {}
        for d in inputs.get("adverse_driver_stress") or []:
            m = next((m for m in mapping if m["driver_id"] == d), None)
            sig = ((m or {}).get("stability") or {}).get("adverse_driver_stress", {}).get("driver_sigma")
            if sig is None:
                raise ValueError(f"adverse_driver_stress: у {d} нет stability.adverse_driver_stress.driver_sigma")
            adverse[d] = float(sig)
        joint = {"spec": spec, "drivers": drivers, "global_seed": int(inputs.get("global_seed", seed_used)), "scenario": inputs.get("scenario"), "adverse": adverse}
        if inputs.get("knockout"):
            knockout_applied = _apply_knockout(cal, list(inputs["knockout"]))
    store = bool(inputs.get("store_paths"))''',
     '''def _prepare(inputs: dict, seed: int):
    """Общая подготовка run() и simulate_paths(): нормализованная калибровка, E0, число путей, seed, chunk, квантили, P0, корреляция
    факторов, совместный слой (spec, драйверы, global_seed, сценарий, adverse), knockout."""
    cal = copy.deepcopy(_normalize(inputs["calibration"]))
    E0 = float(inputs["equity_value_0"]); sim = cal["simulation"]
    paths = int(inputs.get("paths") or sim["paths"]); seed_used = int(inputs.get("seed_override") or sim.get("seed", seed))
    chunk = int(inputs.get("chunk", 50000)); quantiles = sim.get("store_summary_quantiles", [0.05, 0.25, 0.5, 0.75, 0.95])
    P0 = {"growth_shift": 0.0, "margin_shift": 0.0, "mult_factor": 1.0, "rho_shift": 0.0}
    C, fixed = _factor_corr(cal.get("dependencies") or {})
    # срез 2: совместный слой
    joint = None; knockout_applied = []
    js = cal.get("joint_simulation"); mapping = cal.get("driver_parameter_mapping") or []
    if mapping:
        spec = inputs.get("joint_layer_spec")
        if not spec:
            raise ValueError("driver_parameter_mapping задан, но inputs.joint_layer_spec (Joint_Simulation_Layer_Schema) не передан")
        drivers = list((js or {}).get("active_drivers") or [m["driver_id"] for m in mapping])
        adverse = {}
        for d in inputs.get("adverse_driver_stress") or []:
            m = next((m for m in mapping if m["driver_id"] == d), None)
            sig = ((m or {}).get("stability") or {}).get("adverse_driver_stress", {}).get("driver_sigma")
            if sig is None:
                raise ValueError(f"adverse_driver_stress: у {d} нет stability.adverse_driver_stress.driver_sigma")
            adverse[d] = float(sig)
        joint = {"spec": spec, "drivers": drivers, "global_seed": int(inputs.get("global_seed", seed_used)), "scenario": inputs.get("scenario"), "adverse": adverse}
        if inputs.get("knockout"):
            knockout_applied = _apply_knockout(cal, list(inputs["knockout"]))
    return cal, E0, paths, seed_used, chunk, quantiles, P0, fixed, joint, knockout_applied


def simulate_paths(inputs: dict, seed: int) -> dict:
    """Пути компании в памяти (срез 2 Stability): те же общие шоки (global_seed, chunk → выравнивание по path_id с нормативным
    прогоном при равных chunk), опционально inputs.perturbation {growth_shift, margin_shift, mult_factor, rho_shift,
    milestone_prob_shift} и inputs.knockout. Возвращает {"paths": {r3, r5, r8, maxdd5, b3, b5, b8, path_id}, "meta", "summary"}."""
    cal, E0, paths, seed_used, chunk, quantiles, P0, fixed, joint, knockout_applied = _prepare(inputs, seed)
    P = dict(P0); P.update({k: float(v) for k, v in (inputs.get("perturbation") or {}).items()})
    r = _run_once(cal, E0, paths, seed_used, chunk, P, quantiles, joint, keep_paths=True)
    arrays = r.pop("_paths")
    meta = {"ticker": cal.get("ticker"), "model_version": VERSION, "global_seed": (joint or {}).get("global_seed", seed_used), "seed": seed_used, "chunk": chunk, "paths": paths,
            "joint": bool(joint), "scenario": (inputs.get("scenario") or {}).get("id", "BASE"), "equity_value_0": E0, "archetype": cal["archetype"],
            "perturbation": {k: v for k, v in P.items() if v not in (0.0, 1.0)}, "knockout_applied": knockout_applied, "path_id_rule": "path_id = chunk_index*chunk + i"}
    return {"paths": arrays, "meta": meta, "summary": {"median_CAGR_5Y": r["return"]["median_CAGR_5Y"], "P_loss_gt_30pct_5Y": r["downside"]["P_loss_gt_30pct_5Y"], "ES5": r["downside"]["expected_shortfall_5pct_5Y"]}}


def run(inputs: dict, seed: int) -> dict:
    cal, E0, paths, seed_used, chunk, quantiles, P0, fixed, joint, knockout_applied = _prepare(inputs, seed)
    store = bool(inputs.get("store_paths"))'''),
    ('VERSION = "2.3.2"', 'VERSION = "2.4.0"'),
])

# ---------------------------------------------------------------- portfolio_stability 1.2.0
patch("engine/portfolio_stability.py", [
    ('VERSION = "1.1.0"', 'VERSION = "1.2.0"'),
    ('FAMILIES = ("return_shift", "terminal", "correlation", "combined", "loo")', 'FAMILIES = ("return_shift", "terminal", "correlation", "combined", "loo", "milestone", "driver_knockout")'),
    ('''- milestones ±10 п.п. и driver knockout (§3.5): на уровне пути не воспроизводятся → not_testable (пересимуляция — следующий срез);
  материальные драйверы (взвешенная |экспозиция| ≥ 0.30) перечисляются по inputs.driver_exposures;''',
     '''- milestones ±10 п.п. и driver knockout (§3.5): без stability.resimulate — not_testable; с resimulate (1.2.0, срез 2) —
  ПЕРЕСИМУЛЯЦИЯ company_mc.simulate_paths на тех же общих шоках (global_seed, chunk): маржа ±5 п.п. точно (margin_shift вместо
  прокси), вероятность вех ±10 п.п. (milestone_prob_shift) у компаний с milestone_model, knockout материальных драйверов
  (взвешенная |экспозиция| ≥ 0.30) — снятие structural_support (company_mc inputs.knockout) у компаний с положительной
  экспозицией, отрицательная экспозиция бонуса не получает; критерий §7 driver_knockout_feasible_replacement оценивается;'''),
    ('''                       "families": null | ["return_shift","terminal","correlation","combined","loo"] (частичный перепрогон: partial=true)}}''',
     '''                       "families": null | ["return_shift","terminal","correlation","combined","loo","milestone","driver_knockout"] (частичный перепрогон: partial=true),
                       "resimulate": null | {"calibrations": {tk: cal}, "equity_value_0": {tk: E0}, "joint_layer_spec": spec, "global_seed": int,
                                             "chunk": 50000, "milestone_pp": 0.10}}'''),
    ('''from engine import portfolio_optimizer as po
from engine import portfolio_paths''', '''from engine import company_mc
from engine import portfolio_optimizer as po
from engine import portfolio_paths'''),
    # воркер: состояние пересимуляции + операция resim
    ('''def _worker_init(inputs: dict, n: int, cw: dict, cdp: float) -> None:
    files = inputs["paths_files"]; tick = sorted(files)
    base = _copy({t: portfolio_paths.load_paths(files[t]) for t in tick}, n)
    _W.update({"inp": inputs, "n": n, "tick": tick, "base": base, "cw": cw, "cdp": cdp})


def _apply_ops(d: dict, ops: list, tick: list) -> dict:
    for op in ops:
        if op[0] == "scale":
            _scale(d, op[1], op[2])
        elif op[0] == "corr":
            _iman_conover(d, tick, np.array(op[1], dtype=float), int(op[2]))
    return d''', '''def _worker_init(inputs: dict, n: int, cw: dict, cdp: float) -> None:
    files = inputs["paths_files"]; tick = sorted(files)
    base = _copy({t: portfolio_paths.load_paths(files[t]) for t in tick}, n)
    _W.update({"inp": inputs, "n": n, "tick": tick, "base": base, "cw": cw, "cdp": cdp, "resim": ((inputs.get("stability") or {}).get("resimulate") or None)})


def _resimulate(t: str, perturbation: dict | None, knockout: list | None) -> dict:
    """Пути компании t на общих шоках (global_seed/chunk из base.meta) с возмущением или knockout — срез 2."""
    rs = _W["resim"]; n = _W["n"]; meta = _W["base"][t]["meta"]
    inp = {"calibration": rs["calibrations"][t], "equity_value_0": float(rs["equity_value_0"][t]), "joint_layer_spec": rs.get("joint_layer_spec"),
           "global_seed": int(rs.get("global_seed", meta.get("global_seed"))), "chunk": int(rs.get("chunk", meta.get("chunk") or 50000)), "paths": n}
    if perturbation:
        inp["perturbation"] = perturbation
    if knockout:
        inp["knockout"] = list(knockout)
    r = company_mc.simulate_paths(inp, int(meta.get("seed") or inp["global_seed"]))
    arr = r["paths"]
    return {k: arr[k][:n] for k in ("r3", "r5", "r8", "maxdd5")} | {"summary": r["summary"], "knockout_applied": r["meta"].get("knockout_applied")}


def _apply_ops(d: dict, ops: list, tick: list) -> dict:
    for op in ops:
        if op[0] == "scale":
            _scale(d, op[1], op[2])
        elif op[0] == "corr":
            _iman_conover(d, tick, np.array(op[1], dtype=float), int(op[2]))
        elif op[0] == "resim":
            r = _resimulate(op[1], op[2], op[3])
            for k in ("r3", "r5", "r8", "maxdd5"):
                d[op[1]][k] = r[k]
            d.setdefault("_resim_info", {})[op[1]] = {"summary": r["summary"], "knockout_applied": r["knockout_applied"]}
    return d'''),
    ('''    else:
        res = _opt(inp, d, cw, cdp)
        if task.get("measure_corr"):
            res["achieved_C1"] = _rank_corr(d, tick).tolist()''', '''    else:
        res = _opt(inp, d, cw, cdp)
        if task.get("measure_corr"):
            res["achieved_C1"] = _rank_corr(d, tick).tolist()
        if d.get("_resim_info"):
            res["resim_info"] = d["_resim_info"]'''),
    # сборка задач: маржа точно при resimulate; вехи; knockout
    ('''    margins = {t: float(m) for t, m in (cfg.get("terminal_margins") or {}).items() if m is not None}
    incl_thr = float(cfg["inclusion_threshold"])''', '''    margins = {t: float(m) for t, m in (cfg.get("terminal_margins") or {}).items() if m is not None}
    incl_thr = float(cfg["inclusion_threshold"])
    resim = cfg.get("resimulate") or None
    if resim:
        miss = [t for t in tick if t not in (resim.get("calibrations") or {}) or t not in (resim.get("equity_value_0") or {})]
        if miss:
            raise ValueError(f"resimulate: нет калибровки/equity_value_0 для {miss}")'''),
    ('''        m = margins.get(t)
        if m is None or m <= 0.02:
            term_sens[t]["margin"] = "not_testable" + ("" if m is None else "_margin_near_zero")
            continue
        for sgn in (-1, 1):
            delta = sgn * float(cfg["margin_pp"]); f = float(np.clip((m + delta) / m, 0.1, 3.0))
            add("terminal_margin", f"{t}:{delta * 100:+.0f}pp", [("scale", t, {"r5": f, "r8": f})], {"company": t, "margin_pp": delta, "proxy_factor": f, "terminal_margin": m}, ("margin", t, f"{delta * 100:+.0f}pp", round(f, 4)))''',
     '''        if resim:
            # точная маржа: пересимуляция с margin_shift (для C — сервисная маржа через тот же P.margin_shift)
            for sgn in (-1, 1):
                delta = sgn * float(cfg["margin_pp"])
                add("terminal_margin", f"{t}:{delta * 100:+.0f}pp", [("resim", t, {"margin_shift": delta}, None)], {"company": t, "margin_pp": delta, "method": "resimulation"}, ("margin", t, f"{delta * 100:+.0f}pp", "resimulation"))
            continue
        m = margins.get(t)
        if m is None or m <= 0.02:
            term_sens[t]["margin"] = "not_testable" + ("" if m is None else "_margin_near_zero")
            continue
        for sgn in (-1, 1):
            delta = sgn * float(cfg["margin_pp"]); f = float(np.clip((m + delta) / m, 0.1, 3.0))
            add("terminal_margin", f"{t}:{delta * 100:+.0f}pp", [("scale", t, {"r5": f, "r8": f})], {"company": t, "margin_pp": delta, "proxy_factor": f, "terminal_margin": m}, ("margin", t, f"{delta * 100:+.0f}pp", round(f, 4)))
    # --- 3.4 вехи ±10 п.п. (только с пересимуляцией)
    ms_companies = [t for t in tick if t in (cfg.get("milestone_companies") or [])]
    for t in (ms_companies if (resim and "milestone" in fam) else []):
        for sgn in (-1, 1):
            delta = sgn * float(cfg.get("milestone_pp", 0.10))
            add("milestone", f"{t}:ms{delta * 100:+.0f}pp", [("resim", t, {"milestone_prob_shift": delta}, None)], {"company": t, "milestone_pp": delta, "method": "resimulation"}, ("milestone", t, f"{delta * 100:+.0f}pp"))'''),
    ('''    driver_sens = {"status": "not_testable_path_level", "reason": "выбивание драйвера требует пересимуляции company_mc с обнулённым положительным вкладом mapping — следующий срез",
                   "material_drivers": material, "material_rule": "Σ_i w_i·|exposure_i|/2 ≥ 0.30 × Σ w_i (экспозиция ±2 → 1.0, ±1 → 0.5)"}''',
     '''    if resim and "driver_knockout" in fam and material:
        for md in material:
            dname = md["driver"]
            hit = [t for t in tick if float(expo.get(t, {}).get(dname, 0.0)) > 0]        # только положительная экспозиция — без искусственного бонуса
            if not hit:
                continue
            add("driver_knockout", f"ko:{dname}", [("resim", t, None, [dname]) for t in hit], {"driver": dname, "companies": hit}, ("ko", dname, hit))
        driver_sens = {"status": "resimulated", "method": "company_mc knockout (снятие structural_support) у компаний с положительной экспозицией; отрицательная экспозиция без бонуса",
                       "material_drivers": material, "material_rule": "Σ_i w_i·|exposure_i|/2 ≥ 0.30 × Σ w_i (экспозиция ±2 → 1.0, ±1 → 0.5)", "runs": {}}
    else:
        driver_sens = {"status": "not_testable_path_level" if not resim else "not_run", "reason": "выбивание драйвера требует пересимуляции (stability.resimulate)" if not resim else "семейство driver_knockout не запрошено",
                       "material_drivers": material, "material_rule": "Σ_i w_i·|exposure_i|/2 ≥ 0.30 × Σ w_i (экспозиция ±2 → 1.0, ±1 → 0.5)"}'''),
    ('''        if key[0] == "ret":''', '''        if key[0] == "milestone":
            term_sens.setdefault(key[1], {"multiple": {}, "margin": {}, "milestone_probability": {}})
            if not isinstance(term_sens[key[1]].get("milestone_probability"), dict):
                term_sens[key[1]]["milestone_probability"] = {}
            term_sens[key[1]]["milestone_probability"][key[2]] = {"weight": r["weights"].get(key[1]), "feasible": r["feasible"], "median_CAGR_5Y": r["median_CAGR_5Y"], "method": "resimulation",
                                                                   "company_summary": (r.get("resim_info") or {}).get(key[1], {}).get("summary")}
            continue
        if key[0] == "ko":
            driver_sens["runs"][key[1]] = {"companies": key[2], "feasible": r["feasible"], "weights": r["weights"], "median_CAGR_5Y": r["median_CAGR_5Y"], "ES5": r["ES5"],
                                           "turnover_from_central": r["turnover_from_central"], "violations": r["violations"],
                                           "company_summaries": {t: v.get("summary") for t, v in (r.get("resim_info") or {}).items()}, "knockout_applied": {t: v.get("knockout_applied") for t, v in (r.get("resim_info") or {}).items()}}
            continue
        if key[0] == "ret":'''),
    ('''        elif key[0] == "margin":
            term_sens[key[1]]["margin"][key[2]] = {"weight": r["weights"].get(key[1]), "feasible": r["feasible"], "median_CAGR_5Y": r["median_CAGR_5Y"], "proxy_factor": key[3]}''',
     '''        elif key[0] == "margin":
            term_sens[key[1]]["margin"][key[2]] = {"weight": r["weights"].get(key[1]), "feasible": r["feasible"], "median_CAGR_5Y": r["median_CAGR_5Y"],
                                                   **({"method": "resimulation", "company_summary": (r.get("resim_info") or {}).get(key[1], {}).get("summary")} if key[3] == "resimulation" else {"proxy_factor": key[3]})}'''),
    # популяция §5–6: knockout и вехи входят в прогоны (это возмущения предпосылок)
    ('''    runs = [r for r in results if r["family"] != "loo"]   # популяция §5–6 (LOO — отдельно)''',
     '''    runs = [r for r in results if r["family"] != "loo"]   # популяция §5–6 (LOO — отдельно); knockout и вехи — тоже возмущения предпосылок'''),
    ('''                "driver_knockout_feasible_replacement": {"value": None, "pass": None, "status": "not_evaluated (driver knockout not testable at path level)"},''',
     '''                "driver_knockout_feasible_replacement": ({"value": round(float(np.mean([v["feasible"] for v in driver_sens["runs"].values()])), 4), "limit": 1.0,
                                                          "pass": bool(all(v["feasible"] for v in driver_sens["runs"].values())), "infeasible_drivers": [d for d, v in driver_sens["runs"].items() if not v["feasible"]]}
                                                         if driver_sens.get("status") == "resimulated" and driver_sens.get("runs") else
                                                         {"value": None, "pass": None, "status": "not_evaluated (driver knockout requires stability.resimulate)"}),'''),
    ('''    ah = hashlib.sha256(json.dumps({"inputs": {k: v for k, v in inputs.items() if k != "paths_files"}, "paths_meta": {t: base[t]["meta"] for t in tick}, "n": n, "cfg": cfg, "seed": seed, "version": VERSION},''',
     '''    ah = hashlib.sha256(json.dumps({"inputs": {k: v for k, v in inputs.items() if k not in ("paths_files", "stability")}, "paths_meta": {t: base[t]["meta"] for t in tick}, "n": n, "cfg": {k: v for k, v in cfg.items() if k != "resimulate"}, "resimulate": bool(resim), "seed": seed, "version": VERSION},'''),
    ('''            "perturbation_config": {k: v for k, v in cfg.items() if k not in ("driver_exposures",)}, "assumptions_hash": ah,''',
     '''            "perturbation_config": {k: v for k, v in cfg.items() if k not in ("driver_exposures", "resimulate")}, "resimulate": bool(resim), "assumptions_hash": ah,'''),
    ('''                            "terminal margin — прокси на уровне пути ((m+δ)/m на Y5/Y8), не пересимуляция", "terminal multiple — лог-множитель ко всем горизонтам (точно для базы FCF_multiple)",''',
     '''                            ("terminal margin — пересимуляция company_mc (margin_shift) на общих шоках" if resim else "terminal margin — прокси на уровне пути ((m+δ)/m на Y5/Y8), не пересимуляция"), "terminal multiple — лог-множитель ко всем горизонтам (точно для базы FCF_multiple)",'''),
    ('''                            "LOO-прогоны не входят в статистику включения/весов", "milestones и driver knockout — not_testable до пересимуляции"],''',
     '''                            "LOO-прогоны не входят в статистику включения/весов", ("milestones ±10 п.п. и driver knockout — пересимуляция (срез 2)" if resim else "milestones и driver knockout — not_testable до пересимуляции")],'''),
])

# ---------------------------------------------------------------- тесты
t = ROOT / "tests/test_company_mc.py"; u = t.read_text(encoding="utf-8")
u = u.rstrip("\n") + '''


def test_simulate_paths_matches_run_and_supports_perturbation(tmp_path):
    from tests.test_portfolio_paths import _joint, SPEC
    import numpy as np
    from engine import portfolio_paths as pp
    c = _joint(cal_mature(), "AAA")
    stored = cm.run({"calibration": c, "equity_value_0": 30e9, "joint_layer_spec": SPEC, "global_seed": 101, "paths": 6000, "convergence_check": False, "robustness": False, "store_paths": True, "_runs_dir": str(tmp_path), "_run_id": "t-AAA-sp"}, 0)
    disk = pp.load_paths(stored["paths_file"])
    mem = cm.simulate_paths({"calibration": c, "equity_value_0": 30e9, "joint_layer_spec": SPEC, "global_seed": 101, "paths": 6000}, 0)
    assert np.array_equal(mem["paths"]["r5"], disk["r5"]) and np.array_equal(mem["paths"]["path_id"], disk["path_id"])     # память = диск
    sub = cm.simulate_paths({"calibration": c, "equity_value_0": 30e9, "joint_layer_spec": SPEC, "global_seed": 101, "paths": 2000, "chunk": 50000}, 0)
    assert np.array_equal(sub["paths"]["r5"], disk["r5"][:2000])                                                            # усечённый прогон = первые пути
    up = cm.simulate_paths({"calibration": c, "equity_value_0": 30e9, "joint_layer_spec": SPEC, "global_seed": 101, "paths": 6000, "perturbation": {"margin_shift": 0.05}}, 0)
    assert np.median(up["paths"]["r5"]) > np.median(disk["r5"]) and up["meta"]["perturbation"] == {"margin_shift": 0.05}   # маржа +5 п.п. → стоимость выше
    ko = cm.simulate_paths({"calibration": c, "equity_value_0": 30e9, "joint_layer_spec": SPEC, "global_seed": 101, "paths": 6000, "knockout": ["AI_COMPUTE_DEMAND"]}, 0)
    assert ko["meta"]["knockout_applied"] and np.median(ko["paths"]["r5"]) < np.median(disk["r5"])                        # снятие поддержки → ниже
'''
t.write_text(u, encoding="utf-8", newline="\n"); print("test_company_mc patched")

t = ROOT / "tests/test_milestone_mc.py"; u = t.read_text(encoding="utf-8")
u = u.rstrip("\n") + '''


def test_milestone_probability_shift_changes_onset():
    from engine import company_mc as cm
    from tests.test_company_mc import cal_milestone
    c = cal_milestone()
    base = cm.simulate_paths({"calibration": c, "equity_value_0": 5e9, "paths": 6000}, 0)
    up = cm.simulate_paths({"calibration": c, "equity_value_0": 5e9, "paths": 6000, "perturbation": {"milestone_prob_shift": 0.10}}, 0)
    down = cm.simulate_paths({"calibration": c, "equity_value_0": 5e9, "paths": 6000, "perturbation": {"milestone_prob_shift": -0.10}}, 0)
    assert up["summary"]["median_CAGR_5Y"] >= base["summary"]["median_CAGR_5Y"] >= down["summary"]["median_CAGR_5Y"]
    assert up["summary"]["P_loss_gt_30pct_5Y"] <= down["summary"]["P_loss_gt_30pct_5Y"]
'''
t.write_text(u, encoding="utf-8", newline="\n"); print("test_milestone_mc patched")

t = ROOT / "tests/test_portfolio_stability.py"; u = t.read_text(encoding="utf-8")
u = u.rstrip("\n") + '''


def test_resimulation_families(paths):
    """Срез 2: точная маржа, вехи и knockout через пересимуляцию (workers=1 — в процессе; синтетика на 3000 путях)."""
    from tests.test_company_mc import cal_mature, cal_capital, cal_milestone
    from tests.test_portfolio_paths import _joint, SPEC
    cals = {"AAA": _joint(cal_mature(), "AAA"), "BBB": _joint(cal_mature(), "BBB"), "CCC": _joint(cal_capital(), "CCC")}
    cals["AAA"]["revenue_model"]["segments"]["Core"]["initial_growth"] = {"distribution": "triangular", "min": 0.20, "mode": 0.30, "max": 0.40}
    cals["BBB"]["revenue_model"]["segments"]["Core"]["initial_growth"] = {"distribution": "triangular", "min": -0.10, "mode": 0.02, "max": 0.10}; cals["BBB"]["valuation"]["Y5"]["multiple"] = {"distribution": "triangular", "min": 10, "mode": 14, "max": 18}
    inp = _inputs(paths)
    inp["stability"] = {**inp["stability"], "workers": 1, "families": ["terminal", "milestone", "driver_knockout"],
                        "resimulate": {"calibrations": cals, "equity_value_0": {"AAA": 30e9, "BBB": 30e9, "CCC": 30e9}, "joint_layer_spec": SPEC, "global_seed": 101, "chunk": 6000}}
    out = ps.run(inp, 11)
    assert out["resimulate"] is True and out["runs_by_family"]["terminal_margin"] == 6 and "terminal_multiple" in out["runs_by_family"]
    m = out["terminal_sensitivity"]["AAA"]["margin"]
    assert m["+5pp"]["method"] == "resimulation" and m["+5pp"]["company_summary"]["median_CAGR_5Y"] > m["-5pp"]["company_summary"]["median_CAGR_5Y"]
    assert out["terminal_sensitivity"]["CCC"]["margin"]["+5pp"]["method"] == "resimulation"                                # B без прокси — теперь тестируется
    ds = out["driver_sensitivity"]; assert ds["status"] == "resimulated" and "AI_COMPUTE_DEMAND" in ds["runs"]
    ko = ds["runs"]["AI_COMPUTE_DEMAND"]; assert set(ko["companies"]) == {"AAA", "BBB"} and all(ko["knockout_applied"][t] for t in ("AAA", "BBB"))   # CCC без экспозиции — не трогаем
    crit = out["portfolio_stability_classification"]["criteria"]["driver_knockout_feasible_replacement"]; assert crit["pass"] in (True, False) and crit["value"] is not None
    assert out["runs_by_family"].get("milestone") is None                                                                    # milestone_companies пуст — вех нет
    assert all(fam in out["families"] for fam in ("terminal", "milestone", "driver_knockout")) and out["partial"] is True
'''
t.write_text(u, encoding="utf-8", newline="\n"); print("test_portfolio_stability patched")
