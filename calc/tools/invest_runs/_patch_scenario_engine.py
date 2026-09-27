"""Scenario Engine v1.0 на хосте: company_mc 2.4.1 (scenario_id + диагностика фаз в отчёте), portfolio_paths 1.2.0 (взвешенная
эмпирическая смесь §6, MedianImpact/ES5Impact/B_s/ScenarioConcentration §7, контракт вероятностей §2), artifact_validator 1.7.0
(режим scenario: §12 hard checks + coverage §9), тесты."""
from pathlib import Path

ROOT = Path("C:/openclaw-lab/calc")


def patch(path, reps):
    p = ROOT / path; s = p.read_text(encoding="utf-8")
    for a, b in reps:
        assert s.count(a) == 1, (path, a[:70]); s = s.replace(a, b)
    p.write_text(s, encoding="utf-8", newline="\n"); print("patched", path)


# ------------------------------------------------------------------ company_mc: scenario_id + диагностика фаз
patch("engine/company_mc.py", [
    ('VERSION = "2.4.0"', 'VERSION = "2.4.1"'),
    ('''            "joint": bool(joint), "scenario": (inputs.get("scenario") or {}).get("id", "BASE"), "equity_value_0": E0, "archetype": cal["archetype"],''',
     '''            "joint": bool(joint), "scenario": _scenario_id(inputs.get("scenario")), "equity_value_0": E0, "archetype": cal["archetype"],'''),
    ('''                "chunk": chunk, "paths": paths, "joint": bool(joint), "scenario": (inputs.get("scenario") or {}).get("id", "BASE"), "equity_value_0": E0,''',
     '''                "chunk": chunk, "paths": paths, "joint": bool(joint), "scenario": _scenario_id(inputs.get("scenario")), "equity_value_0": E0,'''),
    ('''                                                        "scenario": (inputs.get("scenario") or {}).get("id", "BASE"), "adverse_driver_stress": sorted(joint["adverse"]),''',
     '''                                                        "scenario": _scenario_id(inputs.get("scenario")), "adverse_driver_stress": sorted(joint["adverse"]),
                                                        "scenario_phases": (joint_layer.scenario_diagnostics(joint["spec"], joint["scenario"], joint["drivers"], min(chunk, paths), QUARTERS,
                                                                                                             int(np.random.SeedSequence([joint["global_seed"], 0]).generate_state(1)[0]))
                                                                            if joint_layer.is_phased(joint.get("scenario")) else None),
                                                        "scenario_mode": ("phased" if joint_layer.is_phased(joint.get("scenario")) else ("constant_legacy_non_normative" if (joint.get("scenario") or {}).get("driver_overrides") else "BASE")),'''),
    ('''def _prepare(inputs: dict, seed: int):''', '''def _scenario_id(sc: dict | None) -> str:
    return str((sc or {}).get("scenario_id") or (sc or {}).get("id") or "BASE")


def _prepare(inputs: dict, seed: int):'''),
])

