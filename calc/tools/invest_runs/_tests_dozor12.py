

# ------------------------------------------------------------------ Artifact Schema v1.0.5: история прогонов (ART-REF-030/031)
def test_observation_history_rules():
    d = _docs()
    obs = d["state.json"]["kpi_observations"]
    obs[0].update({"period_end": "2026-06-30", "verification_run_id": "r2", "verification_run_ids": ["r1", "r2"]})
    assert not [f for f in av.integrity_workspace(d, TAX, {"regulatory_filing"}) if f["rule"] in ("ART-REF-030", "ART-REF-031")]
    obs[0]["verification_run_ids"] = ["r2", "r1"]                                                                              # последний ≠ alias
    obs.append({"kpi_id": "T-KPI-01", "period_end": "2026-06-30", "value": 1})                                                # 1 и 1.0 — дубликат
    obs.append({"kpi_id": "T-KPI-01", "period_end": "2026-03-31", "value": 1.0})                                              # другой период — НЕсрабатывание
    rules = [f["rule"] for f in av.integrity_workspace(d, TAX, {"regulatory_filing"})]
    assert rules.count("ART-REF-030") == 1 and rules.count("ART-REF-031") == 1


# ------------------------------------------------------------------ Dozor v1.2: transition_checks, DZR-011..015, итог по старшинству
EX12 = WS / "from_imma" / "Dozor_v1.2_and_Artifact_v1.0.5" / "verify-ASTS-v1.2-example.json"


def _ex12():
    import json
    return json.loads(EX12.read_text(encoding="utf-8"))


@pytest.mark.skipif(not (DOZOR.exists() and EX12.exists()), reason="протокол v1.2 / пример ASTS недоступны")
def test_v12_example_passes_and_live_v11_reports_pass():
    import json
    out = av.run({"mode": "dozor_report", "workspace": str(WS), "report": _ex12(), "folders": ["asts"]}, 0)
    assert out["pass"] and out["protocol_version"] == "1.2", (out["schema_errors"][:3], out["integrity"][:5])
    for tk, name in (("asts", "verify-ASTS-20260923T060714Z"), ("nbis", "verify-NBIS-20260922T210122Z")):
        p = WS / "portfolio" / tk / "_verify" / f"{name}.json"
        if p.exists():
            o = av.run({"mode": "dozor_report", "workspace": str(WS), "report": json.loads(p.read_text(encoding="utf-8")), "folders": [tk]}, 0)
            assert o["pass"], (name, o["schema_errors"][:3], o["integrity"][:5])


@pytest.mark.skipif(not (DOZOR.exists() and EX12.exists()), reason="протокол v1.2 / пример ASTS недоступны")
def test_v12_rules_fire():
    rep = _ex12()
    t0, t1, t2 = rep["transition_checks"][0], rep["transition_checks"][1], rep["transition_checks"][2]
    t0["trigger_id"] = "ASTS-E-99"                                                          # DZR-011: нет в triggers.yaml
    t1["axis"] = "Nope"; t1["kpi_item_refs"] = ["ASTS-KPI-99"]; t1["event_item_refs"] = ["ASTS-E-77"]
    t2["transition"] = {"from": "C3", "to": "Z9"}                                            # DZR-011: ≠ переход триггера / состояния нет в оси
    rep["transition_checks"][3].update({"result": "met", "runtime_verified": False, "patch_required": True})   # DZR-003 (реестр met) + DZR-015
    rep["transition_checks"][4].update({"result": "pending_history", "runtime_verified": None})               # pending → summary/итог
    k9 = next(i for i in rep["items"] if i["kpi_id"] == "ASTS-KPI-09"); k9["found"]["unit"] = "USD B"         # DZR-012: found не в базе кандидата
    ax = rep["axis_items"][0]; ax["current_state"] = "pending_verification"; ax["status"] = "state_pending_verification"; ax["runtime_verified"] = False  # DZR-014: criteria не null
    rep["event_items"][0].update({"status": "condition_not_met", "runtime_verified": False, "patch_required": True})            # DZR-015
    out = av.run({"mode": "dozor_report", "workspace": str(WS), "report": rep, "folders": ["asts"]}, 0)
    by = {}
    for f in out["integrity"]:
        by.setdefault(f["rule"], []).append(f["path"])
    assert not out["pass"] and out["schema_errors"] == []
    assert len(by["DZR-011"]) >= 6 and "transition_checks/0/trigger_id" in by["DZR-011"] and "transition_checks/2/transition" in by["DZR-011"]
    assert "transition_checks/3/runtime_verified" in by["DZR-003"] and "transition_checks/3/patch_required" in by["DZR-015"] and "event_items/0/patch_required" in by["DZR-015"]
    assert by["DZR-012"] == ["items/8/found"] or any(p.startswith("items/") for p in by["DZR-012"])
    assert by["DZR-014"] == ["axis_items/0"]
    assert "summary/pending_transition_checks" in by["DZR-005"] and "summary/patch_required_transition_checks" in by["DZR-005"]
    assert by["DZR-010"] == ["summary/overall_status"]                                                           # ожидается PATCH_REQUIRED, в отчёте PASS
    # итог: только pending_history без patch → PASS_WITH_DECLARED_PENDING; PASS — ошибка
    rep2 = _ex12(); rep2["transition_checks"][0].update({"result": "pending_history", "runtime_verified": None})
    rep2["summary"]["pending_transition_checks"] = ["ASTS-E-01"]; rep2["summary"]["transition_counts"] = {"not_met": 9, "pending_history": 1}
    out2 = av.run({"mode": "dozor_report", "workspace": str(WS), "report": rep2, "folders": ["asts"]}, 0)
    assert [f["path"] for f in out2["integrity"]] == ["summary/overall_status"] and "PASS_WITH_DECLARED_PENDING" in out2["integrity"][0]["message"]
    rep2["summary"]["overall_status"] = "PASS_WITH_DECLARED_PENDING"
    assert av.run({"mode": "dozor_report", "workspace": str(WS), "report": rep2, "folders": ["asts"]}, 0)["pass"]
    # v1.1-отчёт с event_items без claim_type и found в базе источника — по-прежнему валиден (правила v1.2 не ретроактивны)
    rep3 = _ex12(); rep3["protocol_version"] = "1.1.0"; k9 = next(i for i in rep3["items"] if i["kpi_id"] == "ASTS-KPI-09"); k9["found"]["unit"] = "USD B"
    for e in rep3["event_items"]:
        e.pop("claim_type", None)
    assert av.run({"mode": "dozor_report", "workspace": str(WS), "report": rep3, "folders": ["asts"]}, 0)["pass"]
