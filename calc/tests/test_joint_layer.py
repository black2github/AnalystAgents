import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from engine import company_mc as cm, joint_layer as jl  # noqa: E402
from tests.test_company_mc import TRI, cal_mature  # noqa: E402

SPEC = {
    "root_factors": {"factors": {"GLOBAL_GROWTH": {"phi": 0.65}, "AI_CAPEX_CYCLE": {"phi": 0.75}, "FINANCIAL_CONDITIONS": {"phi": 0.6}}},
    "root_correlation": {"pair_overrides": {"GLOBAL_GROWTH__AI_CAPEX_CYCLE": 0.35, "GLOBAL_GROWTH__FINANCIAL_CONDITIONS": 0.35}},
    "driver_generation": {"mappings": {
        "AI_COMPUTE_DEMAND": {"roots": {"AI_CAPEX_CYCLE": 0.85, "GLOBAL_GROWTH": 0.20}, "idio_weight": 0.35},
        "HYPERSCALER_CAPEX": {"roots": {"AI_CAPEX_CYCLE": 0.80, "FINANCIAL_CONDITIONS": 0.15}, "idio_weight": 0.35},
        "INTEREST_RATES": {"roots": {"FINANCIAL_CONDITIONS": -0.90}, "idio_weight": 0.25}}},
}
MAPPING = [
    {"driver_id": "AI_COMPUTE_DEMAND", "material": True,
     "stochastic_targets": [{"path": "revenue_model.segments.New.initial_growth", "transform": "additive_pp", "effect_per_plus_1sigma": 0.10, "lag_quarters": 0, "decay_half_life_quarters": 4},
                            {"path": "margin_model.terminal_margin_Y5", "transform": "additive_pp", "effect_per_plus_1sigma": 0.015, "lag_quarters": 1, "decay_half_life_quarters": 6}],
     "structural_support": [{"path": "revenue_model.segments.New.initial_growth.mode", "contribution": 0.08}],
     "stability": {"knockout": {"mode": "remove_structural_support", "shifts": [{"path": "revenue_model.segments.New.initial_growth", "delta": -0.08}]},
                   "adverse_driver_stress": {"driver_sigma": -1.0}}},
    {"driver_id": "INTEREST_RATES", "material": True,
     "stochastic_targets": [{"path": "valuation.Y5.multiple", "transform": "multiplicative_pct", "effect_per_plus_1sigma": -0.10, "lag_quarters": 0, "decay_half_life_quarters": 8}],
     "structural_support": [], "stability": {"knockout": {"mode": "not_applicable"}, "adverse_driver_stress": {"driver_sigma": 1.0}}},
    {"driver_id": "HYPERSCALER_CAPEX", "material": False,
     "stochastic_targets": [{"path": "capacity_model.online_capacity_growth", "transform": "multiplicative_pct", "effect_per_plus_1sigma": 0.15, "lag_quarters": 1}],
     "structural_support": [], "stability": {"knockout": {"mode": "not_applicable"}, "adverse_driver_stress": {"driver_sigma": -1.0}}},
]


def _cal():
    c = cal_mature()
    c["joint_simulation"] = {"layer_version": "1.0", "active_drivers": ["AI_COMPUTE_DEMAND", "INTEREST_RATES", "HYPERSCALER_CAPEX"], "path_alignment": {"use_global_path_id": True}}
    c["driver_parameter_mapping"] = MAPPING
    return c


def test_root_paths_stationary_and_correlated():
    ids, F = jl.root_paths(SPEC, 20000, 32, 5)
    v = F.var(axis=(0, 2)); assert np.all(np.abs(v - 1) < 0.08)              # стационарная дисперсия ≈ 1
    r = np.corrcoef(F[:, 0, :].ravel(), F[:, 1, :].ravel())[0, 1]; assert abs(r - 0.35) < 0.05
    # AR(1): автокорреляция ≈ phi
    ac = np.mean([np.corrcoef(F[:, 1, t], F[:, 1, t + 1])[0, 1] for t in range(10)]); assert abs(ac - 0.75) < 0.05


def test_driver_shocks_unit_variance_same_path_for_all_companies():
    d1 = jl.driver_shocks(SPEC, ["AI_COMPUTE_DEMAND", "INTEREST_RATES", "UNMAPPED"], 20000, 32, 42)
    for k, x in d1.items():
        assert abs(x.var() - 1) < 0.08, k
    d2 = jl.driver_shocks(SPEC, ["AI_COMPUTE_DEMAND", "INTEREST_RATES", "UNMAPPED"], 20000, 32, 42)
    assert all(np.array_equal(d1[k], d2[k]) for k in d1)                   # тот же seed → тот же путь (для всех компаний)
    r = np.corrcoef(d1["AI_COMPUTE_DEMAND"].ravel(), d1["INTEREST_RATES"].ravel())[0, 1]
    assert r < 0                                                              # ставки ↑ при худших финансовых условиях, AI-спрос ↓ (через корреляцию корней)
    sc = jl.driver_shocks(SPEC, ["AI_COMPUTE_DEMAND"], 4000, 32, 1, scenario={"driver_overrides": {"AI_COMPUTE_DEMAND": {"mean_shift_sigma": -2.0}}})
    assert sc["AI_COMPUTE_DEMAND"].mean() < -1.5