# ------------------------------------------------------------------ portfolio_paths: взвешенная смесь
p = ROOT / "engine/portfolio_paths.py"; s = p.read_text(encoding="utf-8")
start = s.index("def _run_mixture(inputs: dict, seed: int) -> dict:")
s = s[:start] + '''def _wquantile(x: np.ndarray, w: np.ndarray, q: float) -> float:
    o = np.argsort(x); cw = np.cumsum(w[o]); cw /= cw[-1]
    return float(x[o][np.searchsorted(cw, q, side="left").clip(0, len(x) - 1)])


def _wmetrics(pv: np.ndarray, w: np.ndarray, years: int) -> dict:
    """Метрики по взвешенной эмпирической распределённости (Scenario Engine §6): медиана/квантили, P(loss), ES5 — по массе 5 %."""
    cagr = np.power(np.clip(pv, 1e-12, None), 1.0 / years) - 1.0; ret = pv - 1.0
    o = np.argsort(ret); cw = np.cumsum(w[o]); tail = cw <= 0.05 * cw[-1] + 1e-15
    if not tail.any():
        tail[0] = True
    es5 = float(np.average(ret[o][tail], weights=w[o][tail]))
    return {"median_CAGR": _wquantile(cagr, w, 0.5), "P_2x": float(np.average(pv >= 2, weights=w)), "P_loss_gt_30pct": float(np.average(pv < 0.7, weights=w)),
            "P_loss_gt_50pct": float(np.average(pv < 0.5, weights=w)), "expected_shortfall_5pct": es5,
            "CAGR_quantiles": {str(q): _wquantile(cagr, w, q) for q in (0.05, 0.25, 0.5, 0.75, 0.95)}}


def _run_mixture(inputs: dict, seed: int) -> dict:
    """Смесь сценариев (Scenario_Engine_Specification_v1.0 §2, §6, §7): scenario-specific пути с общими path_id объединяются как
    взвешенная эмпирическая распределённость (вес p_s/N на исход); BASE = остаток 1 − Σp; при pending-вероятностях — только
    метрики по сценариям (смесь, impacts и ScenarioConcentration — not_testable_pending_owner_probability)."""
    scen = inputs["scenarios"]
    w = {k: float(v) for k, v in (inputs.get("weights") or {}).items()}
    wdp = float(inputs.get("dry_powder_weight", 0.0)); rdp = float(inputs.get("dry_powder_return_annual", 0.0))
    if abs(sum(w.values()) + wdp - 1.0) > 1e-6:
        raise ValueError("веса + dry powder должны давать 1.0")
    ids = [sc["id"] for sc in scen]
    if len(set(ids)) != len(ids) or "BASE" not in ids:
        raise ValueError("scenarios: id уникальны и обязателен BASE")
    base_i = ids.index("BASE")
    pend = [sc["id"] for sc in scen if sc["id"] != "BASE" and sc.get("probability") is None]
    probs = None
    if not pend:
        pn = {sc["id"]: float(sc["probability"]) for sc in scen if sc["id"] != "BASE"}
        if any(v < 0 for v in pn.values()) or sum(pn.values()) > 1.0 + 1e-12:
            raise ValueError(f"вероятности non-BASE сценариев должны быть ≥0 и в сумме ≤1: {pn}")
        probs = {**pn, "BASE": 1.0 - sum(pn.values())}
        if scen[base_i].get("probability") is not None and abs(float(scen[base_i]["probability"]) - probs["BASE"]) > 1e-12:
            raise ValueError("probability BASE задана и не равна остатку 1 − Σp")
    loaded = []
    for sc in scen:
        files = sc.get("paths_files") or {}
        missing = [t for t in w if t not in files]
        if missing:
            raise ValueError(f"сценарий {sc['id']}: нет файлов путей для {missing}")
        loaded.append({t: load_paths(files[t]) for t in w})
    n = min(len(d[t]["r5"]) for d in loaded for t in w)
    ref_ids = loaded[base_i][next(iter(w))]["path_id"][:n]; ref_meta = loaded[base_i][next(iter(w))]["meta"]
    for sc, d in zip(scen, loaded):
        for t in w:
            m = d[t]["meta"]
            if m.get("global_seed") != ref_meta.get("global_seed") or m.get("chunk") != ref_meta.get("chunk") or not np.array_equal(d[t]["path_id"][:n], ref_ids):
                raise ValueError(f"сценарий {sc['id']}, {t}: пути не выровнены по path_id с BASE — смесь не считается")
    per = {sc["id"]: _metrics_for(loaded[j], w, wdp, rdp, n) for j, sc in enumerate(scen)}
    delta = {sid: {h: {k: per[sid][h][k] - per["BASE"][h][k] for k in ("median_CAGR", "P_loss_gt_30pct", "P_loss_gt_50pct", "expected_shortfall_5pct", "P_2x")} for h in ("Y3", "Y5", "Y8")} for sid in ids if sid != "BASE"}
    out = {"model_version": VERSION, "mode": "scenario_mixture", "spec": "Scenario_Engine_Specification_v1.0", "paths": int(n), "weights": w, "dry_powder_weight": wdp, "dry_powder_return_annual": rdp,
           "scenarios": [{"id": sc["id"], "probability": (probs or {}).get(sc["id"], sc.get("probability"))} for sc in scen],
           "by_scenario": per, "scenario_delta_vs_BASE": delta, "decision": "none"}
    if probs is None:
        out.update({"probability_status": "pending_owner_judgment", "pending": pend, "horizons": None, "scenario_impacts": None, "scenario_concentration": None,
                    "note": "смесь, MedianImpact/ES5Impact/B_s и ScenarioConcentration — not_testable_pending_owner_probability (§2); scenario-specific метрики и дельты к BASE доступны"})
        return out
    # взвешенная эмпирическая смесь: каждый исход сценария s с весом p_s/N
    mix = {}
    for h, key, yrs in (("Y3", "r3", 3), ("Y5", "r5", 5), ("Y8", "r8", 8)):
        pvs, ws = [], []
        for j, sc in enumerate(scen):
            pv = np.zeros(n)
            for t, wt in w.items():
                pv += wt * loaded[j][t][key][:n].astype(float)
            pv += wdp * (1.0 + rdp) ** yrs
            pvs.append(pv); ws.append(np.full(n, probs[sc["id"]] / n))
        mix[h] = _wmetrics(np.concatenate(pvs), np.concatenate(ws), yrs)
    impacts = {}
    for sid in ids:
        if sid == "BASE":
            continue
        p_s = probs[sid]; b = per["BASE"]["Y5"]; m = per[sid]["Y5"]
        impacts[sid] = {"probability": p_s, "MedianImpact_Y5": p_s * (m["median_CAGR"] - b["median_CAGR"]), "ES5Impact_Y5": p_s * (m["expected_shortfall_5pct"] - b["expected_shortfall_5pct"]),
                        "adverse_ES_burden_B": p_s * max(0.0, b["expected_shortfall_5pct"] - m["expected_shortfall_5pct"])}
    tot = sum(v["adverse_ES_burden_B"] for v in impacts.values())
    conc = (max(v["adverse_ES_burden_B"] for v in impacts.values()) / tot) if tot > 0 else 0.0
    out.update({"probability_status": "owner_judgment", "horizons": mix, "scenario_impacts": impacts,
                "scenario_concentration": {"value": conc, "no_adverse_scenario_burden": tot <= 0, "warning": conc > 0.50, "hard_limit_breach": conc > 0.60, "rule": "max_s B_s / Σ_s B_s по non-BASE; warning >50 %, hard >60 % (Optimizer v1.0)"},
                "note": "медиана и ES5 нелинейны — impacts диагностические, не аддитивное разложение (§7)"})
    return out
'''
p.write_text(s, encoding="utf-8", newline="\n"); print("patched engine/portfolio_paths.py")
patch("engine/portfolio_paths.py", [
    ('VERSION = "1.1.0"', 'VERSION = "1.2.0"'),
    ('''Смешивание сценариев (1.1.0, ЧЕРНОВИК до Scenario Engine v1.0): вместо paths_files — "scenarios": [{"id", "probability",
"paths_files": {ticker: .npz}}] (сумма вероятностей 1; пути всех сценариев выровнены по path_id — общий global_seed);
по каждому path_id сценарий выбирается детерминированно (mixture_seed) по вероятностям → смесь; в выходе — метрики смеси,
по каждому сценарию отдельно и scenario_delta (медиана/ES5/P(loss) к первому сценарию в списке, обычно BASE);
scenario_concentration — None до определения IMMA.''',
     '''Смесь сценариев (1.2.0, Scenario_Engine_Specification_v1.0): вместо paths_files — "scenarios": [{"id", "probability",
"paths_files": {ticker: .npz}}]; обязателен BASE (вероятность — остаток 1 − Σp, §2); non-BASE с probability null →
pending_owner_judgment: только метрики по сценариям и дельты к BASE. При вероятностях — взвешенная эмпирическая смесь (вес
p_s/N на исход, §6; общие path_id), MedianImpact/ES5Impact/B_s и ScenarioConcentration = max B_s / Σ B_s (§7; warning >50 %,
hard >60 %).'''),
])

