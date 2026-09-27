"""artifact_validator 1.3.0: режим calibration (Company MC Calibration Schema v1.0.1 + MC-G5-001..013 + сухой прогон движка)."""
from pathlib import Path

p = Path("C:/openclaw-lab/calc/engine/artifact_validator.py"); s = p.read_text(encoding="utf-8")

# --- версия и константы
old = 'VERSION = "1.2.0"\nSCHEMA_VERSION = "1.0.4"'
assert s.count(old) == 1
s = s.replace(old, 'VERSION = "1.3.0"\nSCHEMA_VERSION = "1.0.4"')
old = 'DOZOR_PROTOCOL_VERSION = "1.1"      # Dozor Verification Protocol (схема отчёта output_report_schema; отчёты v1.0 валидны)\n'
assert s.count(old) == 1
s = s.replace(old, old + 'CALIBRATION_SCHEMA_VERSION = "1.0.1"  # Company MC Calibration Schema (калибровки company_mc v2)\n'
              '# MC-G5-013 (предложение 23.09, до принятия IMMA — предупреждение): порог σ суммарного сдвига цели от всех драйверов на q20\n'
              'AGG_SHIFT_LIMITS = {"growth": 0.15, "margin": 0.05, "multiple": 0.15, "milestone": 0.75, "other": 0.15}\n')

# --- докстринг
old = '  mode: "workspace" (по умолчанию) | "candidate" | "dozor_report" (report: dict по output_report_schema протокола дозора;'
assert s.count(old) == 1
s = s.replace(old, '  mode: "workspace" (по умолчанию) | "candidate" | "dozor_report" | "calibration" (calibration: dict по Company MC Calibration\n'
              '        Schema; folders: ["<папка>"] для MC-G5-001 по mpc_inputs; правила MC-G5-001..013 кодом, MC-G5-013 — σ суммарного\n'
              '        сдвига цели на путях Joint Layer (по умолчанию warning; strict_aggregate: true → error); engine_dry_run: true —\n'
              '        company_mc на малом числе путей: mapping_warnings, детерминизм)\n'
              '        | "dozor_report" (report: dict по output_report_schema протокола дозора;')

