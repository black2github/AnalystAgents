import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from engine import conditional_mc as mc  # noqa: E402

CAL = {
    "state_vector": {"AI": "A2", "Starlink": "B2", "Starship": "C1", "Capital_Intensity": "D3"},
    "source_facts": {"q2_2026": {"AI_revenue_b": {"value": 2.561}, "Connectivity_revenue_b": {"value": 4.291}, "Space_revenue_b": {"value": 0.962}}},
    "simulation": {"paths": 4000, "seed": 7, "antithetic_variates": True, "store_summary_quantiles": [0.05, 0.5, 0.95]},
    "revenue_model": {"segments": {
        "AI": {"annual_growth_initial": {"min": 0.35, "mode": 0.60, "max": 0.90}, "long_run_growth_y8": {"min": 0.12, "mode": 0.25, "max": 0.40}, "mean_reversion_half_life_years": 2.5},
        "Connectivity": {"annual_growth_initial": {"min": 0.12, "mode": 0.25, "max": 0.40}, "long_run_growth_y8": {"min": 0.06, "mode": 0.12, "max": 0.20}, "mean_reversion_half_life_years": 2.0},
        "Space": {"annual_growth_initial": {"min": 0.05, "mode": 0.18, "max": 0.35}, "long_run_growth_y8": {"min": 0.05, "mode": 0.12, "max": 0.25}, "mean_reversion_half_life_years": 3.0}}},
    "margin_model": {"nodes": {"Y1": {"min": -1.10, "mode": -0.75, "max": -0.45}, "Y2": {"min": -0.35, "mode": -0.15, "max": 0.05},
                               "Y3": {"min": 0.0, "mode": 0.10, "max": 0.18}, "Y4_terminal_fraction": {"min": 0.55, "mode": 0.70, "max": 0.85},
                               "Y5_terminal_margin": {"min": 0.20, "mode": 0.27, "max": 0.34}}},
    "terminal_multiple": {"Y5": {"min": 25, "mode": 32, "max": 40}, "Y8": {"min": 20, "mode": 27, "max": 35}, "Y3": {"min": 8, "mode": 14, "max": 22}},
    "dependencies": {"rank_correlations": {"AI_growth__Connectivity_growth": {"rho": 0.30}, "AI_growth__Space_growth": {"rho": 0.15},
                                           "AI_growth__margin_improvement": {"rho": 0.45}, "Connectivity_growth__margin_improvement": {"rho": 0.35},
                                           "Space_growth__margin_improvement": {"rho": 0.15}, "terminal_margin__terminal_multiple": {"rho": 0.35}}},
    "market_path_model": {"quarterly_log_price_noise": {"annualized_sigma": 0.55}, "valuation_mean_reversion_half_life_years": 2.0},
    "robustness_tests": {"Scenario_Robustness": {"perturbations": {"growth_modes_pp": [-0.10, 0.10], "terminal_multiple_pct": [-0.2, 0.2]}, "pass_rule": "знак"}},
}


def test_triangular_ppf_bounds_and_mode():
    u = np.linspace(0, 1, 101)
    x = mc._tri_ppf(u, 1, 2, 4)
    assert x.min() == pytest.approx(1) and x.max() == pytest.approx(4)
    assert np.all(np.diff(x) >= 0)


def test_growth_mean_reversion_converges_to_long_run():
    g = mc._growth_path(np.array([0.5]), CAL["revenue_model"]["segments"]["AI"], 0.0)
    assert g[0, 0] > g[0, -1]  # темп снижается к долгосрочному
    assert abs(g[0, -1] - mc._tri_ppf(np.array([0.5]), 0.12, 0.25, 0.40)[0]) < 0.06  # к Y8 близко к долгосрочному


def test_corr_matrix_psd_and_symmetric():
    C, fixed = mc._corr_matrix(CAL)
    assert np.allclose(C, C.T) and np.linalg.eigvalsh(C).min() > 0 and fixed is False


def test_deterministic_and_outputs():
    inp = {"calibration": CAL, "equity_value_0": 2.0e12, "paths": 4000, "convergence_check": False, "robustness": False}
    a = mc.run(inp, seed=0); b = mc.run(inp, seed=0)
    assert a["base"] == b["base"]
    r = a["base"]["return"]; d = a["base"]["downside"]
    assert 0 <= r["P_2x_5Y"] <= 1 and 0 <= d["P_loss_gt_30pct_5Y"] <= 1
    assert -1 <= d["max_drawdown_5Y_quantiles"]["0.5"] <= 0
    assert a["base"]["scenario"]["scenario_concentration"] is None


def test_higher_starting_value_lowers_returns():
    lo = mc.run({"calibration": CAL, "equity_value_0": 0.5e12, "paths": 4000, "convergence_check": False, "robustness": False}, 0)
    hi = mc.run({"calibration": CAL, "equity_value_0": 2.0e12, "paths": 4000, "convergence_check": False, "robustness": False}, 0)
    assert lo["base"]["return"]["median_CAGR_5Y"] > hi["base"]["return"]["median_CAGR_5Y"]
    assert lo["base"]["return"]["P_2x_5Y"] >= hi["base"]["return"]["P_2x_5Y"]


def test_robustness_and_convergence_blocks():
    out = mc.run({"calibration": CAL, "equity_value_0": 2.0e12, "paths": 4000, "robustness_paths": 2000}, 0)
    assert len(out["robustness"]["runs"]) == 4 and out["robustness"]["pass"] in (True, False)
    assert "convergence" in out and set(out["convergence"]["runs"].keys()) == {"4000"}
