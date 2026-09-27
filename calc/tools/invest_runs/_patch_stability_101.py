"""portfolio_stability 1.0.1: LOO на трёх стартах (given/equal/empty — одиночный тёплый старт из недопустимой точки застревал),
выбор семейств прогонов (stability.families) для частичного перепрогона, устойчивость статистики к пустой популяции."""
from pathlib import Path

p = Path("C:/openclaw-lab/calc/engine/portfolio_stability.py"); s = p.read_text(encoding="utf-8")


def rep(old, new, count=1):
    global s
    assert s.count(old) == count, (s.count(old), old[:80])
    s = s.replace(old, new)


rep('VERSION = "1.0.0"', 'VERSION = "1.0.1"')
rep('''- leave-one-company-out: позиции с центральным весом ≥ 5 % исключаются по одной (потолок 0), optimizer заново (§3.6);''',
    '''- leave-one-company-out: позиции с центральным весом ≥ 5 % исключаются по одной (потолок 0), optimizer заново на трёх стартах
  (given/equal/empty: одиночный тёплый старт из точки, нарушающей потолки после удаления бумаги, застревал — 1.0.1) (§3.6);''')
rep('''                       "loo_min_weight": 0.05, "inclusion_threshold": 0.01}}''',
    '''                       "loo_min_weight": 0.05, "inclusion_threshold": 0.01,
                       "families": null | ["return_shift","terminal","correlation","combined","loo"] (частичный перепрогон: partial=true)}}''')
rep('''            "combined_corr_delta": 0.10, "objective_sign_reference": "median_CAGR_5Y"}''',
    '''            "combined_corr_delta": 0.10, "objective_sign_reference": "median_CAGR_5Y"}
FAMILIES = ("return_shift", "terminal", "correlation", "combined", "loo")''')
rep('''    runs: list[dict] = []   # популяция §5–6
''', '''    fam = set(cfg.get("families") or FAMILIES)
    bad = fam - set(FAMILIES)
    if bad:
        raise ValueError(f"неизвестные семейства прогонов: {sorted(bad)}; допустимы {FAMILIES}")
    partial = fam != set(FAMILIES)
    runs: list[dict] = []   # популяция §5–6
''')
rep('''    # --- 3.1 сдвиги доходности
    ret_sens = {}
    for t in tick:''', '''    # --- 3.1 сдвиги доходности
    ret_sens = {}
    for t in (tick if "return_shift" in fam else []):''')
rep('''    # --- 3.4 терминальные допущения
    term_sens = {}
    for t in tick:''', '''    # --- 3.4 терминальные допущения
    term_sens = {}
    for t in (tick if "terminal" in fam else []):''')
rep('''    for delta in [0.0] + [s * d for d in cfg["corr_delta"] for s in (-1, 1)]:''',
    '''    for delta in ([0.0] + [s * d for d in cfg["corr_delta"] for s in (-1, 1)]) if "correlation" in fam else []:''')
rep('''    loo = {}
    for t in tick:
        if float(cw.get(t, 0.0)) < float(cfg["loo_min_weight"]):
            continue''', '''    loo = {}
    for t in (tick if "loo" in fam else []):
        if float(cw.get(t, 0.0)) < float(cfg["loo_min_weight"]):
            continue''')
rep('''        r = po.run({**inp2, "starts": ["given"], "start_weights": sw, "start_dry_powder": cdp}, 0, data=_copy(base, n))
        loo[t] = {"feasible": bool(r["feasible"]),''', '''        r = po.run({**inp2, "starts": ["given", "equal", "empty"], "start_weights": sw, "start_dry_powder": cdp}, 0, data=_copy(base, n))
        loo[t] = {"feasible": bool(r["feasible"]), "start_used": r["start_used"],''')
rep('''    N = int(cfg["combined_runs"]); k = len(tick)''', '''    N = int(cfg["combined_runs"]) if "combined" in fam else 0; k = len(tick)''')
# статистика: устойчивость к пустой популяции
rep('''    feas_rate = len(valid) / total if total else float("nan")''', '''    feas_rate = len(valid) / total if total else None''')
rep('''        f_incl = float(np.mean([w >= incl_thr for w in ws])) if ws else float("nan")
        p10, p50, p90 = _q(ws, 0.10), _q(ws, 0.50), _q(ws, 0.90)
        incl[t] = round(f_incl, 4); wstats[t] = {"p10": round(p10, 4), "p50": round(p50, 4), "p90": round(p90, 4)}; spread[t] = round(p90 - p10, 4)
        if c >= incl_thr:''', '''        if not ws:
            incl[t] = None; wstats[t] = None; spread[t] = None; cls[t] = {"class": "not_evaluated", "central_weight": c, "note": "популяция прогонов пуста (частичный прогон)"}
            continue
        f_incl = float(np.mean([w >= incl_thr for w in ws]))
        p10, p50, p90 = _q(ws, 0.10), _q(ws, 0.50), _q(ws, 0.90)
        incl[t] = round(f_incl, 4); wstats[t] = {"p10": round(p10, 4), "p50": round(p50, 4), "p90": round(p90, 4)}; spread[t] = round(p90 - p10, 4)
        if c >= incl_thr:''')