def test_effective_shock_lag_and_decay():
    x = np.zeros((1, 8)); x[0, 2] = 1.0
    y = jl.effective_shock(x, lag_quarters=1, decay_half_life_quarters=None); assert y[0, 3] == 1.0 and y[0, 2] == 0.0
    z = jl.effective_shock(np.random.default_rng(0).standard_normal((5000, 64)), 0, 4); assert abs(z[:, 20:].var() - 1) < 0.1


def test_mapping_effects_scenario_knockout_and_adverse():
    base_inp = {"calibration": _cal(), "equity_value_0": 30e9, "joint_layer_spec": SPEC, "convergence_check": False, "robustness": False, "paths": 8000}
    base = cm.run(base_inp, 0)
    assert base["joint_simulation"]["active_drivers"] == ["AI_COMPUTE_DEMAND", "INTEREST_RATES", "HYPERSCALER_CAPEX"]
    assert any("capacity_model" in w for w in base["base"]["mapping_warnings"])   # неизвестная цель → not_testable, не ошибка
    # сценарий: AI-спрос −2σ → медианный рост выручки ниже
    down = cm.run({**base_inp, "scenario": {"id": "AI_BUST", "driver_overrides": {"AI_COMPUTE_DEMAND": {"mean_shift_sigma": -2.0}}}}, 0)
    assert down["base"]["gap_metrics"]["median_revenue_CAGR_5Y"] < base["base"]["gap_metrics"]["median_revenue_CAGR_5Y"] - 0.02
    # knockout снимает structural support (сдвиг моды на −8 п.п.), а не 1σ-чувствительность
    ko = cm.run({**base_inp, "knockout": ["AI_COMPUTE_DEMAND"]}, 0)
    assert ko["joint_simulation"]["knockout_applied"] and ko["base"]["gap_metrics"]["median_revenue_CAGR_5Y"] < base["base"]["gap_metrics"]["median_revenue_CAGR_5Y"]
    assert ko["base"]["gap_metrics"]["median_revenue_CAGR_5Y"] != down["base"]["gap_metrics"]["median_revenue_CAGR_5Y"]
    # adverse stress по ставкам (+1σ) → мультипликатор Y5 ниже → медианная стоимость Y5 ниже
    adv = cm.run({**base_inp, "adverse_driver_stress": ["INTEREST_RATES"]}, 0)
    assert adv["base"]["median_equity_value_5Y_b"] < base["base"]["median_equity_value_5Y_b"]
    # knockout для отрицательной экспозиции — not_applicable, ничего не меняет
    ko2 = cm.run({**base_inp, "knockout": ["INTEREST_RATES"]}, 0)
    assert ko2["joint_simulation"]["knockout_applied"] == ["INTEREST_RATES: knockout not_applicable"]
    assert ko2["base"]["return"]["median_CAGR_5Y"] == base["base"]["return"]["median_CAGR_5Y"]


def test_mapping_requires_layer_spec_and_is_deterministic():
    with pytest.raises(ValueError):
        cm.run({"calibration": _cal(), "equity_value_0": 30e9, "convergence_check": False, "robustness": False, "paths": 2000}, 0)
    inp = {"calibration": _cal(), "equity_value_0": 30e9, "joint_layer_spec": SPEC, "convergence_check": False, "robustness": False, "paths": 4000, "global_seed": 777}
    assert cm.run(inp, 0)["base"] == cm.run(inp, 0)["base"]


def _ph(pid, quarter=None, tri=None, anchor="t0", ramp=0, dur="until_end", decay=0, ov=None, corr=None):
    ef = {"kind": "fixed_quarter", "anchor": anchor, "quarter": quarter} if tri is None else {"kind": "triangular_quarter", "anchor": anchor, "min": tri[0], "mode": tri[1], "max": tri[2]}
    return {"phase_id": pid, "name": pid, "effective_from": ef, "ramp_quarters": ramp, "duration_quarters": dur, "decay_quarters": decay,
            "driver_overrides": {d: {"mean_shift_sigma": m, "volatility_multiplier": v, "persistence_override": None} for d, (m, v) in (ov or {}).items()},
            "root_correlation_overrides": corr or [], "meta": {"provenance": "model_assumption", "rationale": "test"}}


