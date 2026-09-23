"""Тесты валидатора артефактов (гейт G5). Схемы берутся из workspace/methodology (INVEST_WORKSPACE); без workspace —
пропуск живых тестов, синтетические правила целостности проверяются без схем."""
import copy
import os
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import artifact_validator as av  # noqa: E402
from tools import migrate_artifacts_v1_0_1 as mig  # noqa: E402

WS = Path(os.environ.get("INVEST_WORKSPACE", "C:/openclaw-lab/data/workspace-invest"))
ART = WS / "methodology" / "Company_Artifact_Schema_v1.0.5.yaml"
CAND = WS / "methodology" / "Company_Candidate_Schema_v1.0.1.yaml"
needs_ws = pytest.mark.skipif(not (ART.exists() and CAND.exists() and (WS / "portfolio" / "nbis" / "kpis.yaml").exists()), reason="workspace недоступен")
TAX = {"A", "B"}


# ------------------------------------------------------------------ правила целостности без схем
def _docs():
    return {
        "states.yaml": {"schema_version": av.SCHEMA_VERSION, "ticker": "T", "sources": {"S1": {"source_class": "regulatory_filing", "url": "u", "as_of": "2026-01-01"}},
                        "axes": {"Ax": {"states": {"S1": {}, "S2": {}}, "current": "S1", "source_refs": ["S1"]}}},
        "kpis.yaml": {"schema_version": av.SCHEMA_VERSION, "ticker": "T", "critical_kpis": [
            {"id": "T-KPI-01", "source_class": "regulatory_filing", "source_ref": "S1", "last_value": 1.0, "value_type": "actual", "thresholds": {"green": "a", "yellow": "b", "red": "c"}}]},
        "triggers.yaml": {"schema_version": av.SCHEMA_VERSION, "profile": "full_model", "meta": {"ticker": "T"}, "rules": {"trigger_not_decision": True},
                          "triggers": [{"id": "T-E-01", "axis": "Ax", "transition": {"from": "S1", "to": "S2"}, "kpis": ["T-KPI-01"], "action": "инвестиционное действие не предопределено"}]},
        "mpc_inputs.yaml": {"schema_version": av.SCHEMA_VERSION, "ticker": "T", "driver_taxonomy_version": "9.9", "driver_exposure_vector": {"A": 1, "B": 0}, "failure_modes": [{"failure_id": "T-FM-01"}]},
        "state.json": {"schema_version": av.SCHEMA_VERSION, "scenario_state": {"Ax": {"state": "S1", "source": "u"}}, "kpi_observations": [{"kpi_id": "T-KPI-01", "value": 1.0}]},
    }


def test_clean_documents_have_no_findings():
    assert av.integrity_workspace(_docs(), TAX, {"regulatory_filing"}) == []


@pytest.mark.parametrize("mutate, rule", [
    (lambda d: d["triggers.yaml"]["triggers"][0].__setitem__("axis", "Nope"), "ART-REF-001"),
    (lambda d: d["triggers.yaml"]["triggers"][0]["transition"].__setitem__("to", "S9"), "ART-REF-002"),
    (lambda d: d["triggers.yaml"]["triggers"][0].__setitem__("kpis", ["T-KPI-99"]), "ART-REF-003"),
    (lambda d: d["states.yaml"]["axes"]["Ax"].__setitem__("source_refs", ["S9"]), "ART-REF-004"),
    (lambda d: d["kpis.yaml"]["critical_kpis"][0].__setitem__("source_class", "blog"), "ART-REF-005"),
    (lambda d: d["kpis.yaml"]["critical_kpis"][0].__setitem__("last_value", ">40"), "ART-REF-007"),
    (lambda d: d["kpis.yaml"]["critical_kpis"][0].__setitem__("value_type", "lower_bound"), "ART-REF-008"),
    (lambda d: d["state.json"]["scenario_state"].__setitem__("Zz", {"state": "S1"}), "ART-REF-009"),
    (lambda d: d["state.json"]["scenario_state"]["Ax"].__setitem__("state", "S9"), "ART-REF-010"),
    (lambda d: d["state.json"]["kpi_observations"][0].__setitem__("kpi_id", "T-KPI-99"), "ART-REF-011"),
    (lambda d: d["kpis.yaml"]["critical_kpis"].append(dict(d["kpis.yaml"]["critical_kpis"][0])), "ART-REF-012"),
    (lambda d: d["mpc_inputs.yaml"]["driver_exposure_vector"].pop("B"), "ART-REF-014"),
    (lambda d: d["triggers.yaml"]["rules"].__setitem__("trigger_not_decision", False), "ART-REF-015"),
    (lambda d: d["kpis.yaml"].__setitem__("schema_version", "1.0"), "ART-REF-016"),
    (lambda d: d["mpc_inputs.yaml"].__setitem__("ticker", "OTHER"), "ART-REF-017"),
    (lambda d: d["kpis.yaml"]["critical_kpis"][0].update({"observation_qualifier": "range", "value_range": {"min": 1}}), "ART-REF-018"),
    (lambda d: d["kpis.yaml"]["critical_kpis"][0].update({"observation_qualifier": "lower_bound", "last_value": None}), "ART-REF-019"),
    (lambda d: d["kpis.yaml"]["critical_kpis"][0].__setitem__("source_ref", "S9"), "ART-REF-020"),
    (lambda d: d["state.json"]["kpi_observations"][0].__setitem__("value_type", "approximate"), "ART-REF-021"),
    (lambda d: d["kpis.yaml"]["critical_kpis"][0]["thresholds"].pop("yellow"), "ART-REF-022"),
    (lambda d: d["state.json"]["scenario_state"]["Ax"].update({"evidence_type": "qualitative_primary_source", "source": None}), "ART-REF-023"),
])
def test_each_rule_fires(mutate, rule):
    d = _docs()
    mutate(d)
    rules = {f["rule"] for f in av.integrity_workspace(d, TAX, {"regulatory_filing"})}
    assert rule in rules, rules


