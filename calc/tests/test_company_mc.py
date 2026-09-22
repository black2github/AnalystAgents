import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from engine import company_mc as cm  # noqa: E402

SIM = {"paths": 6000, "seed": 11, "antithetic_variates": True, "store_summary_quantiles": [0.05, 0.5, 0.95]}
TRI = lambda lo, mo, hi: {"distribution": "triangular", "min": lo, "mode": mo, "max": hi}  # noqa: E731


def cal_mature(**over):
    c = {
        "ticker": "TEST-A", "archetype": "mature_positive_margin", "simulation": SIM,
        "revenue_model": {"segments": {"Core": {"base_revenue_quarterly": 1.0e9, "initial_growth": TRI(0.10, 0.20, 0.30), "long_run_growth_y8": TRI(0.04, 0.08, 0.12), "growth_half_life_years": 2.0},
                                       "New": {"base_revenue_quarterly": 0.2e9, "initial_growth": TRI(0.30, 0.50, 0.80), "long_run_growth_y8": TRI(0.05, 0.15, 0.25), "growth_half_life_years": 2.5}}},
        "margin_model": {"method": "mean_reverting_positive_margin", "current_margin": 0.10, "terminal_margin_Y5": TRI(0.22, 0.28, 0.34),
                         "terminal_margin_Y8": {"rule": "y5_plus_normal", "sigma": 0.02, "min": 0.10, "max": 0.45}, "half_life_years": 2.0,
                         "shock_sigma": 0.01, "shock_persistence": 0.5, "lower_bound": -0.2, "upper_bound": 0.6},
        "valuation": {"Y3": {"basis": "FCF_multiple", "multiple": TRI(20, 26, 32)}, "Y5": {"basis": "FCF_multiple", "multiple": TRI(18, 24, 30)},
                      "Y8": {"basis": "FCF_multiple", "multiple": TRI(15, 20, 25)}, "negative_fcf_fallback": {"basis": "revenue_bridge", "multiple": TRI(3, 5, 8)}},
        "dependencies": {"latent_factors": ["growth", "margin", "valuation"], "default_loading": 0.7,
                         "factor_correlations": {"growth__margin": 0.3, "growth__valuation": 0.1, "margin__valuation": 0.3}},
        "market_path_model": {"quarterly_log_price_noise": {"annualized_sigma": 0.4}, "valuation_mean_reversion_half_life_years": 2.0},
        "reverse_valuation_ref": {"implied_revenue_cagr_5y": 0.30, "discount_rate": 0.10},
        "robustness_tests": {"Scenario_Robustness": {"perturbations": {"growth_modes_pp": [-0.05, 0.05], "terminal_multiple_pct": [-0.2, 0.2]}, "delta_tolerance": 0.10}},
    }
    c.update(over); return c


def cal_capital():
    c = cal_mature(ticker="TEST-B", archetype="capital_intensive_transition")
    c["margin_model"] = {"method": "direct_fcf_nodes", "monotonic": True,
                         "nodes": {"Y1": TRI(-1.0, -0.7, -0.4), "Y2": TRI(-0.4, -0.15, 0.05), "Y3": TRI(0.0, 0.10, 0.18), "Y4_terminal_fraction": TRI(0.55, 0.7, 0.85),
                                   "Y5_terminal_margin": TRI(0.20, 0.27, 0.34), "Y8_terminal_margin": {"rule": "y5_plus_normal", "sigma": 0.03, "min": 0.15, "max": 0.40}}}
    c["valuation"]["Y3"] = {"basis": "revenue_bridge", "multiple": TRI(8, 14, 22)}
    return c


def test_dist_ppf_kinds():
    u = np.linspace(0.001, 0.999, 201)
    for d in (TRI(1, 2, 4), {"distribution": "pert", "min": 1, "mode": 2, "max": 4}, {"distribution": "truncated_normal", "mean": 2, "sd": 1, "min": 1, "max": 4}):
        x = cm.dist_ppf(u, d); assert x.min() >= 1 - 1e-9 and x.max() <= 4 + 1e-9 and np.all(np.diff(x) >= -1e-12)
    ln = cm.dist_ppf(np.array([0.5]), {"distribution": "lognormal", "median": 3.0, "sigma": 0.5}); assert ln[0] == pytest.approx(3.0)
    assert cm.dist_ppf(np.array([0.1, 0.9]), {"distribution": "deterministic", "value": 7}).tolist() == [7, 7]


def test_mature_margin_converges_to_terminal_and_outputs():
    inp = {"calibration": cal_mature(), "equity_value_0": 30e9, "convergence_check": False, "robustness": False}
    out = cm.run(inp, 0)
    b = out["base"]
    assert out["archetype"] == "mature_positive_margin" and out["margin_method"] == "mean_reverting_positive_margin"
    assert 0.20 < b["gap_metrics"]["median_fcf_margin_Y5"] < 0.36          # к Y5 маржа у терминальной (28% ± шок), не у 10%
    assert b["valuation_basis_share"]["Y5"]["multiple"] > 0.95 and b["return"]["bridge_dependent"]["Y5"] is False
    assert "RV_Growth_Gap" in b["gap_metrics"] and "Price_Expectation_Gap" in b["gap_metrics"]
    assert b["gap_metrics"]["RV_Growth_Gap"] == pytest.approx(0.30 - b["gap_metrics"]["median_revenue_CAGR_5Y"])
    assert 0 <= b["downside"]["P_loss_gt_30pct_5Y"] <= 1 and -1 <= b["downside"]["max_drawdown_5Y_quantiles"]["0.5"] <= 0


