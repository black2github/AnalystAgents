import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from engine import portfolio_regime as pr  # noqa: E402


def _inp(**kw):
    base = {
        "positions": [
            {"ticker": "A", "sector_id": "SEMICONDUCTORS", "quantity": 10, "price": 100, "price_12m_max": 125},   # dd -20%
            {"ticker": "B", "sector_id": "SOFTWARE", "quantity": 5, "price": 200, "price_12m_max": 200},          # dd 0
            {"ticker": "C", "sector_id": "SEMICONDUCTORS", "quantity": 20, "price": 50, "price_12m_max": 100},    # dd -50%
        ],
        "cash": [{"amount": 1000}],
        "nav_running_max": 4000.0,
        "sector_benchmarks": {"SEMICONDUCTORS": {"index": 4000, "index_12m_max": 5000}},  # -20%; SOFTWARE без benchmark
    }
    base.update(kw)
    return base


def test_nav_weights_and_drawdowns():
    out = pr.run(_inp(), seed=0)
    assert out["nav_base"] == 1000 + 1000 + 1000 + 1000
    assert out["drawdowns"]["portfolio"] == pytest.approx(0.0)
    assert out["drawdowns"]["sectors"]["SEMICONDUCTORS"] == pytest.approx(-0.2)
    assert out["drawdowns"]["sectors"]["SOFTWARE"] is None
    assert out["drawdowns"]["weighted_sector"] == pytest.approx(-0.2)
    assert out["drawdowns"]["benchmark_coverage"] == pytest.approx(2 / 3, abs=1e-3)
    assert out["positions"][2]["severity"] == "SHOCK" and out["positions"][0]["severity"] == "WATCH"


def test_regime_precedence_and_breadth():
    # широта: 1 из 3 позиций ≤ -40% → 33% ≥ 25% → Shock по breadth
    out = pr.run(_inp(), seed=0)
    assert out["regime"] == "Shock"
    # уберём просадку C → Normal
    out2 = pr.run(_inp(positions=[{"ticker": "A", "sector_id": "SEMICONDUCTORS", "quantity": 10, "price": 100, "price_12m_max": 110}],
                       nav_running_max=2000.0, sector_benchmarks={"SEMICONDUCTORS": {"index": 4800, "index_12m_max": 5000}}), seed=0)
    assert out2["regime"] == "Normal"
    # портфель -20% от максимума → Stress
    out3 = pr.run(_inp(positions=[{"ticker": "A", "sector_id": "SEMICONDUCTORS", "quantity": 10, "price": 100, "price_12m_max": 110}],
                       nav_running_max=2500.0, sector_benchmarks={"SEMICONDUCTORS": {"index": 4800, "index_12m_max": 5000}}), seed=0)
    assert out3["drawdowns"]["portfolio"] == pytest.approx(2000 / 2500 - 1)
    assert out3["regime"] == "Stress"


def test_limits_breaches():
    out = pr.run(_inp(limits={"single_name_max_weight": 0.2, "minimum_dry_powder_weight": 0.3}), seed=0)
    kinds = {b["limit"] for b in out["constraint_breaches"]}
    assert "single_name_max_weight" in kinds and "minimum_dry_powder_weight" in kinds


def test_rejects_bad_inputs():
    with pytest.raises(ValueError):
        pr.run({"positions": [{"ticker": "A", "quantity": -1, "price": 10}], "cash": []}, 0)
