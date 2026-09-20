import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from engine import reverse_valuation as rv  # noqa: E402

BASE = {"market": {"price": 10.0, "shares_outstanding": 10e9}, "balance_sheet": {"net_debt": 0},
        "base_period": {"revenue_ttm": 10e9, "current_fcf_margin": 0.10},
        "discounting": {"discount_rate": 0.10, "stress_rates": [0.08, 0.12]},
        "terminal": {"fcf_margin_range": {"min": 0.15, "base": 0.20, "max": 0.25}, "multiple_range": {"min": 20, "base": 25, "max": 30}},
        "calculation": {"forecast_years": 5, "terminal_method": "equity_fcf_multiple"}}


def _with_cap(cap):
    d = {k: (dict(v) if isinstance(v, dict) else v) for k, v in BASE.items()}
    d["market"] = {"equity_value": cap}
    return d


def test_roundtrip_recovers_known_cagr_and_no_double_count():
    p = rv._norm(_with_cap(1.0))
    g_true = 0.18
    pv_i, pv_t, rev5, fcf5 = rv._pv_parts(g_true, 0.20, 25, 0.10, p)
    # год 5 не входит в промежуточные потоки (§6)
    n = 4
    rev0 = 10e9; s = 0.0
    for t in range(1, n + 1):
        rev = rev0 * (1 + g_true) ** t
        s += rev * (0.10 + (0.20 - 0.10) * t / 5) / 1.1 ** t
    assert pv_i == pytest.approx(s, rel=1e-9)
    assert pv_t == pytest.approx(fcf5 * 25 / 1.1 ** 5, rel=1e-9)
    out = rv.run(_with_cap(pv_i + pv_t), seed=0)
    assert out["calculated"]["implied_revenue_cagr_5y"] == pytest.approx(g_true, abs=1e-5)
    assert out["validation"]["converged"] is True
    assert out["calculated"]["control_cagr"] == pytest.approx(g_true, abs=1e-5)


def test_equity_method_ignores_net_debt_enterprise_subtracts_it():
    p_eq = rv._norm({**_with_cap(1.0), "balance_sheet": {"net_debt": 5e9}})
    p_ev = rv._norm({**_with_cap(1.0), "balance_sheet": {"net_debt": 5e9},
                     "calculation": {"forecast_years": 5, "terminal_method": "enterprise_fcf_multiple", "net_debt_5": 5e9}})
    _, pv_t_eq, _, _ = rv._pv_parts(0.15, 0.20, 25, 0.10, p_eq)
    _, pv_t_ev, _, _ = rv._pv_parts(0.15, 0.20, 25, 0.10, p_ev)
    assert pv_t_eq - pv_t_ev == pytest.approx(5e9 / 1.1 ** 5, rel=1e-9)


def test_sensitivity_grid_and_monotonicity():
    out = rv.run(_with_cap(300e9), seed=0)
    grid = out["sensitivity"]["margin_multiple_grid"]
    assert len(grid) == 9 and len(out["sensitivity"]["discount_rate_grid"]) == 2
    # выше маржа/мультипликатор → меньший требуемый CAGR
    assert grid["margin=0.25|multiple=30"] < grid["margin=0.15|multiple=20"]
    assert out["sensitivity"]["discount_rate_grid"]["r=0.12"] > out["sensitivity"]["discount_rate_grid"]["r=0.08"]


def test_transition_check_only_from_current_state():
    # умеренная капитализация → низкий CAGR → из V4 разрешён E-31 (V4→V3); из V2 переходов нет
    low = rv.run({**_with_cap(60e9), "current_valuation_state": "V4"}, seed=0)
    assert low["calculated"]["implied_revenue_cagr_5y"] <= 0.25
    assert low["valuation_state"]["transition_trigger"] == "SPCX-E-31" and low["valuation_state"]["candidate"] == "V3"
    none = rv.run({**_with_cap(60e9), "current_valuation_state": "V2"}, seed=0)
    assert none["valuation_state"]["transition_allowed"] is False


def test_no_solution_returns_status_not_value():
    out = rv.run({**_with_cap(1e18), "hard_limit": 2.0}, seed=0)
    assert out["validation"]["status"] == "no_solution_within_bounds"
    assert out["calculated"]["implied_revenue_cagr_5y"] is None


def test_flat_inputs_compat():
    out = rv.run({"market_cap_usd": 200e9, "revenue_ttm_usd": 10e9, "current_fcf_margin": 0.1,
                  "terminal_fcf_margin": 0.2, "terminal_multiple": 25, "discount_rate": 0.1}, seed=0)
    assert out["validation"]["converged"] is True
