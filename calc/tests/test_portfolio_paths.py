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