# --- функции проверки калибровки
helpers = '''

# ----------------------------------------------------------------------------------------------- калибровки MC (MC-G5-*)
def _dists(o, path=""):
    """Все объекты-распределения калибровки: (путь, dict)."""
    if isinstance(o, dict):
        if "distribution" in o:
            yield path, o
        for k, v in o.items():
            yield from _dists(v, f"{path}.{k}" if path else str(k))
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from _dists(v, f"{path}[{i}]")


def _target_kind(path: str) -> str:
    if "initial_growth" in path or "growth" in path:
        return "growth"
    if "margin" in path or "_nodes" in path or path.startswith("margin_model"):
        return "margin"
    if "multiple" in path:
        return "multiple"
    if path.startswith("milestone_model"):
        return "milestone"
    return "other"


def integrity_calibration(cal: dict, mpc: dict | None, joint_spec: dict | None, limits: dict, strict_aggregate: bool) -> list[dict]:
    F: list[dict] = []
    maps = cal.get("driver_parameter_mapping") or []
    mapped = {m.get("driver_id") for m in maps}
    active = set((cal.get("joint_simulation") or {}).get("active_drivers") or [])
    # MC-G5-001: material-драйверы из mpc_inputs (|exposure| == 2 — error, ненулевые — warning)
    if mpc is not None:
        vec = mpc.get("driver_exposure_vector") or {}
        for d, e in vec.items():
            if e in (0, None) or d in mapped:
                continue
            F.append(_f("MC-G5-001", f"driver_parameter_mapping/{d}", f"драйвер {d!r} (exposure {e}) без mapping", "error" if abs(float(e)) >= 2 else "warning"))
    # MC-G5-002: mapping ⊆ active_drivers и наоборот
    for d in sorted(mapped - active):
        F.append(_f("MC-G5-002", f"joint_simulation/active_drivers", f"драйвер {d!r} есть в mapping, но не в active_drivers"))
    for d in sorted(active - mapped):
        F.append(_f("MC-G5-002", f"driver_parameter_mapping", f"драйвер {d!r} активен, но без mapping", "warning"))
    # MC-G5-005/006: вехи архетипа C
    mm = cal.get("milestone_model")
    if cal.get("archetype") == "pre_service_or_milestone_driven" and isinstance(mm, dict):
        ms = mm.get("milestones") or []
        ids = [m.get("id") for m in ms]
        if len(set(ids)) != len(ids):
            F.append(_f("MC-G5-005", "milestone_model/milestones", "дубликаты id вех"))
        req = {m.get("id"): list(m.get("requires") or []) for m in ms}
        for mid, rs in req.items():
            for r in rs:
                if r not in req:
                    F.append(_f("MC-G5-005", f"milestone_model/milestones/{mid}/requires", f"предпосылка {r!r} не существует"))
        if mm.get("service_onset_milestone") not in req:
            F.append(_f("MC-G5-005", "milestone_model/service_onset_milestone", f"{mm.get('service_onset_milestone')!r} не среди вех"))
        # ацикличность (DFS)
        state: dict = {}

        def visit(n, stack):
            if n in stack:
                return True
            if state.get(n) == 2:
                return False
            state[n] = 1
            for r in req.get(n, []):
                if r in req and visit(r, stack | {n}):
                    return True
            state[n] = 2
            return False

        if any(visit(n, set()) for n in req):
            F.append(_f("MC-G5-005", "milestone_model/milestones", "граф предпосылок содержит цикл"))
        up = sum(float(m.get("value_uplift") or 0) for m in ms)
        if up > 1.0 + 1e-9:
            F.append(_f("MC-G5-006", "milestone_model/milestones", f"Σ value_uplift = {up:.3f} > 1"))
    # MC-G5-007: упорядоченность распределений
    for path, d in _dists(cal):
        kind = (d.get("distribution") or "").lower()
        try:
            if kind in ("triangular", "pert") and not (float(d["min"]) <= float(d["mode"]) <= float(d["max"])):
                F.append(_f("MC-G5-007", path, f"{kind}: нарушено min ≤ mode ≤ max"))
            if kind == "truncated_normal":
                lo, hi = d.get("min"), d.get("max")
                if lo is not None and hi is not None and not (float(lo) < float(hi)):
                    F.append(_f("MC-G5-007", path, "truncated_normal: min < max нарушено"))
                if lo is not None and float(d["mean"]) < float(lo) or hi is not None and float(d["mean"]) > float(hi):
                    F.append(_f("MC-G5-007", path, "truncated_normal: mean вне [min, max]"))
            if kind == "lognormal" and float(d.get("sigma", 0)) <= 0:
                F.append(_f("MC-G5-007", path, "lognormal: sigma должна быть > 0"))
        except (KeyError, TypeError, ValueError) as e:
            F.append(_f("MC-G5-007", path, f"распределение не читается: {e}"))
    # MC-G5-008: границы маржи и PSD корреляций факторов
    mg = cal.get("margin_model") or {}
    if mg.get("lower_bound") is not None and mg.get("upper_bound") is not None and float(mg["lower_bound"]) > float(mg["upper_bound"]):
        F.append(_f("MC-G5-008", "margin_model", "lower_bound > upper_bound"))
    dep = cal.get("dependencies") or {}
    factors = list(dep.get("latent_factors") or [])
    corr = dep.get("factor_correlations") or {}
    if factors:
        import numpy as np
        names = [f if isinstance(f, str) else f.get("id") for f in factors]
        M = np.eye(len(names))
        for key, rho in corr.items():
            a, _, b = str(key).partition("__")
            if a in names and b in names:
                i, j = names.index(a), names.index(b)
                M[i, j] = M[j, i] = float(rho)
        mn = float(np.linalg.eigvalsh(M).min())
        if mn < -1e-9:
            F.append(_f("MC-G5-008", "dependencies/factor_correlations", f"матрица корреляций факторов не PSD (мин. собственное число {mn:.3f})"))
    # MC-G5-013: σ суммарного сдвига цели от всех драйверов на путях Joint Layer (q20)
    if maps and joint_spec is not None and active:
        try:
            import numpy as np
            from engine import joint_layer as jl

            drivers = sorted(active)
            shocks = jl.driver_shocks(joint_spec, drivers, 4000, 24, 7, True, None)
            per: dict = {}
            for m in maps:
                for t in m.get("stochastic_targets") or []:
                    per.setdefault(t["path"], []).append((m["driver_id"], float(t["effect_per_plus_1sigma"]), int(t.get("lag_quarters") or 0), float(t.get("decay_half_life_quarters") or 0)))
            for path, items in per.items():
                tot = None
                for d, e, lag, hl in items:
                    if d not in drivers:
                        continue
                    x = np.asarray(shocks[d] if isinstance(shocks, dict) else shocks[drivers.index(d)])
                    xe = jl.effective_shock(x, lag, hl) if hasattr(jl, "effective_shock") else x
                    tot = e * xe if tot is None else tot + e * xe
                if tot is None:
                    continue
                sd = float(tot[:, min(19, tot.shape[1] - 1)].std())
                kind = _target_kind(path); lim = float(limits.get(kind, limits.get("other", 0.15)))
                if sd > lim:
                    F.append(_f("MC-G5-013", f"driver_parameter_mapping → {path}", f"σ суммарного сдвига q20 = {sd:.3f} > {lim} ({kind}; драйверов {len(items)}, Σ|effect| {sum(abs(e) for _, e, _, _ in items):.2f})", "error" if strict_aggregate else "warning"))
        except Exception as e:  # noqa: BLE001 — диагностика не должна ронять валидацию
            F.append(_f("MC-G5-013", "driver_parameter_mapping", f"не удалось посчитать суммарный сдвиг: {type(e).__name__}: {str(e)[:120]}", "warning"))
    return F


def _engine_dry_run(cal: dict, joint_spec: dict | None, paths: int) -> dict:
    from engine import company_mc as cm

    inp = {"calibration": cal, "equity_value_0": 1.0e9, "paths": paths, "convergence_check": False, "robustness": False}
    if joint_spec is not None:
        inp["joint_layer_spec"] = joint_spec
    a = cm.run(dict(inp), 0); b = cm.run(dict(inp), 0)
    ba, bb = a["base"], b["base"]
    return {"engine_version": a.get("model_version"), "mapping_warnings": ba.get("mapping_warnings"), "deterministic": ba["return"]["median_CAGR_5Y"] == bb["return"]["median_CAGR_5Y"],
            "median_CAGR_5Y": ba["return"]["median_CAGR_5Y"], "P_loss_gt_30pct_5Y": ba["downside"]["P_loss_gt_30pct_5Y"], "paths": paths}
'''
anchor = "\n\n# ----------------------------------------------------------------------------------------------- прогон\n"
assert s.count(anchor) == 1
s = s.replace(anchor, helpers + anchor)

