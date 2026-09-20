"""Тесты каркаса движка: детерминизм по seed и форма выхода. Запуск с хоста: python -m pytest calc/tests -q"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

np = pytest.importorskip("numpy")
from engine import selftest  # noqa: E402


def test_deterministic_by_seed():
    a = selftest.run({"years": 3, "paths": 2000}, seed=7)
    b = selftest.run({"years": 3, "paths": 2000}, seed=7)
    c = selftest.run({"years": 3, "paths": 2000}, seed=8)
    assert a == b
    assert a != c


def test_output_shape_and_sanity():
    out = selftest.run({"years": 5, "mu": 0.15, "sigma": 0.35, "paths": 5000}, seed=42)
    for k in ("median_cagr", "p10_cagr", "p90_cagr", "p_2x", "p_5x", "p_loss", "downside_p5_multiple", "median_max_drawdown"):
        assert k in out
    assert out["p10_cagr"] <= out["median_cagr"] <= out["p90_cagr"]
    assert 0.0 <= out["p_2x"] <= 1.0 and 0.0 <= out["p_loss"] <= 1.0
    assert 0.0 <= out["median_max_drawdown"] <= 1.0
    assert 0.05 < out["median_cagr"] < 0.25
