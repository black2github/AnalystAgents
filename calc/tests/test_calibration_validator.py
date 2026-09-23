"""Тесты режима calibration валидатора (Company MC Calibration Schema v1.0.1 + MC-G5-001..013 + сухой прогон движка)."""
import copy
import os
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import artifact_validator as av  # noqa: E402

WS = Path(os.environ.get("INVEST_WORKSPACE", "C:/openclaw-lab/data/workspace-invest"))
SCHEMA = WS / "methodology" / "Company_MC_Calibration_Schema_v1.0.1.yaml"
EX = WS / "from_imma" / "MC_v1.1_partBC" / "Company_MC_Calibration_Schema_v1.0.1_examples.yaml"
needs_ws = pytest.mark.skipif(not (SCHEMA.exists() and EX.exists()), reason="схема калибровки / fixtures недоступны")


def _fixture(name):
    d = yaml.safe_load(EX.read_text(encoding="utf-8"))
    ex = d.get("fixtures") or d.get("examples")
    cal = ex[name]
    return copy.deepcopy(cal.get("calibration", cal))


# ------------------------------------------------------------------ правила без схемы
def test_rules_on_synthetic_calibration():
    cal = {"archetype": "pre_service_or_milestone_driven", "ticker": "T",
           "milestone_model": {"service_onset_milestone": "S", "milestones": [
               {"id": "A", "requires": ["S"], "value_uplift": 0.6, "probability": 0.9, "timing": {"distribution": "triangular", "min": 5, "mode": 4, "max": 8, "provenance": "model_assumption"}},
               {"id": "S", "requires": ["A", "ZZ"], "value_uplift": 0.6, "probability": 0.9, "timing": {"distribution": "triangular", "min": 1, "mode": 2, "max": 3, "provenance": "model_assumption"}},
               {"id": "D", "requires": [], "value_uplift": 0.1, "probability": 0.9, "timing": {"distribution": "truncated_normal", "mean": 9, "sd": 1, "min": 1, "max": 5, "provenance": "model_assumption"}},
               {"id": "D", "requires": [], "value_uplift": 0.0, "probability": 0.9, "timing": {"distribution": "triangular", "min": 1, "mode": 2, "max": 3, "provenance": "model_assumption"}}]},
           "margin_model": {"lower_bound": 0.5, "upper_bound": 0.1},
           "dependencies": {"latent_factors": ["growth", "margin", "valuation"], "factor_correlations": {"growth__margin": 0.95, "growth__valuation": 0.95, "margin__valuation": -0.9}},
           "joint_simulation": {"active_drivers": ["AI_COMPUTE_DEMAND"]},
           "driver_parameter_mapping": [{"driver_id": "AI_COMPUTE_DEMAND", "stochastic_targets": []}, {"driver_id": "INTEREST_RATES", "stochastic_targets": []}]}
    mpc = {"driver_exposure_vector": {"AI_COMPUTE_DEMAND": 2, "TAIWAN_SUPPLY": 2, "CHINA_REVENUE": 1, "INTEREST_RATES": -1}}
    F = av.integrity_calibration(cal, mpc, None, av.AGG_SHIFT_LIMITS, False)
    by = {}
    for f in F:
        by.setdefault(f["rule"], []).append((f["severity"], f["path"]))
    assert ("error", "driver_parameter_mapping/TAIWAN_SUPPLY") in by["MC-G5-001"] and ("warning", "driver_parameter_mapping/CHINA_REVENUE") in by["MC-G5-001"]
    assert any("INTEREST_RATES" in f["message"] for f in F if f["rule"] == "MC-G5-002")
    msgs5 = [f["message"] for f in F if f["rule"] == "MC-G5-005"]
    assert any("дубликаты" in m for m in msgs5) and any("ZZ" in m for m in msgs5) and any("цикл" in m for m in msgs5)
    assert "MC-G5-006" in by and "MC-G5-007" in by and "MC-G5-008" in by
    assert any("PSD" in f["message"] for f in F if f["rule"] == "MC-G5-008") and any("lower_bound" in f["message"] for f in F if f["rule"] == "MC-G5-008")


def test_clean_synthetic_has_no_findings():
    cal = {"archetype": "mature_positive_margin", "ticker": "T", "margin_model": {"lower_bound": 0.1, "upper_bound": 0.5},
           "dependencies": {"latent_factors": ["growth", "margin", "valuation"], "factor_correlations": {"growth__margin": 0.3}},
           "revenue_model": {"segments": {"Core": {"initial_growth": {"distribution": "pert", "min": 0.1, "mode": 0.2, "max": 0.3, "lambda": 4, "provenance": "model_assumption"}}}},
           "joint_simulation": {"active_drivers": []}, "driver_parameter_mapping": []}
    assert av.integrity_calibration(cal, {"driver_exposure_vector": {"X": 0}}, None, av.AGG_SHIFT_LIMITS, False) == []


# ------------------------------------------------------------------ живые проверки
@needs_ws
def test_fixtures_pass_schema_and_engine():
    for name in ("A", "B", "C"):
        out = av.run({"mode": "calibration", "workspace": str(WS), "calibration": _fixture(name), "dry_run_paths": 1500}, 0)
        assert out["schema_errors"] == [], (name, out["schema_errors"][:3])
        assert out["engine_dry_run"] and out["engine_dry_run"]["mapping_warnings"] == [] and out["engine_dry_run"]["deterministic"], (name, out["engine_dry_run"])
        assert not [f for f in out["integrity"] if f["severity"] == "error"], (name, out["integrity"])


@needs_ws
def test_received_calibrations_flag_aggregate_shift():
    p = WS / "from_imma" / "MC_v1.1_partBC" / "NVDA_mc_calibration_v1.0.yaml"
    if not p.exists():
        pytest.skip("нет калибровки NVDA")
    cal = yaml.safe_load(p.read_text(encoding="utf-8"))
    out = av.run({"mode": "calibration", "workspace": str(WS), "calibration": cal, "folders": ["nvda"], "dry_run_paths": 1500}, 0)
    assert out["schema_errors"] == [] and not out["pass"]                               # MC-G5-013 — hard gate (Rules v1.1)
    w = [f for f in out["integrity"] if f["rule"] == "MC-G5-013" and f["severity"] == "error"]
    assert w and any("initial_growth" in f["path"] for f in w)
    soft = av.run({"mode": "calibration", "workspace": str(WS), "calibration": cal, "folders": ["nvda"], "strict_aggregate": False, "engine_dry_run": False}, 0)
    assert soft["pass"] and all(f["severity"] != "error" for f in soft["integrity"])
    broken = copy.deepcopy(cal); broken["driver_parameter_mapping"][0]["stochastic_targets"][0]["path"] = "capacity_model.gw"
    out2 = av.run({"mode": "calibration", "workspace": str(WS), "calibration": broken, "folders": ["nvda"], "dry_run_paths": 1500}, 0)
    assert not out2["pass"] and (out2["schema_errors"] or any(f["rule"] == "MC-G5-003" for f in out2["integrity"]))
