import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from engine import synthetic_basket as sb  # noqa: E402


def _series(start_price, steps, dates):
    px, out = start_price, []
    for d, s in zip(dates, steps):
        px *= s
        out.append([d, round(px, 4)])
    return out


DATES = ["2026-03-30", "2026-03-31", "2026-04-01", "2026-04-02", "2026-04-03", "2026-04-06"]


def test_single_constituent_tracks_price():
    s = _series(100, [1.0, 1.1, 0.9, 1.05, 1.0, 0.8], DATES)
    out = sb.run({"constituents": [{"ticker": "A", "series": s}], "initial_level": 1000}, 0)
    assert out["index_last"] == pytest.approx(1000 * s[-1][1] / s[0][1])
    assert out["drawdown_12m"] == pytest.approx(s[-1][1] / max(p for _, p in s) - 1)
    assert out["benchmark_status"] == "ok"


def test_equal_weight_and_quarterly_chain_link():
    a = _series(100, [1.0, 1.0, 1.2, 1.0, 1.0, 1.0], DATES)   # A +20% на первый день Q2
    b = _series(50, [1.0, 1.0, 1.0, 1.0, 1.0, 0.5], DATES)    # B −50% в последний день
    out = sb.run({"constituents": [{"ticker": "A", "series": a}, {"ticker": "B", "series": b}]}, 0)
    # ребалансировка на 2026-04-01 (первый торговый день Q2): веса снова 50/50 по ценам этого дня
    assert "2026-04-01" in out["rebalances"]
    # индекс на 04-01 = 1000 * (0.5*1.2 + 0.5*1.0) = 1100; далее B падает на 50% при равных весах → 1100 * 0.75
    assert out["index_last"] == pytest.approx(1100 * 0.75)
    assert out["drawdown_12m"] == pytest.approx(0.75 - 1)


def test_missing_prices_carry_forward_and_degraded():
    a = _series(100, [1.0] * 6, DATES)
    b = [[DATES[0], 10.0], [DATES[1], 10.0], [DATES[5], 10.0]]  # 3 дня подряд без цены → degraded
    out = sb.run({"constituents": [{"ticker": "A", "series": a}, {"ticker": "B", "series": b}], "max_carry_forward_days": 1}, 0)
    assert out["benchmark_status"] == "degraded" and out["gaps"][0]["ticker"] == "B"
    assert out["index_last"] == pytest.approx(1000.0)


def test_rejects_bad_inputs():
    with pytest.raises(ValueError):
        sb.run({"constituents": []}, 0)
    with pytest.raises(ValueError):
        sb.run({"constituents": [{"ticker": "A", "series": [["2026-01-01", -1]]}]}, 0)