def test_registry_only_skips_cross_file_checks_and_action_warning_is_not_error():
    d = _docs()
    d["triggers.yaml"]["profile"] = "registry_only"
    d["triggers.yaml"]["triggers"][0].update({"axis": "Nope", "kpis": ["T-KPI-99"], "action": "купить 10 акций"})
    F = av.integrity_workspace(d, TAX, {"regulatory_filing"})
    assert not [f for f in F if f["rule"] in ("ART-REF-001", "ART-REF-003")]
    assert [f for f in F if f["rule"] == "ART-REF-015"][0]["severity"] == "warning"
    d["triggers.yaml"]["triggers"][0]["status"] = "paused"                   # приостановленный триггер не предупреждает
    assert not [f for f in av.integrity_workspace(d, TAX, {"regulatory_filing"}) if f["rule"] == "ART-REF-015"]


def test_binary_kpi_without_yellow_is_ok():
    d = _docs()
    d["kpis.yaml"]["critical_kpis"][0]["thresholds"] = {"binary": True, "green": "=1", "red": "=0"}
    assert not [f for f in av.integrity_workspace(d, TAX, {"regulatory_filing"}) if f["rule"] == "ART-REF-022"]


# ------------------------------------------------------------------ живые прогоны
@needs_ws
def test_workspace_after_migration_passes(tmp_path):
    import shutil
    from tests.test_migrate_artifacts import _copy
    _copy(tmp_path, ["nbis", "asts", "hood"])          # снимок S0 (до миграции)
    shutil.copytree(WS / "methodology", tmp_path / "methodology")
    for f in mig.iter_folders(tmp_path, None):
        assert not mig.migrate_folder(f, apply=True)["errors"]
    out = av.run({"workspace": str(tmp_path), "folders": "all"}, 0)
    assert out["summary"] == {"folders": 3, "pass": 3, "fail": 0, "failed": []}, {k: (v["files"], v["integrity"]) for k, v in out["folders"].items() if not v["pass"]}
    assert out["folders"]["nbis"]["profile"] == "full_model" and out["folders"]["nbis"]["integrity_warnings"] == 0
    # незамигрированная папка (S0) — не проходит, и именно по схеме
    _copy(tmp_path, ["nvda"])
    out2 = av.run({"workspace": str(tmp_path), "folders": ["nvda"]}, 0)
    assert out2["summary"]["fail"] == 1 and out2["folders"]["nvda"]["schema_errors"] > 0
    assert av.run({"workspace": str(tmp_path), "folders": ["nope"]}, 0)["folders"]["nope"]["pass"] is False


@needs_ws
def test_candidate_example_passes_and_broken_candidate_fails():
    schema = yaml.safe_load(CAND.read_text(encoding="utf-8"))
    ex = copy.deepcopy(schema["x-full-example"])
    out = av.run({"mode": "candidate", "workspace": str(WS), "candidate": ex}, 0)
    assert out["pass"], (out["schema_errors"][:3], out["integrity"][:3])
    bad = copy.deepcopy(ex)
    bad["kpis"]["items"][0]["local_id"] = f"{ex['ticker']}-KPI-01"                  # канонический ID у кандидата
    bad["transitions"]["items"][0]["kpi_refs"] = ["kpi_zz"]
    bad["states"]["axes"][next(iter(bad["states"]["axes"]))]["current"] = "Z9"
    bad["mpc_inputs"]["driver_exposure_vector"].pop(next(iter(bad["mpc_inputs"]["driver_exposure_vector"])))
    out = av.run({"mode": "candidate", "workspace": str(WS), "candidate": bad}, 0)
    rules = {f["rule"] for f in out["integrity"]}
    assert not out["pass"] and {"CAND-REF-015", "CAND-REF-008", "CAND-REF-009", "CAND-REF-014"} <= rules, rules


