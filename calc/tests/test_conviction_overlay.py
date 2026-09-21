import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from engine import conviction_overlay as co  # noqa: E402

PARAMS = {
    "L_max_standard": 0.10, "L_max_conviction": 0.25, "target_safety_buffer": 0.75,
    "plausible_drawdown_floor": 0.25, "plausible_drawdown_ceiling": 0.90,
    "standard_hard_cap_floor": 0.05, "standard_hard_cap_ceiling": 0.30, "conviction_hard_cap_floor": 0.05, "conviction_hard_cap_ceiling": 0.45,
    "invested_capital": {"standard_name_limit": 0.12, "conviction_name_limit": 0.20, "sector_limit": 0.30},
    "sector_market": {"soft_limit": 0.35, "hard_limit": 0.45},
    "archetype_fallback": {"mature_positive_margin": 0.55, "capital_intensive_transition": 0.75, "pre_service_or_milestone_driven": 0.85},
}


def _inp(conv_a=False):
    # NAV 1000 (кэш 100): A 400 (basis 150, капиталоёмкая 75%), B 300 (basis 200, зрелая 55%), C 200 (basis 250, без архетипа)
    return {"positions": [
        {"ticker": "A", "sector_id": "S1", "market_value": 400, "cost_basis": 150, "archetype": "capital_intensive_transition", "conviction": conv_a},
        {"ticker": "B", "sector_id": "S1", "market_value": 300, "cost_basis": 200, "archetype": "mature_positive_margin"},
        {"ticker": "C", "sector_id": "S2", "market_value": 200, "cost_basis": 250},
    ], "cash": 100, "params": PARAMS}


def test_caps_and_gaps_standard():
    out = co.run(_inp(), 0)
    a = out["assets"][0]
    assert out["risk_capital_basis"] == 700 and out["nav_base"] == 1000
    assert a["hard_cap"] == pytest.approx(0.10 / 0.75, abs=1e-4) and a["target_cap"] == pytest.approx(0.75 * 0.10 / 0.75, abs=1e-4)
    assert a["market_weight"] == 0.4 and a["concentration_gap"] == "hard_loss_budget_breach" and a["decision_request"] == "MANDATORY_RISK_REDUCTION_REVIEW"
    assert a["weight_to_restore_budget"] == pytest.approx(0.10 / 0.75, abs=1e-4)
    b = out["assets"][1]
    # B: hard 0.10/0.55 = 0.1818, target 0.1364; вес 0.30 → breach
    assert b["concentration_gap"] == "hard_loss_budget_breach"
    c = out["assets"][2]
    assert c["plausible_drawdown"] is None and c["concentration_gap"] == "not_applicable"


def test_conviction_relaxes_only_single_name_budget():
    out = co.run(_inp(conv_a=True), 0)
    a = out["assets"][0]
    assert a["conviction"] and a["L_max"] == 0.25
    assert a["hard_cap"] == pytest.approx(0.25 / 0.75, abs=1e-4)  # 0.3333 < 0.45 ceiling
    assert a["concentration_gap"] == "hard_loss_budget_breach"  # 0.40 > 0.3333
    # секторные пороги не ослабляются: сектор S1 = 70% по рынку → hard
    assert out["sectors"]["S1"]["market_gap"] == "hard" and out["sectors"]["S1"]["decision_request"] == "SECTOR_CONCENTRATION_REVIEW"


def test_invested_capital_limit_blocks_buys_without_forced_sale():
    out = co.run(_inp(), 0)
    c = out["assets"][2]  # basis 250/700 = 35.7% > 12% → gap, buys blocked, но продажи (decision_request) нет
    assert c["invested_share"] == pytest.approx(250 / 700, abs=1e-4) and c["invested_gap"] > 0 and c["block_new_buys"] and c["decision_request"] is None
    assert c["incremental_buy_capacity_usd"] == 0.0
    a = out["assets"][0]  # basis 150/700 = 21.4% > 12% → capacity 0
    assert a["incremental_buy_capacity_usd"] == 0.0


def test_ceiling_and_floor_clamp():
    p = dict(PARAMS); p["L_max_conviction"] = 0.45
    out = co.run({"positions": [{"ticker": "A", "market_value": 10, "cost_basis": 10, "archetype": "mature_positive_margin", "conviction": True}], "cash": 90, "params": p}, 0)
    assert out["assets"][0]["hard_cap"] == 0.45  # 0.45/0.55 = 0.818 → clamp 0.45


def test_rejects_bad_inputs():
    with pytest.raises(ValueError):
        co.run({"positions": [], "cash": 0, "params": PARAMS}, 0)
    with pytest.raises(ValueError):
        co.run({"positions": [{"ticker": "A", "market_value": -1, "cost_basis": 1}], "cash": 0, "params": PARAMS}, 0)