# ------------------------------------------------------------------ artifact_validator: режим scenario
patch("engine/artifact_validator.py", [
    ('''    if mode == "dozor_report":
        rep = inputs.get("report")''', '''    if mode == "scenario":
        return _validate_scenario(inputs, ws, rules)
    if mode == "dozor_report":
        rep = inputs.get("report")'''),
    ('''def run(inputs: dict, seed: int) -> dict:
    mode = inputs.get("mode", "workspace")''', '''SCENARIO_SCHEMA_VERSION = "1.0"


def _validate_scenario(inputs: dict, ws: Path, rules: dict) -> dict:
    """Режим scenario (Scenario_Engine_Specification_v1.0 §12): JSON-схема, уникальные id, ацикличность anchor'ов, драйверы в
    таксономии, корни в Joint-схеме, PSD фазовых матриц без ремонта, монотонность стартов (replay), детерминизм, контракт
    вероятностей набора, coverage по компаниям (§9: applicable / unmapped / explicitly_immaterial)."""
    import numpy as np
    from engine import joint_layer as jl
    scen = inputs.get("scenarios") or ([inputs["scenario"]] if inputs.get("scenario") else None)
    if not scen:
        raise ValueError("mode=scenario требует inputs.scenario (dict) или inputs.scenarios (list)")
    schema = _schema(inputs, "scenario_schema_path", f"Scenario_Engine_Schema_v{SCENARIO_SCHEMA_VERSION}.yaml")
    jspec = inputs.get("joint_layer_spec") or _schema(inputs, "joint_layer_spec_path", "Joint_Simulation_Layer_Schema_v1.0.yaml")
    tax_ver = inputs.get("taxonomy_version") or "1.2"
    tax = _taxonomy_ids(ws, tax_ver) or set()
    audit = inputs.get("coverage_audit") or {}
    n_chk = int(inputs.get("replay_paths", 4000)); Q = int(inputs.get("quarters", 32)); seed = int(inputs.get("global_seed", 20260920))
    per = {}; ids_seen = set(); mx_sets = set(); n_err = 0
    for sc in scen:
        sc = _norm(sc); sid = sc.get("scenario_id") or "?"
        errs = _schema_errors(schema, sc); findings: list[dict] = []
        if sid in ids_seen:
            findings.append(_f("SCN-001", "scenario_id", f"дубликат scenario_id {sid}"))
        ids_seen.add(sid); mx_sets.add(sc.get("mutual_exclusion_set"))
        phases = sc.get("phases") or []; pids = [p.get("phase_id") for p in phases]
        if len(set(pids)) != len(pids):
            findings.append(_f("SCN-002", "phases", "phase_id не уникальны"))
        for i, ph in enumerate(phases):
            anc = str((ph.get("effective_from") or {}).get("anchor", "t0"))
            if anc.startswith("phase:") and anc[6:] not in pids[:i]:
                findings.append(_f("SCN-003", f"phases/{i}/effective_from/anchor", f"{anc}: ссылка на фазу не раньше по списку (ацикличность/порядок)"))
            for d, o in (ph.get("driver_overrides") or {}).items():
                if tax and d not in tax:
                    findings.append(_f("SCN-004", f"phases/{i}/driver_overrides/{d}", f"драйвер {d} не в таксономии v{tax_ver}"))
                if float(o.get("volatility_multiplier", 1.0)) <= 0:
                    findings.append(_f("SCN-005", f"phases/{i}/driver_overrides/{d}", "volatility_multiplier ≤ 0"))
                po = o.get("persistence_override")
                if po is not None and not (0.0 <= float(po) <= 0.99):
                    findings.append(_f("SCN-005", f"phases/{i}/driver_overrides/{d}", "persistence_override вне [0, 0.99]"))
            try:
                T = jl.phase_correlation(jspec, ph); me = float(np.linalg.eigvalsh(T).min())
                findings.append(_f("SCN-006", f"phases/{i}/root_correlation_overrides", f"PSD ok, min eig {me:.4f}", "info"))
            except ValueError as e:
                findings.append(_f("SCN-006", f"phases/{i}/root_correlation_overrides", str(e)))
        # replay: монотонность стартов и детерминизм (малый n)
        replay = None
        if phases and not any(f["severity"] == "error" for f in findings) and not errs:
            try:
                drv = sorted({d for ph in phases for d in (ph.get("driver_overrides") or {})})
                drv_known = [d for d in drv if d in ((jspec.get("driver_generation") or {}).get("mappings") or {})] or drv[:1]
                a = jl.driver_shocks(jspec, drv_known, n_chk, Q, seed, scenario=sc); b = jl.driver_shocks(jspec, drv_known, n_chk, Q, seed, scenario=sc)
                det = all(np.array_equal(a[d], b[d]) for d in drv_known)
                diag = jl.scenario_diagnostics(jspec, sc, drv_known, n_chk, Q, seed)
                replay = {"deterministic": det, "phase_start_quantiles": diag["phase_start_quantiles"], "phase_active_share": diag["phase_active_share"], "n_corr_states": diag["n_corr_states"]}
                if not det:
                    findings.append(_f("SCN-007", "phases", "повторный прогон дал другие шоки — недетерминизм"))
                unmapped_joint = [d for d in drv if d not in ((jspec.get("driver_generation") or {}).get("mappings") or {})]
                if unmapped_joint:
                    findings.append(_f("SCN-008", "phases", f"драйверы без root-mapping в Joint-схеме (идиосинкратические, без корреляции): {unmapped_joint}", "warning"))
            except ValueError as e:
                findings.append(_f("SCN-007", "phases", f"replay: {e}"))
        # coverage §9 по компаниям (калибровки из workspace)
        coverage = {}
        sdrv = sorted({d for ph in phases for d in (ph.get("driver_overrides") or {})})
        for folder, calname in (inputs.get("calibrations") or {}).items():
            cp = ws / "portfolio" / folder / calname
            if not cp.exists():
                coverage[folder] = {"error": f"нет файла {cp.name}"}; continue
            cal = _load(cp); active = set((cal.get("joint_simulation") or {}).get("active_drivers") or [])
            imm = set(((audit.get("decisions") or {}).get(cal.get("ticker") or folder.upper()) or {}).get("explicitly_immaterial") or [])
            excl = set(((audit.get("excluded_semantic_mismatch") or {}).get(cal.get("ticker") or folder.upper()) or []))
            coverage[folder] = {"ticker": cal.get("ticker"), "scenario_drivers_applicable": [d for d in sdrv if d in active and d not in excl],
                                "scenario_drivers_unmapped": [d for d in sdrv if d not in active and d not in imm],
                                "scenario_drivers_explicitly_immaterial": [d for d in sdrv if d in imm], "excluded_semantic_mismatch": sorted(excl & set(sdrv))}
        n_err += len(errs) + sum(1 for f in findings if f["severity"] == "error")
        per[sid] = {"schema_errors": errs, "integrity": findings, "replay": replay, "coverage": coverage,
                    "probability": sc.get("probability"), "probability_status": sc.get("probability_status"), "pass": not errs and not any(f["severity"] == "error" for f in findings)}
    # контракт вероятностей набора (§2)
    prob_findings = []
    if len(mx_sets) > 1:
        prob_findings.append(_f("SCN-009", "mutual_exclusion_set", f"сценарии из разных наборов: {sorted(str(x) for x in mx_sets)}"))
    pn = [sc.get("probability") for sc in scen if (sc.get("scenario_id") != "BASE")]
    if all(p is not None for p in pn) and pn:
        if any(float(p) < 0 for p in pn) or sum(float(p) for p in pn) > 1.0 + 1e-12:
            prob_findings.append(_f("SCN-010", "probability", f"Σ non-BASE = {sum(float(p) for p in pn):.4f} > 1 или отрицательная"))
        else:
            prob_findings.append(_f("SCN-010", "probability", f"p_BASE = {1.0 - sum(float(p) for p in pn):.4f} (остаток)", "info"))
    else:
        prob_findings.append(_f("SCN-010", "probability", "pending_owner_judgment: смесь/ScenarioConcentration/§3.3 not_testable", "info"))
    n_err += sum(1 for f in prob_findings if f["severity"] == "error")
    return {"model_version": VERSION, "mode": "scenario", "scenario_schema_version": SCENARIO_SCHEMA_VERSION, "taxonomy_version": tax_ver, "scenarios": per,
            "set_findings": prob_findings, "pass": n_err == 0, "rules": rules, "decision": "none"}


def run(inputs: dict, seed: int) -> dict:
    mode = inputs.get("mode", "workspace")'''),
])
p = ROOT / "engine/artifact_validator.py"; s = p.read_text(encoding="utf-8")
import re
m = re.search(r'VERSION = "(\d+)\.(\d+)\.(\d+)"', s); assert m
s = s.replace(m.group(0), 'VERSION = "1.7.0"', 1); p.write_text(s, encoding="utf-8", newline="\n"); print("validator version → 1.7.0 (было", m.group(0), ")")