DOZOR = WS / "methodology" / "Dozor_Verification_Protocol_v1.2.yaml"


def _report(**over):
    item = {"kpi_id": "NBIS-KPI-01", "status": "verified_match", "candidate": {"last_value": 5.14, "value_type": "actual", "observation_qualifier": "exact", "unit": "YoY fraction", "period": "quarterly"},
            "source_check": {"source_ref": None, "source_class": "issuer_ir_release", "url": "https://www.sec.gov/x", "allowed_by_policy": True, "technical_status": "accessible"},
            "found": {"value": 5.14, "value_type": "actual", "observation_qualifier": "exact", "unit": "YoY fraction", "period": "quarterly"},
            "normalization": {"applied": False, "steps": []}, "runtime_verified": True, "patch_required": False}
    item.update(over)
    return {"protocol_version": "1.0.0", "run_id": "verify-NBIS-20260922T200000Z", "ticker": "NBIS", "as_of": "2026-09-22T20:00:00Z",
            "inputs": {"kpis_ref": "portfolio/nbis/kpis.yaml", "source_registry_ref": "portfolio/nbis/states.yaml", "evidence_pack_ref": None},
            "items": [item], "summary": {"overall_status": "PASS", "counts": {"verified_match": 1}, "patch_required_kpis": [], "technical_blocked_kpis": [], "pending_kpis": []}}


@pytest.mark.skipif(not DOZOR.exists(), reason="протокол дозора недоступен")
def test_dozor_report_mode():
    ok = av.run({"mode": "dozor_report", "workspace": str(WS), "report": _report(), "folders": ["nbis"]}, 0)
    assert ok["pass"], (ok["schema_errors"][:3], ok["integrity"])
    bad = av.run({"mode": "dozor_report", "workspace": str(WS), "report": _report(kpi_id="NBIS-KPI-99", status="mismatch_value", runtime_verified=True, patch_required=False), "folders": ["nbis"]}, 0)
    rules = {f["rule"] for f in bad["integrity"]}
    assert not bad["pass"] and {"DZR-002", "DZR-003", "DZR-004"} <= rules, rules
    incons = av.run({"mode": "dozor_report", "workspace": str(WS), "report": _report(status="mismatch_value", runtime_verified=False, patch_required=True)}, 0)
    assert {f["rule"] for f in incons["integrity"]} == {"DZR-005", "DZR-010"}  # patch_required у item, но summary пуст и итог PASS
    broken = _report(); broken["items"][0]["status"] = "kinda_ok"
    assert not av.run({"mode": "dozor_report", "workspace": str(WS), "report": broken}, 0)["pass"]


@pytest.mark.skipif(not DOZOR.exists(), reason="протокол дозора недоступен")
def test_live_v10_report_and_v11_example_pass():
    import json
    live = WS / "portfolio" / "nbis" / "_verify" / "verify-NBIS-20260922T201443Z.json"
    ex = WS / "from_imma" / "verify-NBIS-v1.1-example.json"
    for p in (live, ex):
        if not p.exists():
            pytest.skip(f"нет {p.name}")
        out = av.run({"mode": "dozor_report", "workspace": str(WS), "report": json.loads(p.read_text(encoding="utf-8")), "folders": ["nbis"]}, 0)
        assert out["pass"], (p.name, out["schema_errors"][:3], out["integrity"][:5])
    rep = json.loads(ex.read_text(encoding="utf-8"))
    rep["axis_items"][0]["axis_id"] = "Nope"; rep["axis_items"][0]["kpi_item_refs"] = ["NBIS-KPI-99"]
    rep["event_items"][0]["trigger_id"] = "NBIS-E-99"; rep["event_items"][0]["fact_only"] = False
    rep["axis_items"][1]["status"] = "state_not_supported"; rep["axis_items"][1]["patch_required"] = False
    bad = av.run({"mode": "dozor_report", "workspace": str(WS), "report": rep, "folders": ["nbis"]}, 0)
    rules = {f["rule"] for f in bad["integrity"]}
    assert not bad["pass"] and {"DZR-006", "DZR-007", "DZR-008", "DZR-009", "DZR-003", "DZR-004"} <= rules, rules


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
