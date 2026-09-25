import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from engine import company_mc as cm, portfolio_paths as pp  # noqa: E402
from tests.test_company_mc import cal_mature, cal_capital  # noqa: E402
from tests.test_joint_layer import SPEC, MAPPING  # noqa: E402


def _joint(c, ticker):
    c = dict(c); c["ticker"] = ticker
    c["joint_simulation"] = {"layer_version": "1.0", "active_drivers": ["AI_COMPUTE_DEMAND", "INTEREST_RATES"]}
    c["driver_parameter_mapping"] = [m for m in MAPPING if m["driver_id"] in ("AI_COMPUTE_DEMAND", "INTEREST_RATES")]
    return c


def _run_store(c, tmp, global_seed=101, paths=6000):
    inp = {"calibration": c, "equity_value_0": 30e9, "joint_layer_spec": SPEC, "global_seed": global_seed, "paths": paths,
           "convergence_check": False, "robustness": False, "store_paths": True, "_runs_dir": str(tmp), "_run_id": f"t-{c['ticker']}-{global_seed}"}
    return cm.run(inp, 0)


def test_paths_file_written_and_aligned(tmp_path):
    a = _run_store(_joint(cal_mature(), "AAA"), tmp_path); b = _run_store(_joint(cal_capital(), "BBB"), tmp_path)
    assert a["paths_file"].endswith("t-AAA-101-paths.npz") and Path(a["paths_file"]).exists()
    da, db = pp.load_paths(a["paths_file"]), pp.load_paths(b["paths_file"])
    assert da["meta"]["joint"] is True and da["meta"]["global_seed"] == db["meta"]["global_seed"] == 101
    assert np.array_equal(da["path_id"], db["path_id"]) and len(da["r5"]) == 6000
    # относительные стоимости соответствуют сводке
    assert float(np.median(np.power(da["r5"].astype(float), 0.2) - 1)) == pytest.approx(a["base"]["return"]["median_CAGR_5Y"], abs=1e-3)
    # портфель 100% AAA воспроизводит статистику AAA; смесь снижает дисперсию
    solo = pp.run({"paths_files": {"AAA": a["paths_file"]}, "weights": {"AAA": 1.0}}, 0)
    assert solo["horizons"]["Y5"]["median_CAGR"] == pytest.approx(a["base"]["return"]["median_CAGR_5Y"], abs=1e-3)
    mix = pp.run({"paths_files": {"AAA": a["paths_file"], "BBB": b["paths_file"]}, "weights": {"AAA": 0.5, "BBB": 0.4}, "dry_powder_weight": 0.1, "dry_powder_return_annual": 0.04}, 0)
    assert mix["alignment"]["aligned"] and mix["alignment"]["joint_layer_all"]
    q = mix["horizons"]["Y5"]["CAGR_quantiles"]; qa = solo["horizons"]["Y5"]["CAGR_quantiles"]
    assert (q["0.95"] - q["0.05"]) < (qa["0.95"] - qa["0.05"])
    assert "AAA__BBB" in mix["log_value_correlation_Y5"] and mix["median_contribution_Y5"]["dry_powder"] == pytest.approx(0.1 * 1.04 ** 5)


def test_unaligned_paths_rejected(tmp_path):
    a = _run_store(_joint(cal_mature(), "AAA"), tmp_path, global_seed=101); b = _run_store(_joint(cal_capital(), "BBB"), tmp_path, global_seed=202)
    with pytest.raises(ValueError):
        pp.run({"paths_files": {"AAA": a["paths_file"], "BBB": b["paths_file"]}, "weights": {"AAA": 0.5, "BBB": 0.5}}, 0)
    with pytest.raises(ValueError):
        pp.run({"paths_files": {"AAA": a["paths_file"]}, "weights": {"AAA": 0.9}}, 0)   # веса не дают 1


def test_convergence_includes_loss_probability():
    out = cm.run({"calibration": cal_mature(), "equity_value_0": 30e9, "paths": 4000, "convergence_check": True, "robustness": False}, 0)
    conv = out["convergence"]
    assert "P_loss_gt_30pct_5Y" in next(iter(conv["runs"].values())) and "P_loss_gt_30pct_5Y" in conv["tolerance"]


