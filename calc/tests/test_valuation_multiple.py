import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from engine import valuation_multiple as vm  # noqa: E402


def test_spcx_like_values_red():
    out = vm.run({"price": 152.71, "shares_outstanding": 13.55e9, "ttm_revenue_usd": 23.04e9}, seed=0)
    assert out["market_cap_usd_b"] == pytest.approx(2069.2, abs=1)
    assert out["ps_multiple"] == pytest.approx(89.8, abs=0.5)
    assert out["color"] == "red"


def test_colors_by_thresholds():
    assert vm.run({"price": 10, "shares_outstanding": 1e9, "ttm_revenue_usd": 1e9}, 0)["color"] == "green"   # 10x
    assert vm.run({"price": 40, "shares_outstanding": 1e9, "ttm_revenue_usd": 1e9}, 0)["color"] == "yellow"  # 40x
    assert vm.run({"price": 60, "shares_outstanding": 1e9, "ttm_revenue_usd": 1e9}, 0)["color"] == "red"     # 60x


def test_rejects_nonpositive():
    with pytest.raises(ValueError):
        vm.run({"price": 0, "shares_outstanding": 1, "ttm_revenue_usd": 1}, 0)
