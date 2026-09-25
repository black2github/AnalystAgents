import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from engine import company_mc as cm  # noqa: E402
from tests.test_company_mc import TRI  # noqa: E402
from tests.test_joint_layer import SPEC  # noqa: E402

SIM = {"paths": 8000, "seed": 3, "antithetic_variates": True, "store_summary_quantiles": [0.05, 0.5, 0.95]}


def cal_c(**over):
    c = {
        "ticker": "TEST-C", "archetype": "pre_service_or_milestone_driven", "simulation": SIM,
        "milestone_model": {
            "service_onset_milestone": "SERVICE_ONSET",
            "reference_value": TRI(8e9, 12e9, 18e9), "residual_on_failure": 0.1,
            "milestones": [
                {"id": "DEPLOY", "probability": 0.90, "requires": [], "timing": TRI(6, 10, 14), "value_uplift": 0.3},
                {"id": "REG", "probability": 0.85, "requires": ["DEPLOY"], "timing": TRI(1, 2, 4), "value_uplift": 0.3},
                {"id": "SERVICE_ONSET", "probability": 0.90, "requires": ["REG"], "timing": TRI(1, 2, 3), "value_uplift": 0.4},
            ]},
        "revenue_model": {
            "existing_segments": {"Core": {"base_revenue_quarterly": 30e6, "initial_growth": TRI(0.1, 0.2, 0.3), "long_run_growth_y8": TRI(0.03, 0.06, 0.1), "growth_half_life_years": 2.0}},
            "service_segments": {"Service": {"initial_annual_revenue": TRI(300e6, 500e6, 800e6), "post_service_growth": TRI(0.6, 1.0, 1.5), "long_run_growth_y8": TRI(0.1, 0.2, 0.3), "growth_half_life_years": 1.5}}},
        "cash_model": {"net_cash_0": 3.0e9, "pre_service_burn_quarterly": TRI(250e6, 350e6, 450e6), "dilution_penalty": 0.2,
                       "core_margin": TRI(-0.2, 0.0, 0.1),
                       "service_margin": {"current_margin_at_onset": -0.5, "terminal_margin_Y5": TRI(0.25, 0.35, 0.45), "half_life_years": 1.5}},
        "valuation": {"fcf_maturity_margin": 0.10, "multiple_fcf": TRI(18, 25, 32), "multiple_revenue_bridge": TRI(5, 8, 12)},
        "dependencies": {"latent_factors": ["growth", "margin", "valuation"], "default_loading": 0.5, "factor_correlations": {"growth__margin": 0.2, "margin__valuation": 0.2}},
        "market_path_model": {"quarterly_log_price_noise": {"annualized_sigma": 0.6}, "valuation_mean_reversion_half_life_years": 2.0},
        "reverse_valuation_ref": {"discount_rate": 0.12},
    }
    c.update(over); return c


def _run(c, **kw):
    inp = {"calibration": c, "equity_value_0": 5e9, "convergence_check": False, "robustness": False}
    inp.update(kw); return cm.run(inp, 0)


def test_onset_probability_and_state_shares():
    out = _run(cal_c()); b = out["base"]
    assert out["archetype"] == "pre_service_or_milestone_driven"
    p_onset = b["service_onset"]["P_onset_within_8Y"]
    assert abs(p_onset - 0.9 * 0.85 * 0.9) < 0.03                       # цепочка вех воспроизводит произведение вероятностей
    assert 11 <= b["service_onset"]["median_onset_quarter"] <= 17        # 10 + 2 + 2 ≈ 14 кварталов
    s3, s8 = b["milestone_state_share"]["Y3"], b["milestone_state_share"]["Y8"]
    assert s3["pre_service"] > 0.2 and s8["service_started"] > 0.6 and abs(s8["terminal_failure"] - (1 - p_onset)) < 0.03
    vb = b["valuation_basis_share"]
    assert vb["Y3"]["milestone_conditioned_EV"] > 0.2 and vb["Y8"]["failure_residual"] > 0.2 and (vb["Y8"]["multiple"] + vb["Y8"]["revenue_bridge"]) > 0.5
    assert b["return"]["bridge_dependent"]["Y3"] is True
    assert "Price_Expectation_Gap" in b["gap_metrics"] and "RV_Growth_Gap" not in b["gap_metrics"]  # implied CAGR не задан