def test_scenario_mixture_weighted(tmp_path):
    """Scenario Engine §2/§6/§7: BASE — остаток; pending-вероятность → только по-сценарные метрики; при вероятностях — взвешенная
    эмпирическая смесь (p=1 у BASE воспроизводит обычный прогон), impacts, ScenarioConcentration; детерминизм; контракт."""
    import pytest
    base_a = _run_store(_joint(cal_mature(), "AAA"), tmp_path); base_b = _run_store(_joint(cal_capital(), "BBB"), tmp_path)
    down = {"scenario_id": "DOWN", "driver_overrides": {"AI_COMPUTE_DEMAND": {"mean_shift_sigma": -2.0}}}
    mk = lambda tk, c, rid: cm.run({"calibration": c, "equity_value_0": 30e9, "joint_layer_spec": SPEC, "global_seed": 101, "paths": 6000, "convergence_check": False, "robustness": False, "store_paths": True, "_runs_dir": str(tmp_path), "_run_id": rid, "scenario": down}, 0)
    da = mk("AAA", _joint(cal_mature(), "AAA"), "t-AAA-DOWN"); db = mk("BBB", _joint(cal_capital(), "BBB"), "t-BBB-DOWN")
    files_b = {"AAA": base_a["paths_file"], "BBB": base_b["paths_file"]}; files_d = {"AAA": da["paths_file"], "BBB": db["paths_file"]}
    w = {"AAA": 0.5, "BBB": 0.4}
    pend = pp.run({"scenarios": [{"id": "BASE", "paths_files": files_b}, {"id": "DOWN", "probability": None, "paths_files": files_d}], "weights": w, "dry_powder_weight": 0.1, "dry_powder_return_annual": 0.04}, 0)
    assert pend["probability_status"] == "pending_owner_judgment" and pend["horizons"] is None and pend["scenario_concentration"] is None and pend["scenario_delta_vs_BASE"]["DOWN"]["Y5"]["median_CAGR"] < 0
    out = pp.run({"scenarios": [{"id": "BASE", "paths_files": files_b}, {"id": "DOWN", "probability": 0.3, "paths_files": files_d}], "weights": w, "dry_powder_weight": 0.1, "dry_powder_return_annual": 0.04}, 0)
    assert out["mode"] == "scenario_mixture" and out["scenarios"][0]["probability"] == 0.7 and out["decision"] == "none"
    b, d, m = out["by_scenario"]["BASE"]["Y5"], out["by_scenario"]["DOWN"]["Y5"], out["horizons"]["Y5"]
    assert d["median_CAGR"] < b["median_CAGR"] and min(b["median_CAGR"], d["median_CAGR"]) - 1e-9 <= m["median_CAGR"] <= max(b["median_CAGR"], d["median_CAGR"]) + 1e-9
    imp = out["scenario_impacts"]["DOWN"]; assert imp["probability"] == 0.3 and imp["MedianImpact_Y5"] < 0 and imp["adverse_ES_burden_B"] >= 0
    sc_ = out["scenario_concentration"]; assert sc_["applicable"] is False and sc_["status"] in ("not_applicable_single_adverse_scenario", "not_applicable_no_adverse_scenario")   # один non-BASE сценарий → лимит не применяется (вариант «а»)
    single = pp.run({"paths_files": files_b, "weights": w, "dry_powder_weight": 0.1, "dry_powder_return_annual": 0.04}, 0)
    only = pp.run({"scenarios": [{"id": "BASE", "paths_files": files_b}, {"id": "DOWN", "probability": 0.0, "paths_files": files_d}], "weights": w, "dry_powder_weight": 0.1, "dry_powder_return_annual": 0.04}, 0)
    assert abs(only["horizons"]["Y5"]["median_CAGR"] - single["horizons"]["Y5"]["median_CAGR"]) < 1e-9 and abs(only["horizons"]["Y5"]["expected_shortfall_5pct"] - single["horizons"]["Y5"]["expected_shortfall_5pct"]) < 1e-6
    assert pp.run({"scenarios": out and [{"id": "BASE", "paths_files": files_b}, {"id": "DOWN", "probability": 0.3, "paths_files": files_d}], "weights": w, "dry_powder_weight": 0.1, "dry_powder_return_annual": 0.04}, 0)["horizons"] == out["horizons"]
    with pytest.raises(ValueError):
        pp.run({"scenarios": [{"id": "BASE", "paths_files": files_b}, {"id": "DOWN", "probability": 1.2, "paths_files": files_d}], "weights": w, "dry_powder_weight": 0.1, "dry_powder_return_annual": 0.04}, 0)
    with pytest.raises(ValueError):
        pp.run({"scenarios": [{"id": "DOWN", "probability": 0.3, "paths_files": files_d}], "weights": w, "dry_powder_weight": 0.1, "dry_powder_return_annual": 0.04}, 0)


