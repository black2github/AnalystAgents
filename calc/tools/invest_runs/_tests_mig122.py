

# ------------------------------------------------------------------ MIG-122 (Artifact Schema v1.0.5): история прогонов дозора
def _rep(run_id, kpi_id, last_value, value_range=None, verified=True):
    return {"run_id": run_id, "items": [{"kpi_id": kpi_id, "runtime_verified": verified, "candidate": {"last_value": last_value, "value_range": value_range}}]}


def test_mig122_collapse_seed_backfill_and_order():
    obs = [
        {"kpi_id": "K1", "period_end": "2026-06-30", "value": 3, "value_raw": "three", "verified": True},                      # legacy-строка run1 (без run_id)
        {"kpi_id": "K1", "period_end": "2026-06-30", "value": 3.0, "observation_qualifier": "exact", "verification_run_id": "verify-T-20260922T210122Z"},
        {"kpi_id": "K2", "period_end": "2026-06-30", "value": None, "value_range": {"min": 50, "max": 60}, "verification_run_id": "verify-T-20260922T210122Z"},
        {"kpi_id": "K1", "period_end": "2026-03-31", "value": 2.0, "verified": True},                                           # другой период — не дубликат
        {"kpi_id": "K3", "period_end": "2026-06-30", "value": 7.0, "verified": True},                                           # без прогона — история не выдумывается
    ]
    reports = [_rep("verify-T-20260922T201443Z", "K1", 3.0), _rep("verify-T-20260922T201443Z", "K3", 8.0),                     # K3: значение не совпало → не привязывать
               _rep("verify-T-20260923T000000Z", "K2", None, {"min": 50, "max": 60}), _rep("verify-T-20260920T000000Z", "K1", 3.0, verified=False)]
    out = mig.migrate_observations(obs, reports)
    assert [o["kpi_id"] for o in out] == ["K1", "K2", "K1", "K3"]                                                               # 3 и 3.0 — одно наблюдение
    k1 = out[0]
    assert k1["value"] == 3.0 and k1["observation_qualifier"] == "exact" and k1["value_raw"] == "three"                       # победила строка с прогоном, поля добраны
    assert k1["verification_run_ids"] == ["verify-T-20260922T201443Z", "verify-T-20260922T210122Z"] and k1["verification_run_id"] == "verify-T-20260922T210122Z"
    assert out[1]["verification_run_ids"] == ["verify-T-20260922T210122Z", "verify-T-20260923T000000Z"] and out[1]["verification_run_id"] == "verify-T-20260923T000000Z"
    assert "verification_run_ids" not in out[2] and "verification_run_ids" not in out[3]                                       # НЕсрабатывание: без связи — без истории
    assert mig.migrate_observations(out, reports) == out                                                                       # идемпотентность


@needs_ws
def test_mig122_live_nbis_history_from_immutable_reports():
    folder = WS / "portfolio" / "nbis"
    docs = {fn: mig.load_plain(folder / fn) for fn in mig.FILES if (folder / fn).exists()}
    out = mig.migrate_docs(docs, mig.load_verify_reports(folder))["state.json"]["kpi_observations"]
    assert len(out) == 11 and len({o["kpi_id"] for o in out}) == 11
    k1 = next(o for o in out if o["kpi_id"] == "NBIS-KPI-01")
    assert k1["verification_run_ids"] == ["verify-NBIS-20260922T201443Z", "verify-NBIS-20260922T210122Z"] and k1["verification_run_id"] == "verify-NBIS-20260922T210122Z"
    k11 = next(o for o in out if o["kpi_id"] == "NBIS-KPI-11")
    assert k11["verification_run_ids"] == ["verify-NBIS-20260922T210122Z"]                                                   # not_found в run1 → run1 не привязан
