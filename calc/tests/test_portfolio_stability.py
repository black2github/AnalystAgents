"""Тесты Portfolio Stability Test v1.0: три синтетические компании на совместных путях; однофакторный набор + LOO + малый combined;
инварианты возмущений (сдвиг доходности, множитель, прокси маржи, переспаривание Имана–Коновера), классификация, детерминизм."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402

from engine import portfolio_optimizer as po  # noqa: E402
from engine import portfolio_paths as pp  # noqa: E402
from engine import portfolio_stability as ps  # noqa: E402
from tests.test_portfolio_optimizer import LIMITS, paths  # noqa: E402,F401


def _inputs(paths, **over):
    d = {"paths_files": paths, "weights_current": {"AAA": 0.10, "BBB": 0.40, "CCC": 0.30}, "fixed_weights": {"ZZZ": 0.05}, "dry_powder_current": 0.10,
         "dry_powder_return_annual": 0.04, "regime": "Normal", "limits": LIMITS, "per_name_caps": {"AAA": 0.40, "BBB": 0.40, "CCC": 0.30},
         "sectors": {"AAA": "S1", "BBB": "S1", "CCC": "S2", "ZZZ": "S3"}, "common_cause": {"CAUSE": {"AAA": 1.0, "CCC": 0.75}},
         "stability": {"combined_runs": 6, "max_paths": 3000, "search_paths": 3000, "terminal_margins": {"AAA": 0.30, "BBB": 0.30, "CCC": None},
                       "milestone_companies": [], "driver_exposures": {"AAA": {"AI_COMPUTE_DEMAND": 2}, "BBB": {"AI_COMPUTE_DEMAND": 1}, "CCC": {"INTEREST_RATES": -1}},
                       "central_run_ref": "ref-run", "workers": 2}}
    d.update(over); return d


def test_perturbation_primitives(paths):
    base = {t: pp.load_paths(f) for t, f in paths.items()}; tick = sorted(base)
    d = ps._copy(base, 2000)
    ps._scale(d, "AAA", {"r5": 1.1, "r8": 1.1})
    assert np.allclose(d["AAA"]["r5"], base["AAA"]["r5"][:2000] * 1.1, rtol=1e-5) and np.array_equal(d["AAA"]["r3"], base["AAA"]["r3"][:2000])
    assert np.array_equal(d["BBB"]["r5"], base["BBB"]["r5"][:2000])                                     # другие компании не тронуты
    # переспаривание: маргиналы сохранены, ранговая корреляция сдвинута к цели, горизонты внутри компании переставлены одной перестановкой
    d = ps._copy(base, 2000)                                                                              # свежая копия (без масштаба)
    C0 = ps._rank_corr(d, tick)
    T = np.clip(C0 + 0.3 * (np.ones_like(C0) - np.eye(3)), -0.99, 0.99); np.fill_diagonal(T, 1.0); T, rep = ps._nearest_psd(T)
    d2 = ps._copy(base, 2000); ps._iman_conover(d2, tick, T, 5)
    for t in tick:
        assert np.array_equal(np.sort(d2[t]["r5"]), np.sort(d[t]["r5"]))
        i = np.argsort(d2[t]["r5"]); j = np.argsort(d[t]["r5"])
        assert np.allclose(d2[t]["r8"][i], d[t]["r8"][j])                                                 # r8 следует за r5 той же перестановкой
    C1 = ps._rank_corr(d2, tick)
    off = ~np.eye(3, dtype=bool)
    assert np.mean(C1[off] - C0[off]) > 0.2                                                               # сдвиг ≥ 2/3 запрошенного
    # PSD-ремонт: заведомо невалидная матрица чинится и помечается
    bad = np.array([[1.0, 0.95, -0.95], [0.95, 1.0, 0.95], [-0.95, 0.95, 1.0]])
    fixed, repaired = ps._nearest_psd(bad)
    assert repaired and np.linalg.eigvalsh(fixed).min() > 0 and np.allclose(np.diag(fixed), 1.0)


def test_stability_run_structure_and_classification(paths):
    out = ps.run(_inputs(paths), 11)
    tick = ["AAA", "BBB", "CCC"]
    assert out["decision"] == "none" and out["central_run_ref"] == "ref-run" and out["model_version"] == ps.VERSION
    cw = out["central_weights"]
    assert set(cw) == set(tick) and abs(sum(cw.values()) + out["central"]["dry_powder"] + 0.05 - 1.0) < 1e-6
    fam = out["runs_by_family"]
    assert fam["return_shift"] == 3 * 4 and fam["terminal_multiple"] == 3 * 2 and fam["terminal_margin"] == 2 * 2 and fam["correlation"] == 5 and fam["combined"] == 6
    assert out["runs_total"] == sum(fam.values()) and 0.0 <= out["feasibility_rate"] <= 1.0
    for t in tick:
        assert 0.0 <= out["inclusion_frequency_by_asset"][t] <= 1.0
        w = out["weight_p10_p50_p90"][t]; assert w["p10"] <= w["p50"] <= w["p90"] and abs(out["weight_spread"][t] - (w["p90"] - w["p10"])) < 1e-6
        assert out["company_stability_classification"][t]["class"] in ("stable", "conditional", "unstable", "excluded_at_central")
    assert out["terminal_sensitivity"]["CCC"]["margin"] == "not_testable" and isinstance(out["terminal_sensitivity"]["AAA"]["margin"]["+5pp"]["proxy_factor"], float)
    assert out["scenario_sensitivity"]["status"] == "not_applicable" and out["driver_sensitivity"]["status"].startswith("not_testable")
    assert [m["driver"] for m in out["driver_sensitivity"]["material_drivers"]] in (["AI_COMPUTE_DEMAND"], [])
    assert "zero_delta_control" in out["correlation_sensitivity"]["runs"] and "+0.10" in out["correlation_sensitivity"]["runs"]
    # LOO: только позиции ≥ 5 % центрального веса, исключённая бумага получает 0
    for t, r in out["leave_one_out"].items():
        assert cw[t] >= 0.05 and r["weights"][t] == 0.0
    assert all(t in out["leave_one_out"] for t in tick if cw[t] >= 0.05)
    crit = out["portfolio_stability_classification"]["criteria"]
    assert crit["driver_knockout_feasible_replacement"]["pass"] is None and "driver_knockout_feasible_replacement" in out["portfolio_stability_classification"]["criteria_not_evaluated"]
    assert out["portfolio_stability_classification"]["class"] in ("structurally_stable", "not_structurally_stable")
    assert out["mpc_robustness_mapping"] is None and len(out["assumptions_hash"]) == 64
    # сдвиг доходности вверх не уменьшает вес сдвинутой компании (монотонность на уровне однофакторного набора) — для сильной AAA
    rs = out["return_sensitivity"]["AAA"]
    assert rs["+5pp"]["weight"] >= rs["-5pp"]["weight"] - 1e-9
    # детерминизм
    again = ps.run(_inputs(paths), 11)
    assert again["assumptions_hash"] == out["assumptions_hash"] and again["inclusion_frequency_by_asset"] == out["inclusion_frequency_by_asset"] and again["combined"]["runs_detail"] == out["combined"]["runs_detail"]
    # последовательный режим (workers=1) даёт тот же результат, что пул из 2 процессов
    seq = ps.run(_inputs(paths, stability={**_inputs(paths)["stability"], "workers": 1}), 11)
    assert seq["workers"] == 1 and out["workers"] == 2
    assert seq["inclusion_frequency_by_asset"] == out["inclusion_frequency_by_asset"] and seq["weight_p10_p50_p90"] == out["weight_p10_p50_p90"]
    assert seq["combined"]["runs_detail"] == out["combined"]["runs_detail"] and seq["leave_one_out"] == out["leave_one_out"] and seq["correlation_sensitivity"] == out["correlation_sensitivity"]


def test_optimizer_given_start_and_max_paths(paths):
    inp = {"paths_files": paths, "weights_current": {"AAA": 0.10, "BBB": 0.40, "CCC": 0.30}, "fixed_weights": {"ZZZ": 0.05}, "dry_powder_current": 0.10,
           "dry_powder_return_annual": 0.04, "regime": "Normal", "limits": LIMITS, "per_name_caps": {"AAA": 0.40, "BBB": 0.40, "CCC": 0.30},
           "sectors": {"AAA": "S1", "BBB": "S1", "CCC": "S2", "ZZZ": "S3"}, "common_cause": {"CAUSE": {"AAA": 1.0, "CCC": 0.75}}, "max_paths": 2500}
    full = po.run({**inp, "starts": ["current"]}, 0)
    warm = po.run({**inp, "starts": ["given"], "start_weights": full["proposed_weights"], "start_dry_powder": full["dry_powder_weight"]}, 0)
    assert full["paths"] == 2500 and warm["start_used"] == "given" and warm["feasible"]
    assert warm["proposed_weights"] == full["proposed_weights"]                                            # тёплый старт из оптимума остаётся в нём
    data = {t: pp.load_paths(f) for t, f in paths.items()}
    inmem = po.run({**inp, "starts": ["current"]}, 0, data=data)
    assert inmem["proposed_weights"] == full["proposed_weights"]                                           # пути из памяти = пути из файлов


def test_partial_run_loo_only(paths):
    inp = _inputs(paths); inp["stability"] = {**inp["stability"], "families": ["loo"]}
    out = ps.run(inp, 11)
    assert out["partial"] is True and out["families"] == ["loo"] and out["runs_total"] == 0 and out["feasibility_rate"] is None
    assert out["portfolio_stability_classification"]["class"] == "not_evaluated" and out["turnover_distribution"] is None
    assert all(c["class"] == "not_evaluated" for c in out["company_stability_classification"].values())
    assert out["leave_one_out"] and all(r["start_used"] in ("given", "equal", "empty") for r in out["leave_one_out"].values())
    # линейная ёмкость: у центра запас ≥ 0 (центр допустим); у LOO structurally_infeasible=true → optimizer тоже недопустим
    cap = out["central"]["capacity"]; assert cap["headroom"] >= -1e-9 and not cap["structurally_infeasible"]
    for r in out["leave_one_out"].values():
        assert r["capacity"]["lp_max_placeable"] <= cap["lp_max_placeable"] + 1e-9
        if r["capacity"]["structurally_infeasible"]:
            assert not r["feasible"]
    tight = po.run({**{k: v for k, v in inp.items() if k != "stability"}, "starts": ["current"], "max_paths": 2500,
                    "per_name_caps": {"AAA": 0.20, "BBB": 0.20, "CCC": 0.20}, "limits": {**LIMITS, "dry_powder": {"Normal": {"min": 0.05, "preferred_max": 0.10, "hard_max": 0.15}}}}, 0)
    c2 = ps._capacity({**inp, "per_name_caps": {"AAA": 0.20, "BBB": 0.20, "CCC": 0.20}}, ["AAA", "BBB", "CCC"], None)
    assert c2["structurally_infeasible"] and not tight["feasible"]                                        # 0.60 < 0.95 − 0.15: ёмкости нет — и LP, и optimizer согласны
    import pytest
    with pytest.raises(ValueError):
        ps.run({**inp, "stability": {**inp["stability"], "families": ["nope"]}}, 11)


def test_resimulation_families(paths):
    """Срез 2: точная маржа, вехи и knockout через пересимуляцию (workers=1 — в процессе; синтетика на 3000 путях)."""
    from tests.test_company_mc import cal_mature, cal_capital
    from tests.test_portfolio_paths import _joint, SPEC
    cals = {"AAA": _joint(cal_mature(), "AAA"), "BBB": _joint(cal_mature(), "BBB"), "CCC": _joint(cal_capital(), "CCC")}
    cals["AAA"]["revenue_model"]["segments"]["Core"]["initial_growth"] = {"distribution": "triangular", "min": 0.20, "mode": 0.30, "max": 0.40}
    cals["BBB"]["revenue_model"]["segments"]["Core"]["initial_growth"] = {"distribution": "triangular", "min": -0.10, "mode": 0.02, "max": 0.10}; cals["BBB"]["valuation"]["Y5"]["multiple"] = {"distribution": "triangular", "min": 10, "mode": 14, "max": 18}
    inp = _inputs(paths)
    inp["stability"] = {**inp["stability"], "workers": 1, "max_paths": 4000, "search_paths": 4000, "families": ["terminal", "milestone", "driver_knockout"],
                        "resimulate": {"calibrations": cals, "equity_value_0": {"AAA": 30e9, "BBB": 30e9, "CCC": 30e9}, "joint_layer_spec": SPEC, "global_seed": 101, "chunk": 4000}}
    out = ps.run(inp, 11)
    assert out["resimulate"] is True and out["resimulate_check"]["reproduced"] and out["runs_by_family"]["terminal_margin"] == 6 and "terminal_multiple" in out["runs_by_family"]
    import pytest
    with pytest.raises(ValueError):                                                                                          # другой chunk → сторож выравнивания
        ps.run({**inp, "stability": {**inp["stability"], "resimulate": {**inp["stability"]["resimulate"], "chunk": 1000}}}, 11)
    m = out["terminal_sensitivity"]["AAA"]["margin"]
    assert m["+5pp"]["method"] == "resimulation" and m["+5pp"]["company_summary"]["median_CAGR_5Y"] > m["-5pp"]["company_summary"]["median_CAGR_5Y"]
    assert out["terminal_sensitivity"]["CCC"]["margin"]["+5pp"]["method"] == "resimulation"                                # B без прокси — теперь тестируется
    ds = out["driver_sensitivity"]; assert ds["status"] == "resimulated" and "AI_COMPUTE_DEMAND" in ds["runs"]
    ko = ds["runs"]["AI_COMPUTE_DEMAND"]; assert set(ko["companies"]) == {"AAA", "BBB"} and all(ko["knockout_applied"][t] for t in ("AAA", "BBB"))   # CCC без экспозиции — не трогаем
    crit = out["portfolio_stability_classification"]["criteria"]["driver_knockout_feasible_replacement"]; assert crit["pass"] in (True, False) and crit["value"] is not None
    assert out["runs_by_family"].get("milestone") is None                                                                    # milestone_companies пуст — вех нет
    assert all(fam in out["families"] for fam in ("terminal", "milestone", "driver_knockout")) and out["partial"] is True