def test_capital_intensive_nodes_monotonic_and_bridge_dependent():
    out = cm.run({"calibration": cal_capital(), "equity_value_0": 30e9, "convergence_check": False, "robustness": False}, 0)
    b = out["base"]
    assert b["return"]["bridge_dependent"]["Y3"] is True and b["valuation_basis_share"]["Y3"]["revenue_bridge"] == 1.0
    assert b["return"]["bridge_dependent"]["Y5"] is False                  # Y5 маржа ≥ 0.55×Y5 > 0 → FCF multiple
    assert b["gap_metrics"]["median_fcf_margin_Y5"] > 0.15


def test_negative_fcf_uses_fallback_not_negative_multiple():
    c = cal_mature(); c["margin_model"]["terminal_margin_Y5"] = TRI(-0.30, -0.20, -0.10); c["margin_model"]["current_margin"] = -0.25
    c["margin_model"]["terminal_margin_Y8"] = TRI(-0.30, -0.20, -0.10)
    out = cm.run({"calibration": c, "equity_value_0": 30e9, "convergence_check": False, "robustness": False}, 0)
    b = out["base"]
    assert b["valuation_basis_share"]["Y5"]["negative_fcf_fallback"] > 0.99 and b["return"]["bridge_dependent"]["Y5"] is True
    assert b["median_equity_value_5Y_b"] > 0
    c["valuation"].pop("negative_fcf_fallback")
    with pytest.raises(ValueError):
        cm.run({"calibration": c, "equity_value_0": 30e9, "convergence_check": False, "robustness": False}, 0)


def test_deterministic_and_no_shared_rank():
    inp = {"calibration": cal_mature(), "equity_value_0": 30e9, "convergence_check": False, "robustness": False}
    assert cm.run(inp, 0)["base"] == cm.run(inp, 0)["base"]
    # загрузка 0 → фактор не влияет: корреляция начального и долгосрочного роста должна быть слабой (не тождественной, как при общем ранге)
    c = cal_mature(); c["dependencies"]["default_loading"] = 0.0
    rng = np.random.default_rng(1); F = rng.standard_normal((4000, 3)); d = cm._Draw(rng, 4000, F, 0.0)
    seg = c["revenue_model"]["segments"]["Core"]
    g0 = cm.dist_ppf(d.u("growth"), seg["initial_growth"]); g8 = cm.dist_ppf(d.u("growth"), seg["long_run_growth_y8"])
    assert abs(np.corrcoef(g0, g8)[0, 1]) < 0.1


def test_robustness_v1_1_and_spcx_adapter():
    out = cm.run({"calibration": cal_mature(), "equity_value_0": 30e9, "convergence_check": False, "robustness": True, "robustness_paths": 4000}, 0)
    r = out["robustness"]; assert len(r["runs"]) == 4 and "within_delta_tolerance_share" in r and r["pass"] in (True, False)
    spcx_v1 = {"ticker": "SPCX", "state_vector": {"AI": "A2"}, "simulation": SIM,
               "source_facts": {"q2_2026": {"AI_revenue_b": {"value": 2.561}, "Connectivity_revenue_b": {"value": 4.291}, "Space_revenue_b": {"value": 0.962}}},
               "revenue_model": {"segments": {
                   "AI": {"annual_growth_initial": TRI(0.35, 0.60, 0.90), "long_run_growth_y8": TRI(0.12, 0.25, 0.40), "mean_reversion_half_life_years": 2.5},
                   "Connectivity": {"annual_growth_initial": TRI(0.12, 0.25, 0.40), "long_run_growth_y8": TRI(0.06, 0.12, 0.20), "mean_reversion_half_life_years": 2.0},
                   "Space": {"annual_growth_initial": TRI(0.05, 0.18, 0.35), "long_run_growth_y8": TRI(0.05, 0.12, 0.25), "mean_reversion_half_life_years": 3.0}}},
               "margin_model": {"nodes": {"Y1": TRI(-1.10, -0.75, -0.45), "Y2": TRI(-0.35, -0.15, 0.05), "Y3": TRI(0.0, 0.10, 0.18), "Y4_terminal_fraction": TRI(0.55, 0.70, 0.85), "Y5_terminal_margin": TRI(0.20, 0.27, 0.34)}},
               "terminal_multiple": {"Y5": TRI(25, 32, 40), "Y8": TRI(20, 27, 35), "Y3": TRI(8, 14, 22)},
               "dependencies": {"rank_correlations": {"AI_growth__margin_improvement": {"rho": 0.45}, "terminal_margin__terminal_multiple": {"rho": 0.35}}}}
    out = cm.run({"calibration": spcx_v1, "equity_value_0": 2.013e12, "convergence_check": False, "robustness": False}, 0)
    assert out["adapted_from"] == "SPCX_Conditional_Monte_Carlo_Calibration_v1.0" and out["archetype"] == "capital_intensive_transition"
    assert out["base"]["return"]["median_CAGR_5Y"] < 0  # тот же качественный вывод, что у conditional_mc 1.0.1 (−14.9%)
