"""artifact_validator 1.4.0: диагностика дисперсии intrinsic/full (Joint_Simulation_Layer_Rules_v1.1 → dispersion_plausibility)
и структурный отчёт σ по целям (aggregate_shift) в выводе режима calibration."""
from pathlib import Path

p = Path("C:/openclaw-lab/calc/engine/artifact_validator.py"); s = p.read_text(encoding="utf-8")
s = s.replace('VERSION = "1.3.1"\nSCHEMA_VERSION = "1.0.4"', 'VERSION = "1.4.0"\nSCHEMA_VERSION = "1.0.4"')

# --- σ по целям: возвращать структуру (integrity_calibration → (findings, aggregate_shift))
old = '                sd = float(tot[:, min(qn, tot.shape[1] - 1)].std())\n                kind = _target_kind(path); lim = float(limits.get(kind, limits.get("other", 0.15)))\n'
assert s.count(old) == 1
s = s.replace(old, old + '                agg[path] = {"sigma": round(sd, 4), "cap": lim, "kind": kind, "quarter": qn + 1, "drivers": len(items), "sum_abs_effect": round(sum(abs(e) for _, e, _, _ in items), 4), "ok": sd <= lim}\n')
old = 'def integrity_calibration(cal: dict, mpc: dict | None, joint_spec: dict | None, limits: dict, strict_aggregate: bool) -> list[dict]:\n    F: list[dict] = []\n'
assert s.count(old) == 1
s = s.replace(old, 'def integrity_calibration(cal: dict, mpc: dict | None, joint_spec: dict | None, limits: dict, strict_aggregate: bool, agg: dict | None = None) -> list[dict]:\n    """agg — необязательный словарь-накопитель σ суммарного сдвига по целям (заполняется для вывода aggregate_shift)."""\n    F: list[dict] = []\n    if agg is None:\n        agg = {}\n')

# --- диагностика дисперсии
helper = '''

def _dispersion_check(cal: dict, joint_spec: dict | None, rules: dict | None, paths: int) -> tuple[dict, list[dict]]:
    """intrinsic (mapping выключен) vs full: W = q95 − q5 CAGR equity 5Y, ориентиры по архетипу (диагностика, warning)."""
    import copy

    from engine import company_mc as cm

    F: list[dict] = []
    bands = ((rules or {}).get("dispersion_plausibility") or {}).get("reference_bands") or {}
    band = bands.get(cal.get("archetype")) or {}
    res = {}
    for label in ("intrinsic", "full"):
        d = copy.deepcopy(cal)
        if label == "intrinsic":
            d["driver_parameter_mapping"] = []
            d.setdefault("joint_simulation", {})["active_drivers"] = []
        inp = {"calibration": d, "equity_value_0": 1.0e9, "paths": paths, "convergence_check": False, "robustness": False}
        if joint_spec is not None:
            inp["joint_layer_spec"] = joint_spec
        b = cm.run(inp, 0)["base"]
        q = b["return"]["CAGR_5Y_quantiles"]
        res[label] = {"W": round(q["0.95"] - q["0.05"], 4), "q05": q["0.05"], "q95": q["0.95"], "median_CAGR_5Y": b["return"]["median_CAGR_5Y"],
                      "P_loss_gt_30pct_5Y": b["downside"]["P_loss_gt_30pct_5Y"], "P_2x_5Y": b["return"].get("P_2x_5Y")}
    ratio = res["full"]["W"] / res["intrinsic"]["W"] if res["intrinsic"]["W"] > 0 else None
    out = {"paths": paths, "intrinsic": res["intrinsic"], "full": res["full"], "full_to_intrinsic_ratio": round(ratio, 3) if ratio else None, "bands": band or None}
    if band:
        lo, hi = band.get("intrinsic_W", [None, None])
        if lo is not None and res["intrinsic"]["W"] < lo:
            F.append(_f("MC-DISP-001", "dispersion/intrinsic", f"intrinsic W = {res['intrinsic']['W']:.3f} ниже ориентира {lo}–{hi}: собственная неопределённость слишком узкая", "warning"))
        elif hi is not None and res["intrinsic"]["W"] > hi:
            F.append(_f("MC-DISP-001", "dispersion/intrinsic", f"intrinsic W = {res['intrinsic']['W']:.3f} выше ориентира {lo}–{hi}", "warning"))
        lo, hi = band.get("full_W", [None, None])
        if lo is not None and res["full"]["W"] < lo:
            F.append(_f("MC-DISP-002", "dispersion/full", f"full W = {res['full']['W']:.3f} ниже ориентира {lo}–{hi}", "warning"))
        elif hi is not None and res["full"]["W"] > hi:
            F.append(_f("MC-DISP-002", "dispersion/full", f"full W = {res['full']['W']:.3f} выше ориентира {lo}–{hi}: двойной счёт / невозможные хвосты", "warning"))
        rmax = band.get("full_to_intrinsic_width_ratio_max")
        if ratio is not None and rmax is not None and ratio > rmax:
            F.append(_f("MC-DISP-003", "dispersion/ratio", f"W_full/W_intrinsic = {ratio:.2f} > {rmax}: Joint Layer доминирует в дисперсии", "warning"))
    return out, F
'''
anchor = "\n\ndef _engine_dry_run(cal: dict, joint_spec: dict | None, paths: int) -> dict:"
assert s.count(anchor) == 1
s = s.replace(anchor, helper + anchor)