# --- ветка режима в run()
old = '    if mode == "dozor_report":\n        rep = inputs.get("report")'
assert s.count(old) == 1
branch = '''    if mode == "calibration":
        cal = inputs.get("calibration")
        if not isinstance(cal, dict):
            raise ValueError("mode=calibration требует inputs.calibration (dict)")
        schema = _schema(inputs, "calibration_schema_path", f"Company_MC_Calibration_Schema_v{CALIBRATION_SCHEMA_VERSION}.yaml")
        cal = _norm(cal)
        errs = _schema_errors(schema, cal)
        folders = inputs.get("folders") or []
        mpc = None
        if folders:
            mp = ws / "portfolio" / folders[0] / "mpc_inputs.yaml"
            mpc = _load(mp) if mp.exists() else None
        jp = Path(inputs.get("joint_layer_spec_path") or (ws / "methodology" / "Joint_Simulation_Layer_Schema_v1.0.yaml"))
        joint_spec = inputs.get("joint_layer_spec") or (yaml.safe_load(jp.read_text(encoding="utf-8")) if jp.exists() else None)
        limits = dict(AGG_SHIFT_LIMITS); limits.update(inputs.get("aggregate_shift_limits") or {})
        findings = integrity_calibration(cal, mpc, joint_spec, limits, bool(inputs.get("strict_aggregate", False)))
        engine = None
        if inputs.get("engine_dry_run", True) and not errs:
            try:
                engine = _engine_dry_run(cal, joint_spec, int(inputs.get("dry_run_paths", 2000)))
                for w in engine.get("mapping_warnings") or []:
                    findings.append(_f("MC-G5-003", "driver_parameter_mapping", f"движок: {w}"))
                if not engine.get("deterministic"):
                    findings.append(_f("MC-G5-DET", "simulation", "два прогона с одним seed дали разные результаты"))
            except Exception as e:  # noqa: BLE001
                findings.append(_f("MC-G5-ENGINE", "calibration", f"движок не принял калибровку: {type(e).__name__}: {str(e)[:200]}"))
        n_err = sum(1 for f in findings if f["severity"] == "error")
        return {"model_version": VERSION, "schema_version": CALIBRATION_SCHEMA_VERSION, "mode": mode, "ticker": cal.get("ticker"), "archetype": cal.get("archetype"),
                "schema_errors": errs, "integrity": findings, "engine_dry_run": engine, "pass": not errs and n_err == 0,
                "note": "MC-G5-013 (σ суммарного сдвига) — предложение 23.09, до принятия IMMA выдаётся как warning; MC-G5-009 (антицикличность) и MC-G5-010 (полнота provenance сверх схемы) статически не проверяются", "decision": "none"}
'''
s = s.replace(old, branch + old)
p.write_text(s, encoding="utf-8", newline="\n")
print("validator 1.3.0: режим calibration добавлен")
