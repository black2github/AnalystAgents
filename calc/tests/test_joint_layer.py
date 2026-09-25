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


def test_scenario_phases_profile_and_legacy_equivalence():
    n, T = 4000, 32
    # legacy driver_overrides == одна фаза с t0 до конца
    legacy = jl.driver_shocks(SPEC, ["AI_COMPUTE_DEMAND"], n, T, 1, scenario={"driver_overrides": {"AI_COMPUTE_DEMAND": {"mean_shift_sigma": -1.5, "volatility_multiplier": 1.2}}})
    one = jl.driver_shocks(SPEC, ["AI_COMPUTE_DEMAND"], n, T, 1, scenario={"phases": [{"phase_id": "p", "effective_from": 0, "driver_overrides": {"AI_COMPUTE_DEMAND": {"mean_shift_sigma": -1.5, "volatility_multiplier": 1.2}}}]})
    assert np.allclose(legacy["AI_COMPUTE_DEMAND"], one["AI_COMPUTE_DEMAND"])
    # профиль: старт по распределению, подъём 4 кв., плато 8 кв., спад 4 кв.
    prof = jl.scenario_profiles({"phases": [{"phase_id": "a", "effective_from": {"distribution": "uniform", "min": 4, "max": 8}, "ramp_quarters": 4, "duration_quarters": 8, "decay_quarters": 4, "driver_overrides": {"X": {"mean_shift_sigma": 1}}},
                                            {"phase_id": "b", "after_phase": "a", "offset": 2, "driver_overrides": {"X": {"mean_shift_sigma": -1}}}]}, n, T, 7)
    a, b = prof[0], prof[1]
    assert a["m"].shape == (n, T) and a["m"].min() >= 0 and a["m"].max() <= 1
    assert (a["start"] >= 4).all() and (a["start"] <= 8).all()
    i = 0; st = a["start"][i]
    assert a["m"][i, int(np.floor(st))] <= 1e-9 or st == np.floor(st)                 # до старта — 0
    assert abs(a["m"][i, int(np.ceil(st)) + 5] - 1.0) < 1e-9                             # плато
    assert a["m"][i, min(T - 1, int(np.ceil(st)) + 4 + 8 + 4)] <= 1e-9 or int(np.ceil(st)) + 16 >= T   # после спада — 0
    assert (b["start"] >= a["start"] + 4 + 8 + 2 - 1e-9).all()                            # after_phase: старт после плато a + offset
    # сдвиг действует только после старта: средний шок до 4-го квартала ≈ 0, на плато ≈ +1
    sh = jl.driver_shocks(SPEC, ["AI_COMPUTE_DEMAND"], n, T, 1, scenario={"phases": [{"phase_id": "a", "effective_from": 8, "ramp_quarters": 0, "driver_overrides": {"AI_COMPUTE_DEMAND": {"mean_shift_sigma": 1.0}}}]})["AI_COMPUTE_DEMAND"]
    assert abs(sh[:, :8].mean()) < 0.1 and abs(sh[:, 8:].mean() - 1.0) < 0.1
    # детерминизм
    again = jl.driver_shocks(SPEC, ["AI_COMPUTE_DEMAND"], n, T, 1, scenario={"phases": [{"phase_id": "a", "effective_from": {"distribution": "triangular", "min": 2, "mode": 6, "max": 10}, "ramp_quarters": 2, "driver_overrides": {"AI_COMPUTE_DEMAND": {"mean_shift_sigma": -1.0}}}]})
    again2 = jl.driver_shocks(SPEC, ["AI_COMPUTE_DEMAND"], n, T, 1, scenario={"phases": [{"phase_id": "a", "effective_from": {"distribution": "triangular", "min": 2, "mode": 6, "max": 10}, "ramp_quarters": 2, "driver_overrides": {"AI_COMPUTE_DEMAND": {"mean_shift_sigma": -1.0}}}]})
    assert np.array_equal(again["AI_COMPUTE_DEMAND"], again2["AI_COMPUTE_DEMAND"])