def test_failure_paths_worth_less_and_dilution_bites():
    out = _run(cal_c()); b = out["base"]
    assert b["downside"]["P_loss_gt_50pct_5Y"] > 0.1                     # отказы цепочки дают провалы стоимости
    # без резерва кэша и с большим сжиганием — размытие снижает медианную стоимость
    poor = cal_c(); poor["cash_model"]["net_cash_0"] = 0.2e9; poor["cash_model"]["pre_service_burn_quarterly"] = TRI(400e6, 500e6, 600e6)
    assert _run(poor)["base"]["median_equity_value_5Y_b"] < b["median_equity_value_5Y_b"]


def test_driver_mapping_on_milestones_and_service_growth():
    c = cal_c()
    c["joint_simulation"] = {"layer_version": "1.0", "active_drivers": ["AI_COMPUTE_DEMAND", "INTEREST_RATES"]}
    c["driver_parameter_mapping"] = [
        {"driver_id": "INTEREST_RATES", "material": True,
         "stochastic_targets": [{"path": "milestone_model.milestones.REG.probability", "transform": "probability_logit_shift", "effect_per_plus_1sigma": -0.6, "lag_quarters": 0},
                                {"path": "milestone_model.milestones.DEPLOY.timing", "transform": "timing_quarters_shift", "effect_per_plus_1sigma": 1.5, "lag_quarters": 0}],
         "structural_support": [], "stability": {"knockout": {"mode": "not_applicable"}, "adverse_driver_stress": {"driver_sigma": 1.0}}},
        {"driver_id": "AI_COMPUTE_DEMAND", "material": True,
         "stochastic_targets": [{"path": "revenue_model.service_segments.Service.post_service_growth", "transform": "additive_pp", "effect_per_plus_1sigma": 0.15, "lag_quarters": 0, "decay_half_life_quarters": 4}],
         "structural_support": [{"path": "revenue_model.service_segments.Service.post_service_growth.mode", "contribution": 0.2}],
         "stability": {"knockout": {"mode": "remove_structural_support", "shifts": [{"path": "revenue_model.service_segments.Service.post_service_growth", "delta": -0.2}]}, "adverse_driver_stress": {"driver_sigma": -1.0}}},
    ]
    base = _run(c, joint_layer_spec=SPEC); b = base["base"]
    assert b["mapping_warnings"] == []
    adv = _run(c, joint_layer_spec=SPEC, adverse_driver_stress=["INTEREST_RATES"])["base"]     # ставки +1σ → вероятность REG ниже, DEPLOY позже
    assert adv["service_onset"]["P_onset_within_8Y"] < b["service_onset"]["P_onset_within_8Y"] - 0.05
    assert adv["service_onset"]["median_onset_quarter"] > b["service_onset"]["median_onset_quarter"]
    ko = _run(c, joint_layer_spec=SPEC, knockout=["AI_COMPUTE_DEMAND"])["base"]                 # снятие опоры роста сервиса → стоимость Y8 ниже
    assert np.median([ko["return"]["median_CAGR_8Y"]]) < b["return"]["median_CAGR_8Y"]


def test_c_validation_and_determinism():
    bad = cal_c(); bad.pop("cash_model")
    with pytest.raises(ValueError):
        _run(bad)
    cyc = cal_c(); cyc["milestone_model"]["milestones"][0]["requires"] = ["SERVICE_ONSET"]
    with pytest.raises(ValueError):
        _run(cyc)
    assert _run(cal_c())["base"] == _run(cal_c())["base"]


def test_milestone_probability_shift_changes_onset():
    from engine import company_mc as cm
    c = cal_c()
    base = cm.simulate_paths({"calibration": c, "equity_value_0": 5e9, "paths": 6000}, 0)
    up = cm.simulate_paths({"calibration": c, "equity_value_0": 5e9, "paths": 6000, "perturbation": {"milestone_prob_shift": 0.10}}, 0)
    down = cm.simulate_paths({"calibration": c, "equity_value_0": 5e9, "paths": 6000, "perturbation": {"milestone_prob_shift": -0.10}}, 0)
    assert up["summary"]["median_CAGR_5Y"] >= base["summary"]["median_CAGR_5Y"] >= down["summary"]["median_CAGR_5Y"]
    assert up["summary"]["P_loss_gt_30pct_5Y"] <= down["summary"]["P_loss_gt_30pct_5Y"]
