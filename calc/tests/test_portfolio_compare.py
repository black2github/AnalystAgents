"""Тесты сравнения вариантов состава (portfolio_compare 1.0.0): картины по сценариям и смеси, вклады, концентрация, тема, оборот, проверка
лимитов через задачу оптимизатора, таблица разностей и ранжирование; pending-вероятности; ошибки входа."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from engine import portfolio_compare as pc  # noqa: E402
from tests.test_portfolio_optimizer import LIMITS, _shocked, paths  # noqa: E402,F401


def _scen(paths, tmp_path):
    s1 = {"AAA": _shocked(paths["AAA"], tmp_path / "c-s1-AAA.npz", {"f": 0.3}), "BBB": _shocked(paths["BBB"], tmp_path / "c-s1-BBB.npz", {"f": 1.0}), "CCC": _shocked(paths["CCC"], tmp_path / "c-s1-CCC.npz", {"f": 1.0})}
    return [{"id": "BASE", "paths_files": paths}, {"id": "S1", "probability": 0.2, "paths_files": s1}]


def test_compare_variants_scenarios_mixture_and_ranking(paths, tmp_path):
    scen = _scen(paths, tmp_path)
    variants = [{"id": "current", "weights": {"AAA": 0.10, "BBB": 0.40, "CCC": 0.30}, "dry_powder": 0.15},
                {"id": "alt", "weights": {"AAA": 0.35, "BBB": 0.10, "CCC": 0.30}, "dry_powder": 0.20, "note": "ручной вариант"}]
    out = pc.run({"variants": variants, "reference_id": "current", "scenarios": scen, "dry_powder_return_annual": 0.04, "fixed_weights": {"ZZZ": 0.05},
                  "theme": {"aggregate_id": "AI_TOTAL", "shares": {"AAA": 1.0, "CCC": 0.5}, "baseline_value": 0.30},
                  "limits_check": {"limits": LIMITS, "per_name_caps": {"AAA": 0.40, "BBB": 0.40, "CCC": 0.30}, "sectors": {"AAA": "S1", "BBB": "S1", "CCC": "S2", "ZZZ": "S3"}, "regime": "Normal"}}, 0)
    assert out["decision"] == "none" and out["probability_status"] == "owner_judgment" and out["limits_check"] == "applied"
    v = out["variants"]
    assert set(v) == {"current", "alt"} and v["alt"]["positions_count"] == 3 and v["current"]["turnover_vs_reference"] == 0.0
    assert set(v["alt"]["by_scenario_Y5"]) == {"BASE", "S1"} and v["alt"]["mixture"]["Y5"]["median_CAGR"] is not None
    # шок AAA ×0.3 под S1: вариант с бóльшим AAA хуже под S1, чем под BASE
    assert v["alt"]["by_scenario_Y5"]["S1"]["median_CAGR"] < v["alt"]["by_scenario_Y5"]["BASE"]["median_CAGR"]
    assert v["alt"]["scenario_impacts"]["S1"]["adverse_ES_burden_B"] >= 0 and v["alt"]["scenario_concentration"]["status"] == "not_applicable_single_adverse_scenario"
    # тема: AAA 1.0 + CCC 0.5
    assert v["alt"]["theme"]["value"] == pytest.approx(0.35 + 0.15, abs=1e-9) and v["alt"]["theme"]["within_policy"] is False
    assert v["current"]["theme"]["value"] == pytest.approx(0.10 + 0.15, abs=1e-9) and v["current"]["theme"]["within_policy"] is True
    # лимиты: dry powder 0.20 > hard_max 0.15 (Normal) у alt
    assert any(x["constraint"].startswith("dry_powder_hard_max") for x in v["alt"]["violations"]) and v["alt"]["feasible"] is False
    assert v["current"]["feasible"] is True
    cmp_ = out["comparison_vs_reference"]["alt"]
    assert cmp_["cash_pp"] == pytest.approx(5.0) and "mixture_Y5" in cmp_ and "S1" in cmp_["by_scenario_Y5"] and cmp_["theme_pp"] == pytest.approx(25.0)
    assert out["ranking"]["order"] == ["current"] and out["ranking"]["excluded_infeasible"] == ["alt"]


def test_compare_pending_probability_and_conditional(paths, tmp_path):
    scen = _scen(paths, tmp_path); scen[1]["probability"] = None
    cond = [{"scenario_id": "S1", "phase_id": "P1", "paths_files": scen[1]["paths_files"]}]
    out = pc.run({"variants": [{"id": "a", "weights": {"AAA": 0.5, "BBB": 0.2}, "dry_powder": 0.3}], "scenarios": scen, "conditional": cond}, 0)
    assert out["probability_status"] == "pending_owner_judgment" and out["pending"] == ["S1"]
    a = out["variants"]["a"]
    assert a["mixture"] is None and a["scenario_impacts"] is None and out["ranking"] is None
    assert a["conditional_phases_Y5"]["S1|P1"]["median_CAGR"] == pytest.approx(a["by_scenario_Y5"]["S1"]["median_CAGR"], abs=1e-12)
    with pytest.raises(ValueError):
        pc.run({"variants": [{"id": "a", "weights": {"AAA": 0.5}, "dry_powder": 0.3}], "scenarios": scen}, 0)          # сумма ≠ 1
    with pytest.raises(ValueError):
        pc.run({"variants": [{"id": "a", "weights": {"AAA": 0.7}, "dry_powder": 0.3}, {"id": "a", "weights": {"AAA": 0.7}, "dry_powder": 0.3}], "scenarios": scen}, 0)   # дубликат id


def test_universe_mode_optimizes_without_weights(paths, tmp_path):
    """1.1.0: вариант списком бумаг → веса через оптимизатор на смеси; оптимумы под сценариями; бумага вне вселенной (CCC) считается
    проданной в кэш; бумага без путей — ошибка; таблица «бумага × сценарий»."""
    from tests.test_portfolio_optimizer import _inputs
    scen = _scen(paths, tmp_path)
    tmpl = _inputs(paths, dry_powder_current=0.15, scenario_constraints={"p_min": 0.1, "es5_min": None, "p_loss_gt_30_max": None, "scenario_concentration_max": None,
                                                                           "scenarios": [{"id": "S1", "probability": 0.2, "paths_files": scen[1]["paths_files"]}], "base_paths_files": paths},
                   search={"random_starts": 0, "basin_kicks": 0}, search_paths=1000, max_paths=2000)
    out = pc.run({"variants": [{"id": "current", "weights": {"AAA": 0.10, "BBB": 0.40, "CCC": 0.30}, "dry_powder": 0.15},
                               {"id": "uni_ab", "universe": ["AAA", "BBB"], "note": "без CCC"}],
                  "reference_id": "current", "scenarios": scen, "fixed_weights": {"ZZZ": 0.05}, "optimizer_inputs": tmpl, "universe_options": {"per_scenario": True}}, 0)
    u = out["variants"]["uni_ab"]; opt = u["optimized"]
    assert out["universe_mode"]["variants"] == ["uni_ab"] and opt["universe"] == ["AAA", "BBB"] and opt["excluded_from_universe"] == {"CCC": 0.30}
    assert set(u["weights"]) <= {"AAA", "BBB"} and abs(sum(u["weights"].values()) + u["dry_powder"] + 0.05 - 1.0) < 1e-4
    assert opt["mixture"]["feasible"] is not None and "median_CAGR_5Y" in opt["mixture"] and opt["mixture"]["turnover_from_current"] is not None
    assert set(opt["by_scenario"]) == {"BASE", "S1"} and all("weights" in x for x in opt["by_scenario"].values())
    assert set(opt["weights_by_scenario"]) == {"AAA", "BBB"} and set(opt["weights_by_scenario"]["AAA"]) == {"mixture", "BASE", "S1"}
    assert opt["weights_by_scenario"]["AAA"]["S1"] <= opt["weights_by_scenario"]["AAA"]["BASE"] + 1e-9     # AAA ×0.3 под S1 → не больше, чем под BASE
    assert u["by_scenario_Y5"]["BASE"]["median_CAGR"] is not None and "uni_ab" in out["comparison_vs_reference"]
    with pytest.raises(ValueError, match="нет путей"):
        pc.run({"variants": [{"id": "x", "universe": ["AAA", "QQQ"]}], "scenarios": scen, "optimizer_inputs": tmpl}, 0)
    with pytest.raises(ValueError, match="optimizer_inputs"):
        pc.run({"variants": [{"id": "x", "universe": ["AAA"]}], "scenarios": scen}, 0)