def test_mixture_export_partition(tmp_path):
    """mixture_export (1.3.0): разбиение path_id по сценариям — k чётные, BASE остаток, одни диапазоны у всех компаний; файлы-смеси
    читаются обычным прогоном, их метрики ≈ взвешенная смесь §6; meta сохраняет выравнивание; pending-вероятность → ValueError."""
    base_a = _run_store(_joint(cal_mature(), "AAA"), tmp_path); base_b = _run_store(_joint(cal_capital(), "BBB"), tmp_path)
    down = {"scenario_id": "DOWN", "driver_overrides": {"AI_COMPUTE_DEMAND": {"mean_shift_sigma": -2.0}}}
    mk = lambda c, rid: cm.run({"calibration": c, "equity_value_0": 30e9, "joint_layer_spec": SPEC, "global_seed": 101, "paths": 6000, "convergence_check": False, "robustness": False, "store_paths": True, "_runs_dir": str(tmp_path), "_run_id": rid, "scenario": down}, 0)
    da = mk(_joint(cal_mature(), "AAA"), "t-AAA-DOWN"); db = mk(_joint(cal_capital(), "BBB"), "t-BBB-DOWN")
    files_b = {"AAA": base_a["paths_file"], "BBB": base_b["paths_file"]}; files_d = {"AAA": da["paths_file"], "BBB": db["paths_file"]}
    scen = [{"id": "BASE", "paths_files": files_b}, {"id": "DOWN", "probability": 0.3, "paths_files": files_d}]
    assert pp.mixture_ranges(6000, {"DOWN": 0.3, "BASE": 0.7}, ["BASE", "DOWN"]) == {"BASE": (0, 4200), "DOWN": (4200, 6000)}
    assert pp.mixture_ranges(1001, {"S": 0.333, "BASE": 0.667}, ["BASE", "S"])["S"] == (669, 1001)                     # k = round(333.3) = 333 → 332 (чётное)
    ex = pp.run({"mode": "mixture_export", "scenarios": scen, "out_dir": str(tmp_path / "mix"), "tag": "t"}, 0)
    assert ex["mode"] == "mixture_export" and ex["ranges"] == {"BASE": [0, 4200], "DOWN": [4200, 6000]} and set(ex["paths_files"]) == {"AAA", "BBB"}
    ma = pp.load_paths(ex["paths_files"]["AAA"]); mb = pp.load_paths(ex["paths_files"]["BBB"])
    assert len(ma["r5"]) == 6000 and np.array_equal(ma["path_id"], mb["path_id"]) and ma["meta"]["global_seed"] == 101 and ma["meta"]["joint"] is True
    assert ma["meta"]["mixture"]["probabilities"] == {"DOWN": 0.3, "BASE": 0.7}
    # состав: первые 4200 — BASE-пути, остальные — DOWN-пути тех же path_id
    assert np.array_equal(ma["r5"][:4200], pp.load_paths(files_b["AAA"])["r5"][:4200]) and np.array_equal(ma["r5"][4200:], pp.load_paths(files_d["AAA"])["r5"][4200:])
    w = {"AAA": 0.5, "BBB": 0.4}
    plain = pp.run({"paths_files": ex["paths_files"], "weights": w, "dry_powder_weight": 0.1, "dry_powder_return_annual": 0.04}, 0)
    weighted = pp.run({"scenarios": scen, "weights": w, "dry_powder_weight": 0.1, "dry_powder_return_annual": 0.04}, 0)
    for k in ("median_CAGR", "P_loss_gt_30pct", "expected_shortfall_5pct", "P_2x"):
        assert plain["horizons"]["Y5"][k] == pytest.approx(weighted["horizons"]["Y5"][k], abs=0.02), k                 # стратифицированная выборка ≈ взвешенная смесь
    with pytest.raises(ValueError):
        pp.run({"mode": "mixture_export", "scenarios": [{"id": "BASE", "paths_files": files_b}, {"id": "DOWN", "probability": None, "paths_files": files_d}], "out_dir": str(tmp_path / "mix2")}, 0)


def test_scenario_concentration_rule_a():
    """ScenarioConcentration по варианту «а» (IMMA 25.09): 0 adverse → not_applicable; 1 adverse → raw 1.0, лимит не применяется;
    ≥2 adverse → max/Σ по A с warning > 0.50 и hard > 0.60; BASE вне знаменателя."""
    c0 = pp.scenario_concentration({"TS": 0.0, "CW": 0.0})
    assert c0["applicable"] is False and c0["status"] == "not_applicable_no_adverse_scenario" and c0["value"] is None and not c0["hard_limit_breach"]
    c1 = pp.scenario_concentration({"TS": 0.05, "CW": 0.0})
    assert c1["applicable"] is False and c1["status"] == "not_applicable_single_adverse_scenario" and c1["raw_value"] == 1.0 and c1["value"] is None and not c1["hard_limit_breach"]
    c2 = pp.scenario_concentration({"TS": 0.07, "CW": 0.03, "BASE": 0.0})
    assert c2["applicable"] and c2["value"] == pytest.approx(0.7) and c2["warning"] and c2["hard_limit_breach"] and c2["adverse_scenarios"] == ["CW", "TS"]
    c3 = pp.scenario_concentration({"A": 0.05, "B": 0.05, "C": 0.04})
    assert c3["value"] == pytest.approx(5 / 14) and not c3["warning"] and not c3["hard_limit_breach"]