def test_scenario_phases_spec_semantics():
    """Scenario Engine v1.0: фаза = целевое состояние относительно BASE; ramp линейно (сдвиг) и геометрически (волатильность);
    целочисленная длительность возвращает к BASE через decay; until_next_phase — плато до следующей фазы; legacy — прежний путь."""
    n, T, d = 2000, 32, "AI_COMPUTE_DEMAND"
    # пример из Scenario_Engine_Examples: шок 4 кв. −1.0σ ×1.5 → восстановление с ramp 4 к −0.2σ ×1.1 до конца
    sc = {"scenario_id": "EX", "phases": [_ph("SHOCK", quarter=0, dur=4, ov={d: (-1.0, 1.5)}), _ph("RECOVERY", quarter=4, ramp=4, ov={d: (-0.2, 1.1)})]}
    sch = jl.scenario_schedule(SPEC, sc, [d], n, T, 1)
    mu, lv = sch["mu"][d][0], sch["logvol"][d][0]
    assert np.allclose(mu[:4], -1.0) and np.allclose(np.exp(lv[:4]), 1.5)
    assert np.allclose(mu[4:8], [-0.8, -0.6, -0.4, -0.2]) and np.allclose(mu[8:], -0.2)                       # линейный ramp от предыдущего состояния к целевому
    assert np.allclose(np.exp(lv[4:8]), 1.5 * (1.1 / 1.5) ** np.array([0.25, 0.5, 0.75, 1.0])) and np.allclose(np.exp(lv[8:]), 1.1)   # геометрически
    # целочисленная длительность + decay → возврат к BASE ступенями, потом 0
    sc2 = {"scenario_id": "D", "phases": [_ph("A", quarter=2, ramp=2, dur=3, decay=2, ov={d: (1.0, 1.0)})]}
    m2 = jl.scenario_schedule(SPEC, sc2, [d], n, T, 1)["mu"][d][0]
    assert np.allclose(m2[:2], 0) and np.allclose(m2[2:4], [0.5, 1.0]) and np.allclose(m2[4:7], 1.0) and np.allclose(m2[7:9], [0.5, 0.0]) and np.allclose(m2[9:], 0)
    # until_next_phase: плато до старта следующей; следующая фаза стартует от предыдущего состояния
    sc3 = {"scenario_id": "U", "phases": [_ph("A", quarter=0, dur="until_next_phase", ov={d: (1.0, 1.0)}), _ph("B", quarter=6, ramp=2, ov={d: (-1.0, 1.0)})]}
    m3 = jl.scenario_schedule(SPEC, sc3, [d], n, T, 1)["mu"][d][0]
    assert np.allclose(m3[:6], 1.0) and np.allclose(m3[6:8], [0.0, -1.0]) and np.allclose(m3[8:], -1.0)
    # применение к шокам: ScenarioDriver = mu + vol·Base; legacy-формат без фаз — прежний путь
    base = jl.driver_shocks(SPEC, [d], n, T, 1)[d]
    x = jl.driver_shocks(SPEC, [d], n, T, 1, scenario=sc)[d]
    assert np.allclose(x[:, :4], -1.0 + 1.5 * base[:, :4]) and np.allclose(x[:, 8:], -0.2 + 1.1 * base[:, 8:])
    legacy = jl.driver_shocks(SPEC, [d], n, T, 1, scenario={"driver_overrides": {d: {"mean_shift_sigma": -1.5, "volatility_multiplier": 1.2}}})[d]
    assert np.allclose(legacy, -1.5 + 1.2 * base)


