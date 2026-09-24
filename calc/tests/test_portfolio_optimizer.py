"""Тесты портфельного оптимизатора (стадия A): совместные пути трёх синтетических компаний, лексикографическая цель, жёсткие
ограничения без ослабления, полосы весов, разрывы к текущему портфелю, infeasible с минимальными ослаблениями."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from engine import portfolio_optimizer as po  # noqa: E402
from tests.test_company_mc import cal_mature, cal_capital, TRI  # noqa: E402
from tests.test_portfolio_paths import _joint, _run_store  # noqa: E402

LIMITS = {"sector_max": 0.60, "top3_aggregate_max": 0.95, "common_cause_effective_max": 0.60, "roles": {"Challenger_max_per_name": 0.08, "Challenger_aggregate_max": 0.25},
          "dry_powder": {"Normal": {"min": 0.05, "preferred_max": 0.10, "hard_max": 0.15}, "Stress": {"min": 0.05, "preferred_max": 0.15, "hard_max": 0.20}},
          "risk_5y": {"p_loss_gt_30_max": 0.20, "p_loss_gt_50_max": 0.10, "es5_min": -0.55}}


@pytest.fixture(scope="module")
def paths(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("opt")
    strong = cal_mature(); strong["revenue_model"]["segments"]["Core"]["initial_growth"] = TRI(0.20, 0.30, 0.40)
    weak = cal_mature(); weak["revenue_model"]["segments"]["Core"]["initial_growth"] = TRI(-0.10, 0.02, 0.10); weak["valuation"]["Y5"]["multiple"] = TRI(10, 14, 18)
    a = _run_store(_joint(strong, "AAA"), tmp, paths=4000); b = _run_store(_joint(weak, "BBB"), tmp, paths=4000); c = _run_store(_joint(cal_capital(), "CCC"), tmp, paths=4000)
    return {"AAA": a["paths_file"], "BBB": b["paths_file"], "CCC": c["paths_file"]}


def _inputs(paths, **over):
    d = {"paths_files": paths, "weights_current": {"AAA": 0.10, "BBB": 0.40, "CCC": 0.30}, "fixed_weights": {"ZZZ": 0.05}, "dry_powder_current": 0.10,
         "dry_powder_return_annual": 0.04, "regime": "Normal", "limits": LIMITS, "per_name_caps": {"AAA": 0.40, "BBB": 0.40, "CCC": 0.30},
         "sectors": {"AAA": "S1", "BBB": "S1", "CCC": "S2", "ZZZ": "S3"}, "common_cause": {"CAUSE": {"AAA": 1.0, "CCC": 0.75}}}
    d.update(over); return d


def test_optimizer_prefers_strong_and_respects_hard_constraints(paths):
    out = po.run(_inputs(paths), 0)
    w = out["proposed_weights"]; dp = out["dry_powder_weight"]
    assert out["feasible"] and out["violations_at_optimum"] == [] and out["decision"] == "none"
    assert abs(sum(w.values()) + dp + 0.05 - 1.0) < 1e-6                                   # бюджет: оптимизируемые + dp + fixed = 1
    assert w["AAA"] >= w["BBB"]                                                            # сильная компания не ниже слабой
    assert w["AAA"] <= 0.40 + 1e-9 and w["CCC"] <= 0.30 + 1e-9 and 0.05 - 1e-9 <= dp <= 0.15 + 1e-9
    assert out["concentrations"]["sector"]["S1"] <= 0.60 + 1e-9 and out["concentrations"]["common_cause"]["CAUSE"] <= 0.60 + 1e-9
    assert out["portfolio_return_distribution"]["Y5"]["median_CAGR"] >= out["current_portfolio"]["return_distribution_Y5"]["median_CAGR"] - 0.005
    assert set(out["feasible_weight_bands"]) == {"AAA", "BBB", "CCC"} and all(b[0] <= w[t] + 1e-9 <= b[1] + 1e-9 for t, b in out["feasible_weight_bands"].items())
    assert "AAA" in out["marginal_curves"] and out["marginal_curves"]["AAA"][0]["weight"] == 0.0
    assert out["fixed_positions"]["total"] == 0.05 and out["scenario_concentration"] is None
    # детерминизм
    again = po.run(_inputs(paths), 0)
    assert again["proposed_weights"] == w and again["dry_powder_weight"] == dp


def test_constraint_gaps_and_infeasible_reporting(paths):
    out = po.run(_inputs(paths, weights_current={"AAA": 0.55, "BBB": 0.25, "CCC": 0.05}), 0)
    gaps = {g["constraint"] for g in out["constraint_gaps_vs_current"]}
    assert "per_name_cap:AAA" in gaps and any(g.startswith("sector_max:S1") for g in gaps)      # текущий портфель нарушает, оптимум — нет
    assert out["feasible"] and all(not g["constraint"].startswith("per_name_cap") for g in out["violations_at_optimum"])
    bad = po.run(_inputs(paths, limits={**LIMITS, "risk_5y": {"p_loss_gt_30_max": 0.0, "p_loss_gt_50_max": 0.0, "es5_min": -0.05}}), 0)
    assert not bad["feasible"] and bad["minimum_relaxations"] and any(k.startswith("risk_5y") for k in bad["minimum_relaxations"])   # без тихого ослабления


def test_lexicographic_tolerance_and_watch_role(paths):
    out = po.run(_inputs(paths, roles={"CCC": "Watch"}), 0)
    assert out["proposed_weights"]["CCC"] == 0.0 and out["per_name_caps"]["CCC"] == 0.0
    P = po._Problem(_inputs(paths))
    a = {"horizons": {"Y5": {"median_CAGR": 0.100, "expected_shortfall_5pct": -0.30}}, "turnover": 0.1}
    b = {"horizons": {"Y5": {"median_CAGR": 0.103, "expected_shortfall_5pct": -0.40}}, "turnover": 0.1}
    assert P.better(a, b) and not P.better(b, a)                                            # в пределах 0.5 п.п. решает ES5
    c = {"horizons": {"Y5": {"median_CAGR": 0.110, "expected_shortfall_5pct": -0.40}}, "turnover": 0.1}
    assert P.better(c, a)                                                                   # вне допуска решает медиана
