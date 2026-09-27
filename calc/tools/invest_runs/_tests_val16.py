

# ------------------------------------------------------------------ 1.6.0: схема по schema_version калибровки; квартал измерения вех — как в движке
@needs_ws
def test_schema_selected_by_calibration_version_and_milestone_quarter():
    old_p = WS / "portfolio" / "nvda" / "mc_calibration_v1.0.2.yaml"                       # принятая калибровка, схема 1.0.1 (закреплена)
    new_p = WS / "from_imma" / "HOOD_RKLB_v1.0.1_and_MC_v1.1.3" / "HOOD_mc_calibration_v1.0.1.yaml"   # схема 1.0.2
    rk_p = WS / "from_imma" / "HOOD_RKLB_v1.0.1_and_MC_v1.1.3" / "RKLB_mc_calibration_v1.0.1.yaml"
    if not (old_p.exists() and new_p.exists() and rk_p.exists()):
        pytest.skip("нет калибровок для проверки выбора схемы")
    old = yaml.safe_load(old_p.read_text(encoding="utf-8"))
    out = av.run({"mode": "calibration", "workspace": str(WS), "calibration": old, "folders": ["nvda"], "engine_dry_run": False, "dispersion_check": False}, 0)
    assert out["schema_version"] == "1.0.1" and out["schema_errors"] == []
    new = yaml.safe_load(new_p.read_text(encoding="utf-8"))
    out2 = av.run({"mode": "calibration", "workspace": str(WS), "calibration": new, "folders": ["hood"], "engine_dry_run": False, "dispersion_check": False}, 0)
    assert out2["schema_version"] == "1.0.2" and out2["schema_errors"] == []
    wrong = copy.deepcopy(new); wrong["schema_version"] = "1.0.1"                            # файл v1.0.2-формы с чужой версией — ловится const схемы 1.0.1
    out3 = av.run({"mode": "calibration", "workspace": str(WS), "calibration": wrong, "folders": ["hood"], "engine_dry_run": False, "dispersion_check": False}, 0)
    assert out3["schema_version"] == "1.0.1" and out3["schema_errors"]
    rk = yaml.safe_load(rk_p.read_text(encoding="utf-8"))
    out4 = av.run({"mode": "calibration", "workspace": str(WS), "calibration": rk, "folders": ["rklb"], "engine_dry_run": False, "dispersion_check": False}, 0)
    agg = out4["aggregate_shift"]
    p1 = agg["milestone_model.milestones.NEUTRON_FIRST_ORBITAL.probability"]; t1 = agg["milestone_model.milestones.NEUTRON_FIRST_ORBITAL.timing"]
    assert p1["quarter"] == 3 and t1["quarter"] == 3 and p1["kind"] == "milestone_probability" and t1["kind"] == "milestone_timing"   # мода сроков 2 кв. → q3, не q20
    assert p1["cap"] == 0.35 and t1["cap"] == 1.0 and p1["ok"] and t1["ok"]
    assert agg["revenue_model.service_segments.Neutron.post_service_growth"]["quarter"] == 20