# ------------------------------------------------------------------ тесты
t = ROOT / "tests/test_portfolio_paths.py"; u = t.read_text(encoding="utf-8")
i = u.index("def test_scenario_mixture_draft(tmp_path):"); u = u[:i] + '''def test_scenario_mixture_weighted(tmp_path):
    """Scenario Engine §2/§6/§7: BASE — остаток; pending-вероятность → только по-сценарные метрики; при вероятностях — взвешенная
    эмпирическая смесь (p=1 у BASE воспроизводит обычный прогон), impacts, ScenarioConcentration; детерминизм; контракт."""
    import pytest
    base_a = _run_store(_joint(cal_mature(), "AAA"), tmp_path); base_b = _run_store(_joint(cal_capital(), "BBB"), tmp_path)
    down = {"scenario_id": "DOWN", "driver_overrides": {"AI_COMPUTE_DEMAND": {"mean_shift_sigma": -2.0}}}
    mk = lambda tk, c, rid: cm.run({"calibration": c, "equity_value_0": 30e9, "joint_layer_spec": SPEC, "global_seed": 101, "paths": 6000, "convergence_check": False, "robustness": False, "store_paths": True, "_runs_dir": str(tmp_path), "_run_id": rid, "scenario": down}, 0)
    da = mk("AAA", _joint(cal_mature(), "AAA"), "t-AAA-DOWN"); db = mk("BBB", _joint(cal_capital(), "BBB"), "t-BBB-DOWN")
    files_b = {"AAA": base_a["paths_file"], "BBB": base_b["paths_file"]}; files_d = {"AAA": da["paths_file"], "BBB": db["paths_file"]}
    w = {"AAA": 0.5, "BBB": 0.4}
    pend = pp.run({"scenarios": [{"id": "BASE", "paths_files": files_b}, {"id": "DOWN", "probability": None, "paths_files": files_d}], "weights": w, "dry_powder_weight": 0.1, "dry_powder_return_annual": 0.04}, 0)
    assert pend["probability_status"] == "pending_owner_judgment" and pend["horizons"] is None and pend["scenario_concentration"] is None and pend["scenario_delta_vs_BASE"]["DOWN"]["Y5"]["median_CAGR"] < 0
    out = pp.run({"scenarios": [{"id": "BASE", "paths_files": files_b}, {"id": "DOWN", "probability": 0.3, "paths_files": files_d}], "weights": w, "dry_powder_weight": 0.1, "dry_powder_return_annual": 0.04}, 0)
    assert out["mode"] == "scenario_mixture" and out["scenarios"][0]["probability"] == 0.7 and out["decision"] == "none"
    b, d, m = out["by_scenario"]["BASE"]["Y5"], out["by_scenario"]["DOWN"]["Y5"], out["horizons"]["Y5"]
    assert d["median_CAGR"] < b["median_CAGR"] and min(b["median_CAGR"], d["median_CAGR"]) - 1e-9 <= m["median_CAGR"] <= max(b["median_CAGR"], d["median_CAGR"]) + 1e-9
    imp = out["scenario_impacts"]["DOWN"]; assert imp["probability"] == 0.3 and imp["MedianImpact_Y5"] < 0 and imp["adverse_ES_burden_B"] >= 0
    assert out["scenario_concentration"]["value"] in (0.0, 1.0)                                                # один non-BASE сценарий
    single = pp.run({"paths_files": files_b, "weights": w, "dry_powder_weight": 0.1, "dry_powder_return_annual": 0.04}, 0)
    only = pp.run({"scenarios": [{"id": "BASE", "paths_files": files_b}, {"id": "DOWN", "probability": 0.0, "paths_files": files_d}], "weights": w, "dry_powder_weight": 0.1, "dry_powder_return_annual": 0.04}, 0)
    assert abs(only["horizons"]["Y5"]["median_CAGR"] - single["horizons"]["Y5"]["median_CAGR"]) < 1e-9 and abs(only["horizons"]["Y5"]["expected_shortfall_5pct"] - single["horizons"]["Y5"]["expected_shortfall_5pct"]) < 1e-6
    assert pp.run({"scenarios": out and [{"id": "BASE", "paths_files": files_b}, {"id": "DOWN", "probability": 0.3, "paths_files": files_d}], "weights": w, "dry_powder_weight": 0.1, "dry_powder_return_annual": 0.04}, 0)["horizons"] == out["horizons"]
    with pytest.raises(ValueError):
        pp.run({"scenarios": [{"id": "BASE", "paths_files": files_b}, {"id": "DOWN", "probability": 1.2, "paths_files": files_d}], "weights": w, "dry_powder_weight": 0.1, "dry_powder_return_annual": 0.04}, 0)
    with pytest.raises(ValueError):
        pp.run({"scenarios": [{"id": "DOWN", "probability": 0.3, "paths_files": files_d}], "weights": w, "dry_powder_weight": 0.1, "dry_powder_return_annual": 0.04}, 0)
'''
t.write_text(u, encoding="utf-8", newline="\n"); print("test_portfolio_paths patched")

