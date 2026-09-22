"""Тесты миграции артефактов к Company Artifact Schema v1.0.1 (calc/tools/migrate_artifacts_v1_0_1.py).
Синтетическая часть не зависит от workspace; живая часть берёт папки из workspace (INVEST_WORKSPACE или путь по умолчанию)
и пропускается, если workspace недоступен."""
import json
import os
import shutil
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import migrate_artifacts_v1_0_1 as mig  # noqa: E402

WS = Path(os.environ.get("INVEST_WORKSPACE", "C:/openclaw-lab/data/workspace-invest"))
SCHEMA = WS / "methodology" / "Company_Artifact_Schema_v1.0.1.yaml"
needs_ws = pytest.mark.skipif(not (WS / "portfolio" / "nbis" / "kpis.yaml").exists() or not SCHEMA.exists(), reason="workspace недоступен")


# ------------------------------------------------------------------ синтетика
def test_split_value_forms():
    assert mig.split_value(">40") == (40, {"observation_qualifier": "lower_bound"})
    assert mig.split_value("<0.01") == (0.01, {"observation_qualifier": "upper_bound"})
    assert mig.split_value([0.5, 0.6]) == (None, {"observation_qualifier": "range", "value_range": {"min": 0.5, "max": 0.6}})
    assert mig.split_value(5.14) == (5.14, {})
    assert mig.split_value(None) == (None, {})
    assert mig.split_value("текст") == ("текст", {})     # НЕсрабатывание: произвольная строка не трогается


def test_source_class_rules():
    assert mig.source_class("https://www.sec.gov/Archives/edgar/data/1/2/x-20260630.htm", None) == "regulatory_filing"
    assert mig.source_class("https://www.sec.gov/Archives/edgar/data/1/2/tm_ex99-1.htm", None) == "issuer_ir_release"
    assert mig.source_class("https://www.sec.gov/.../presentationinvestor.htm", "SEC 6-K") == "issuer_investor_presentation"
    assert mig.source_class("https://query1.finance.yahoo.com/v8/finance/chart/NBIS", None) == "market_data_provider"
    assert mig.source_class(None, "SEC") == "regulatory_filing"
    assert mig.source_class(None, "IR") == "issuer_ir_release"
    assert mig.source_class(None, None) == "other_primary"


def _docs():
    return {
        "states.yaml": {"version": "1.0", "as_of": "2026-09-21", "ticker": "TST", "semantics": {"thresholds_provenance": "model_assumption", "primary_only": True},
                        "sources": {"A": "https://www.sec.gov/x-20260630.htm", "B": {"url": "https://ir.test.com/q2", "type": "IR release"}},
                        "axes": {"Ax": {"states": {"S1": {}, "S2": {}}, "current": "S1"}}},
        "kpis.yaml": {"ticker": "TST", "source_artifact": "inbox/received/TST.yaml", "critical_kpis": [
            {"id": "TST-KPI-01", "source": "SEC", "last_value": ">40", "thresholds": {"green": ">=50", "yellow": ">=40", "red": "<40"}},
            {"id": "TST-KPI-02", "source": "IR", "last_value": 1, "value_type": "lower_bound", "thresholds": {"green": "=1", "red": "=0"}},
            {"id": "TST-KPI-03", "source": "IR", "last_value": [1, 2], "thresholds": {"green": "x", "red": "y"}}]},
        "triggers.yaml": {"meta": {"ticker": "TST", "horizon": 2030}, "automations": {"_note": "нет"},
                          "triggers": [{"id": "TST-E-01", "transition": {"from": "S1", "to": "S2"}, "axis": "Ax"}, {"id": "TST-P-01", "class": "price"}]},
        "mpc_inputs.yaml": {"ticker": "TST", "driver_exposure_vector": {}},
        "state.json": {"notes": "n", "price": {"last": 10.0}, "kpi_observations": [{"kpi_id": "TST-KPI-01", "value": ">40"}], "conviction": {"tag": True}},
    }