# --- ветка режима: aggregate_shift в выводе, диагностика дисперсии, правила из methodology
old = '        limits = dict(AGG_SHIFT_LIMITS); limits.update(inputs.get("aggregate_shift_limits") or {})\n        findings = integrity_calibration(cal, mpc, joint_spec, limits, bool(inputs.get("strict_aggregate", True)))\n        engine = None\n'
assert s.count(old) == 1
s = s.replace(old, '''        limits = dict(AGG_SHIFT_LIMITS); limits.update(inputs.get("aggregate_shift_limits") or {})
        rp = Path(inputs.get("joint_rules_path") or (ws / "methodology" / "Joint_Simulation_Layer_Rules_v1.1.yaml"))
        rules = yaml.safe_load(rp.read_text(encoding="utf-8")) if rp.exists() else None
        agg: dict = {}
        findings = integrity_calibration(cal, mpc, joint_spec, limits, bool(inputs.get("strict_aggregate", True)), agg)
        engine = None
        dispersion = None
''')
old = '''                if not engine.get("deterministic"):
                    findings.append(_f("MC-G5-DET", "simulation", "два прогона с одним seed дали разные результаты"))
            except Exception as e:  # noqa: BLE001
                findings.append(_f("MC-G5-ENGINE", "calibration", f"движок не принял калибровку: {type(e).__name__}: {str(e)[:200]}"))
'''
assert s.count(old) == 1
s = s.replace(old, old + '''            if inputs.get("dispersion_check", True) and not [f for f in findings if f["rule"] == "MC-G5-ENGINE"]:
                try:
                    dispersion, dF = _dispersion_check(cal, joint_spec, rules, int(inputs.get("dispersion_paths", 20000)))
                    findings.extend(dF)
                except Exception as e:  # noqa: BLE001
                    findings.append(_f("MC-DISP-000", "dispersion", f"диагностика дисперсии не выполнена: {type(e).__name__}: {str(e)[:160]}", "warning"))
''')
old = '"schema_errors": errs, "integrity": findings, "engine_dry_run": engine, "pass": not errs and n_err == 0,'
assert s.count(old) == 1
s = s.replace(old, '"schema_errors": errs, "integrity": findings, "engine_dry_run": engine, "aggregate_shift": agg, "dispersion": dispersion, "pass": not errs and n_err == 0,')
s = s.replace('        Schema; folders: ["<папка>"] для MC-G5-001 по mpc_inputs; правила MC-G5-001..013 кодом, MC-G5-013 — σ суммарного\n        сдвига цели на путях Joint Layer (по умолчанию warning; strict_aggregate: true → error); engine_dry_run: true —\n        company_mc на малом числе путей: mapping_warnings, детерминизм)',
              '        Schema; folders: ["<папка>"] для MC-G5-001 по mpc_inputs; правила MC-G5-001..013 кодом, MC-G5-013 — σ суммарного\n        сдвига цели на путях Joint Layer (hard gate; strict_aggregate: false → warning), выводится в aggregate_shift;\n        engine_dry_run: true — company_mc на малом числе путей: mapping_warnings, детерминизм; dispersion_check: true —\n        intrinsic/full W = q95−q5 CAGR 5Y против ориентиров Rules v1.1 (MC-DISP-001..003, warning), вывод dispersion)')
p.write_text(s, encoding="utf-8", newline="\n")

# --- тест
t = Path("C:/openclaw-lab/calc/tests/test_calibration_validator.py"); ts = t.read_text(encoding="utf-8")
ts += '''

@needs_ws
def test_dispersion_diagnostics_and_sigma_report():
    p = WS / "from_imma" / "MC_v1.1.1_reissue" / "SPCX_mc_calibration_v1.1.1.yaml"
    if not p.exists():
        pytest.skip("нет калибровки SPCX v1.1.1")
    cal = yaml.safe_load(p.read_text(encoding="utf-8"))
    out = av.run({"mode": "calibration", "workspace": str(WS), "calibration": cal, "folders": ["spacex"], "dry_run_paths": 1500, "dispersion_paths": 4000, "strict_aggregate": False}, 0)
    agg = out["aggregate_shift"]
    assert any("initial_growth" in k for k in agg) and all({"sigma", "cap", "kind", "quarter", "ok"} <= set(v) for v in agg.values())
    assert any(k.endswith(".Y3") and v["quarter"] == 12 for k, v in agg.items())          # узлы горизонтов — нативный квартал
    d = out["dispersion"]
    assert d and d["intrinsic"]["W"] > 0 and d["full"]["W"] > 0 and d["bands"]["intrinsic_W"] == [0.4, 0.85]
    assert any(f["rule"] == "MC-DISP-001" for f in out["integrity"])                          # SPCX intrinsic ниже ориентира
    off = av.run({"mode": "calibration", "workspace": str(WS), "calibration": cal, "folders": ["spacex"], "dry_run_paths": 1500, "dispersion_check": False, "strict_aggregate": False}, 0)
    assert off["dispersion"] is None
'''
t.write_text(ts, encoding="utf-8", newline="\n")
print("validator 1.4.0: dispersion + aggregate_shift; тест добавлен")