t = ROOT / "tests/test_artifact_validator.py"; u = t.read_text(encoding="utf-8")
u = u.rstrip("\n") + '''


def test_scenario_mode_on_normative_scenarios():
    """Режим scenario на живых калибровках IMMA v1.0 (workspace): схема, PSD, replay, coverage; сломанная матрица → error."""
    import copy, yaml
    from pathlib import Path
    ws = Path("C:/openclaw-lab/data/workspace-invest")
    if not (ws / "portfolio/_scenarios/CHIP_COLD_WAR_v1.0.yaml").exists():
        import pytest; pytest.skip("нет сценариев в workspace")
    sc = [yaml.safe_load(open(ws / f"portfolio/_scenarios/{f}", encoding="utf-8")) for f in ("TAIWAN_SEIZURE_v1.0.yaml", "CHIP_COLD_WAR_v1.0.yaml")]
    out = av.run({"mode": "scenario", "workspace": str(ws), "scenarios": sc, "replay_paths": 1000, "calibrations": {"nvda": "mc_calibration_v1.0.2.yaml", "hood": "mc_calibration_v1.0.1.yaml"}}, 0)
    assert out["mode"] == "scenario" and out["pass"] and set(out["scenarios"]) == {"TAIWAN_SEIZURE", "CHIP_COLD_WAR"}
    tw = out["scenarios"]["TAIWAN_SEIZURE"]; assert tw["replay"]["deterministic"] and set(tw["replay"]["phase_start_quantiles"]) == {"RESTRICTIONS", "BLOCKADE", "CONFLICT", "RECOVERY"}
    assert "TAIWAN_SUPPLY" in tw["coverage"]["nvda"]["scenario_drivers_applicable"] and "TAIWAN_SUPPLY" in tw["coverage"]["hood"]["scenario_drivers_unmapped"]
    assert any(f["rule"] == "SCN-010" and f["severity"] == "info" for f in out["set_findings"])                # вероятности pending
    bad = copy.deepcopy(sc[0]); bad["phases"][2]["root_correlation_overrides"] = [{"root_a": "AI_CAPEX_CYCLE", "root_b": "SEMI_SUPPLY_HEALTH", "correlation": 0.99, "meta": {"provenance": "model_assumption", "rationale": "t"}}, {"root_a": "AI_CAPEX_CYCLE", "root_b": "CHINA_MARKET_ACCESS", "correlation": 0.99, "meta": {"provenance": "model_assumption", "rationale": "t"}}, {"root_a": "SEMI_SUPPLY_HEALTH", "root_b": "CHINA_MARKET_ACCESS", "correlation": -0.99, "meta": {"provenance": "model_assumption", "rationale": "t"}}]
    out2 = av.run({"mode": "scenario", "workspace": str(ws), "scenario": bad, "replay_paths": 500}, 0)
    assert not out2["pass"] and any(f["rule"] == "SCN-006" and f["severity"] == "error" for f in out2["scenarios"]["TAIWAN_SEIZURE"]["integrity"])
'''
t.write_text(u, encoding="utf-8", newline="\n"); print("test_artifact_validator patched")