def test_scenario_phase_timing_anchor_and_determinism():
    n, T, d = 4000, 32, "AI_COMPUTE_DEMAND"
    sc = {"scenario_id": "TIM", "phases": [_ph("A", tri=(4, 8, 12), ramp=1, dur="until_next_phase", ov={d: (1.0, 1.0)}), _ph("B", tri=(2, 3, 4), anchor="phase:A", ov={d: (-1.0, 1.0)})]}
    st = jl.phase_starts(sc, n, T, 7)
    assert st["A"].min() >= 4 and st["A"].max() <= 12 and (st["B"] - st["A"]).min() >= 2 and (st["B"] - st["A"]).max() <= 4 and st["A"].dtype.kind == "i"
    assert np.array_equal(st["A"], jl.phase_starts(sc, n, T, 7)["A"]) and not np.array_equal(st["A"], jl.phase_starts(sc, n, T, 8)["A"])   # детерминизм по seed
    x1 = jl.driver_shocks(SPEC, [d], n, T, 1, scenario=sc)[d]; x2 = jl.driver_shocks(SPEC, [d], n, T, 1, scenario=sc)[d]
    assert np.array_equal(x1, x2)
    diag = jl.scenario_diagnostics(SPEC, sc, [d, "INTEREST_RATES"], n, T, 1)
    assert diag["phased"] and set(diag["phase_start_quantiles"]) == {"A", "B"} and diag["scenario_drivers_applicable"] == [d] and diag["scenario_drivers_unmapped"] == []
    import pytest
    with pytest.raises(ValueError):
        jl.phase_starts({"scenario_id": "BAD", "phases": [_ph("B", tri=(1, 2, 3), anchor="phase:A")]}, n, T, 1)
    # persistence_override (вариант «б», предварительно): AR(1)-перепостоянство пути на плато; вне [0,0.99] → ValueError; null = базовый путь
    pers = {"scenario_id": "P", "phases": [_ph("A", quarter=4, ramp=2, ov={d: (0.0, 1.0)})]}; pers["phases"][0]["driver_overrides"][d]["persistence_override"] = 0.9
    sch = jl.scenario_schedule(SPEC, pers, [d], n, T, 1); r = sch["rho"][d][0]
    assert np.isnan(r[:4]).all() and np.isnan(r[4]) and r[5] == 0.9 and (r[6:] == 0.9).all()               # один конец null: до середины ramp старое (null), после — новое
    xb = jl.driver_shocks(SPEC, [d], n, T, 1)[d]; xp = jl.driver_shocks(SPEC, [d], n, T, 1, scenario=pers)[d]
    assert np.array_equal(xp[:, :5], xb[:, :5])
    ac_b = np.mean(xb[:, 10:] * xb[:, 9:-1]); ac_p = np.mean(xp[:, 10:] * xp[:, 9:-1])
    assert ac_p > ac_b + 0.2 and abs(np.var(xp[:, 20:]) - 1.0) < 0.15                                        # автокорреляция выросла, дисперсия ≈ 1 (инновационная семантика IMMA)
    diag = jl.persistence_diagnostics(SPEC, pers, [d], n, T, 1)
    k = f"A/{d}"; assert diag[k]["ok"] and abs(diag[k]["lag1_corr"] - 0.9) < 0.1 and abs(diag[k]["var_y"] - 1.0) < 0.15   # SCN-011: Var(y) ≈ 1, lag-1 ≈ ρ
    with pytest.raises(ValueError):
        bad = {"scenario_id": "P2", "phases": [_ph("A", quarter=0, ov={d: (0.0, 1.0)})]}; bad["phases"][0]["driver_overrides"][d]["persistence_override"] = 1.5
        jl.scenario_schedule(SPEC, bad, [d], n, T, 1)


def test_scenario_phase_correlation_overrides():
    """Переопределение корреляции корней в фазе: инновации корней коррелируют по целевой матрице на плато, по базовой — до старта;
    матрица не PSD → ValueError без ремонта; общие iid-инновации (до старта пути совпадают с BASE)."""
    n, T = 20000, 16
    roots = list(SPEC["root_factors"]["factors"].keys()); a, b = roots[0], roots[1]
    _, R0, _ = jl.root_correlation(SPEC); base_rho = R0[0, 1]
    target = 0.9 if base_rho < 0.5 else -0.5
    sc = {"scenario_id": "C", "phases": [_ph("A", quarter=8, ov={}, corr=[{"root_a": a, "root_b": b, "correlation": target}])]}
    sch = jl.scenario_schedule(SPEC, sc, ["AI_COMPUTE_DEMAND"], n, T, 3)
    assert sch["n_corr_states"] == 2 and (sch["corr_idx"][:, :8] == 0).all() and (sch["corr_idx"][:, 8:] == 1).all()
    ids, F = jl.root_paths(SPEC, n, T, 3, corr_schedule=(sch["corr_mats"], sch["corr_idx"]))
    ids0, F0 = jl.root_paths(SPEC, n, T, 3)
    assert np.array_equal(F[:, :, :8], F0[:, :, :8])                                                       # до старта — те же пути (общие инновации)
    phi = np.array([float(SPEC["root_factors"]["factors"][k].get("phi", 0.0)) for k in ids])
    u = (F[:, :, 12] - phi * F[:, :, 11]) / np.sqrt(1 - phi ** 2)                                          # восстановленные инновации на плато
    assert abs(np.corrcoef(u[:, 0], u[:, 1])[0, 1] - target) < 0.03
    import pytest
    with pytest.raises(ValueError):
        jl.phase_correlation(SPEC, _ph("X", quarter=0, corr=[{"root_a": a, "root_b": b, "correlation": 0.99}, {"root_a": a, "root_b": roots[2], "correlation": 0.99}, {"root_a": b, "root_b": roots[2], "correlation": -0.99}]))
