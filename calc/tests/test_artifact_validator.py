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
ART = WS / "methodology" / "Company_Artifact_Schema_v1.0.1.yaml"
CAND = WS / "methodology" / "Company_Candidate_Schema_v1.0.1.yaml"
needs_ws = pytest.mark.skipif(not (ART.exists() and CAND.exists() and (WS / "portfolio" / "nbis" / "kpis.yaml").exists()), reason="workspace недоступен")
TAX = {"A", "B"}


# ------------------------------------------------------------------ правила целостности без схем
def _docs():
    return {
        "states.yaml": {"schema_version": "1.0.1", "ticker": "T", "sources": {"S1": {"source_class": "regulatory_filing", "url": "u", "as_of": "2026-01-01"}},
                        "axes": {"Ax": {"states": {"S1": {}, "S2": {}}, "current": "S1", "source_refs": ["S1"]}}},
        "kpis.yaml": {"schema_version": "1.0.1", "ticker": "T", "critical_kpis": [
            {"id": "T-KPI-01", "source_class": "regulatory_filing", "source_ref": "S1", "last_value": 1.0, "value_type": "actual", "thresholds": {"green": "a", "yellow": "b", "red": "c"}}]},
        "triggers.yaml": {"schema_version": "1.0.1", "profile": "full_model", "meta": {"ticker": "T"}, "rules": {"trigger_not_decision": True},
                          "triggers": [{"id": "T-E-01", "axis": "Ax", "transition": {"from": "S1", "to": "S2"}, "kpis": ["T-KPI-01"], "action": "инвестиционное действие не предопределено"}]},
        "mpc_inputs.yaml": {"schema_version": "1.0.1", "ticker": "T", "driver_taxonomy_version": "9.9", "driver_exposure_vector": {"A": 1, "B": 0}, "failure_modes": [{"failure_id": "T-FM-01"}]},
        "state.json": {"schema_version": "1.0.1", "scenario_state": {"Ax": {"state": "S1", "source": "u"}}, "kpi_observations": [{"kpi_id": "T-KPI-01", "value": 1.0}]},
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