def test_migrate_docs_semantics_and_idempotence():
    d0 = _docs()
    d1 = mig.migrate_docs(d0)
    assert d0["kpis.yaml"]["critical_kpis"][0]["last_value"] == ">40"          # вход не изменён
    k = d1["kpis.yaml"]["critical_kpis"]
    assert k[0]["last_value"] == 40 and k[0]["observation_qualifier"] == "lower_bound" and k[0]["value_type"] == "actual" and k[0]["source_class"] == "regulatory_filing"
    assert k[1]["value_type"] == "actual" and k[1]["observation_qualifier"] == "lower_bound" and k[1]["thresholds"]["binary"] is True
    assert k[2]["last_value"] is None and k[2]["value_range"] == {"min": 1, "max": 2} and "binary" not in k[2]["thresholds"]   # зоны «x/y» не бинарны — НЕсрабатывание MIG-106
    sem = d1["states.yaml"]["semantics"]
    assert sem["numeric_thresholds_provenance"] == "model_assumption" and "thresholds_provenance" not in sem and sem["evidence_required"] is True and sem["primary_only"] is True
    assert d1["states.yaml"]["sources"]["A"] == {"url": "https://www.sec.gov/x-20260630.htm", "source_class": "regulatory_filing", "as_of": "2026-09-21"}
    assert d1["states.yaml"]["sources"]["B"]["source_class"] == "issuer_ir_release" and d1["states.yaml"]["sources"]["B"]["type"] == "IR release"
    tr = d1["triggers.yaml"]
    assert tr["profile"] == "full_model" and tr["automations"] == {} and tr["automations_note"] == "нет" and tr["meta"]["horizon"] == "2030"
    assert tr["triggers"][0]["condition_provenance"] == "model_assumption" and tr["triggers"][0]["fired"] == [] and "condition_provenance" not in tr["triggers"][1]
    assert tr["rules"] == {"evidence_required": True, "pending_verification_blocks_transition": True, "trigger_not_decision": True}
    assert tr["meta"]["price_at_registry"] == 10.0 and tr["meta"]["source_artifact"] == "inbox/received/TST.yaml" and tr["meta"]["position"] is None
    sj = d1["state.json"]
    assert sj["notes"] == ["n"] and sj["kpi_observations"][0]["value"] == 40 and sj["conviction"]["provenance"] == "owner_judgment" and sj["scenario_state"] == {}
    assert all(d["schema_version"] == "1.0.1" for d in d1.values())
    assert mig.migrate_docs(d1) == d1                                          # идемпотентность эталона


def test_registry_only_profile():
    d = {"triggers.yaml": {"meta": {"ticker": "X"}, "triggers": [{"id": "X-E-01", "transition": {"from": "a", "to": "b"}}]}, "state.json": {}}
    out = mig.migrate_docs(d)
    assert out["triggers.yaml"]["profile"] == "registry_only" and "fired" not in out["triggers.yaml"]["triggers"][0] and "rules" not in out["triggers.yaml"]
    assert out["state.json"]["notes"] == [] and out["state.json"]["kpi_observations"] == []


# ------------------------------------------------------------------ живой прогон на копии workspace
def _copy(tmp_path, names):
    for n in names:
        shutil.copytree(WS / "portfolio" / n, tmp_path / "portfolio" / n)
    return tmp_path


@needs_ws
def test_live_patch_equals_reference_and_is_idempotent(tmp_path):
    from jsonschema import Draft202012Validator as V
    ws = _copy(tmp_path, ["nbis", "asts", "net", "6506"])
    schema = yaml.safe_load(SCHEMA.read_text(encoding="utf-8"))
    before = {n: {fn: (ws / "portfolio" / n / fn).read_bytes() for fn in mig.FILES if (ws / "portfolio" / n / fn).exists()} for n in ["nbis", "asts", "net", "6506"]}
    reports = {r["folder"]: r for r in (mig.migrate_folder(f, apply=True) for f in mig.iter_folders(ws, None))}
    assert all(not r["errors"] for r in reports.values()), reports
    assert reports["nbis"]["profile"] == "full_model" and reports["6506"]["profile"] == "registry_only"
    # остаток «target_weight» у legacy-реестров NET/ETN/registry_only ждёт патча схемы v1.0.2 (заказан 22.09) — допускаем только его
    known_residual = {"Additional properties are not allowed ('target_weight' was unexpected)"}
    for n in ["nbis", "asts", "net"]:
        for fn, s in schema["files"].items():
            errs = [e.message for e in V(s).iter_errors(mig.load_plain(ws / "portfolio" / n / fn))]
            assert set(errs) <= known_residual and (n == "net" or not errs), (n, fn, errs[:3])
    # байты: переводы строк и BOM сохранены; комментарии на месте
    for n, files in before.items():
        for fn, old in files.items():
            new = (ws / "portfolio" / n / fn).read_bytes()
            assert (b"\r\n" in old) == (b"\r\n" in new) and not new.startswith(b"\xef\xbb\xbf")
            assert old.count(b"#") <= new.count(b"#")
    # И1: ID, состояния, условия
    for n in ["nbis", "asts", "net"]:
        old = yaml.safe_load(before[n]["triggers.yaml"].decode("utf-8")); new = yaml.safe_load((ws / "portfolio" / n / "triggers.yaml").read_text(encoding="utf-8"))
        assert [(t["id"], t.get("condition")) for t in old["triggers"]] == [(t["id"], t.get("condition")) for t in new["triggers"]]
    # И3: второй прогон ничего не меняет
    again = [mig.migrate_folder(f, apply=False) for f in mig.iter_folders(ws, None)]
    assert all(not r["changed"] and not r["errors"] for r in again)


@needs_ws
def test_live_no_change_without_apply(tmp_path):
    ws = _copy(tmp_path, ["nvda"])
    old = (ws / "portfolio" / "nvda" / "kpis.yaml").read_bytes()
    r = mig.migrate_folder(ws / "portfolio" / "nvda", apply=False)
    assert "kpis.yaml" in r["changed"] and (ws / "portfolio" / "nvda" / "kpis.yaml").read_bytes() == old
