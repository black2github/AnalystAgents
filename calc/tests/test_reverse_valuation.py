import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from engine import reverse_valuation as rv  # noqa: E402


def test_roundtrip_recovers_known_cagr():
    # строим капитализацию из известного g, затем решаем обратную задачу
    p = {"revenue_ttm_usd": 10e9, "current_fcf_margin": 0.10, "terminal_fcf_margin": 0.20,
         "terminal_multiple": 25, "discount_rate": 0.10, "forecast_years": 5, "net_debt_usd": 0}
    g_true = 0.18
    cap = rv._pv(g_true, p)
    out = rv.run({**p, "market_cap_usd": cap}, seed=0)
    assert out["implied_revenue_cagr"] == pytest.approx(g_true, abs=1e-4)
    assert out["pv_check_usd_b"] == pytest.approx(cap / 1e9, rel=1e-4)


def test_higher_price_requires_higher_cagr():
    p = {"revenue_ttm_usd": 10e9, "terminal_fcf_margin": 0.20, "terminal_multiple": 25}
    g1 = rv.run({**p, "market_cap_usd": 100e9}, 0)["implied_revenue_cagr"]
    g2 = rv.run({**p, "market_cap_usd": 200e9}, 0)["implied_revenue_cagr"]
    assert g2 > g1


def test_spcx_like_inputs_are_demanding():
    out = rv.run({"market_cap_usd": 2.013e12, "revenue_ttm_usd": 23.044e9, "current_fcf_margin": -0.5,
                  "terminal_fcf_margin": 0.20, "terminal_multiple": 30, "discount_rate": 0.10}, 0)
    assert out["implied_revenue_cagr"] > 0.35
    assert out["v_state"] in ("V4", "V5")


def test_unreachable_raises():
    with pytest.raises(ValueError):
        rv.run({"market_cap_usd": 1e15, "revenue_ttm_usd": 1e9, "terminal_fcf_margin": 0.2, "terminal_multiple": 20,
                "cagr_bounds": [-0.5, 1.0]}, 0)