rep('''    flips = float(np.mean([np.sign(r["median_CAGR_5Y"]) != sign_c for r in valid])) if valid else float("nan")''',
    '''    flips = float(np.mean([np.sign(r["median_CAGR_5Y"]) != sign_c for r in valid])) if valid else None''')
rep('''    bind_freq = {b: round(v / total, 4) for b, v in sorted(bind_freq.items(), key=lambda x: -x[1])}
    criteria = {"hard_constraint_feasibility": {"value": round(feas_rate, 4), "limit": 0.95, "pass": bool(feas_rate >= 0.95)},
                "median_turnover_from_central": {"value": round(_q(turn, 0.5), 4), "limit": 0.25, "pass": bool(_q(turn, 0.5) <= 0.25)},
                "p90_turnover_from_central": {"value": round(_q(turn, 0.9), 4), "limit": 0.50, "pass": bool(_q(turn, 0.9) <= 0.50)},''',
    '''    bind_freq = {b: round(v / total, 4) for b, v in sorted(bind_freq.items(), key=lambda x: -x[1])}

    def crit(value, limit, ok):
        return {"value": (round(value, 4) if value is not None else None), "limit": limit, "pass": (bool(ok(value)) if value is not None else None)}

    t50 = _q(turn, 0.5) if turn else None; t90 = _q(turn, 0.9) if turn else None
    criteria = {"hard_constraint_feasibility": crit(feas_rate, 0.95, lambda v: v >= 0.95),
                "median_turnover_from_central": crit(t50, 0.25, lambda v: v <= 0.25),
                "p90_turnover_from_central": crit(t90, 0.50, lambda v: v <= 0.50),''')
rep('''                "median_5y_cagr_sign_flip_fraction": {"value": round(flips, 4), "limit": 0.20, "pass": bool(flips <= 0.20)}}
    evaluated = [c for c in criteria.values() if c["pass"] is not None]
    port_class = "structurally_stable" if all(c["pass"] for c in evaluated) else "not_structurally_stable"''',
    '''                "median_5y_cagr_sign_flip_fraction": crit(flips, 0.20, lambda v: v <= 0.20)}
    evaluated = [c for c in criteria.values() if c["pass"] is not None]
    port_class = ("structurally_stable" if all(c["pass"] for c in evaluated) else "not_structurally_stable") if evaluated else "not_evaluated"''')
rep('''            "central_weights": cw, "runs_total": total, "runs_by_family": fam_counts, "valid_runs": len(valid), "feasibility_rate": round(feas_rate, 4),''',
    '''            "central_weights": cw, "partial": partial, "families": sorted(fam), "runs_total": total, "runs_by_family": fam_counts, "valid_runs": len(valid),
            "feasibility_rate": (round(feas_rate, 4) if feas_rate is not None else None),''')
rep('''            "turnover_distribution": {"p10": round(_q(turn, 0.1), 4), "p50": round(_q(turn, 0.5), 4), "p90": round(_q(turn, 0.9), 4), "max": round(max(turn), 4) if turn else None},''',
    '''            "turnover_distribution": ({"p10": round(_q(turn, 0.1), 4), "p50": round(_q(turn, 0.5), 4), "p90": round(_q(turn, 0.9), 4), "max": round(max(turn), 4)} if turn else None),''')
p.write_text(s, encoding="utf-8", newline="\n")

# тест: частичный прогон только LOO + многостартовость
t = Path("C:/openclaw-lab/calc/tests/test_portfolio_stability.py"); u = t.read_text(encoding="utf-8")
u += '''

def test_partial_run_loo_only(paths):
    inp = _inputs(paths); inp["stability"] = {**inp["stability"], "families": ["loo"]}
    out = ps.run(inp, 11)
    assert out["partial"] is True and out["families"] == ["loo"] and out["runs_total"] == 0 and out["feasibility_rate"] is None
    assert out["portfolio_stability_classification"]["class"] == "not_evaluated" and out["turnover_distribution"] is None
    assert all(c["class"] == "not_evaluated" for c in out["company_stability_classification"].values())
    assert out["leave_one_out"] and all(r["start_used"] in ("given", "equal", "empty") for r in out["leave_one_out"].values())
    import pytest
    with pytest.raises(ValueError):
        ps.run({**inp, "stability": {**inp["stability"], "families": ["nope"]}}, 11)
'''
t.write_text(u, encoding="utf-8", newline="\n")
print("patched")
