"""Тесты проверки полноты замены норматива (calc/tools/check_supersedes.py)."""
import os
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import check_supersedes as cs  # noqa: E402

WS = Path(os.environ.get("INVEST_WORKSPACE", "C:/openclaw-lab/data/workspace-invest"))


def test_removed_changed_and_lists():
    old = {"version": "1.1", "principles": {"a": True, "b": True}, "registry": {"kpi": {"ok": {"label_ru": "x", "semantics": "s"}}},
           "rules": [{"id": "R-1", "rule": "one"}, {"id": "R-2", "rule": "two"}], "tags": ["a", "b"], "as_of": "2026-09-22"}
    new = {"version": "1.2", "registry": {"kpi": {"ok": {"label_ru": "x"}, "new": {"label_ru": "y"}}},
           "rules": [{"id": "R-1", "rule": "one (edited)"}, {"id": "R-3", "rule": "three"}], "tags": ["a"], "as_of": "2026-09-23", "extra": 1}
    removed, changed = cs.compare(old, new)
    assert removed == ["$.principles", "$.registry.kpi.ok.semantics", "$.rules[id=R-2]", "$.tags['b']"]
    assert changed == ["$.version", "$.rules[id=R-1].rule", "$.as_of"]           # добавления и изменения — не пропажа


def test_allow_and_no_false_alarm():
    old = {"a": {"b": 1, "c": [1, 2]}, "d": [{"id": "x", "v": 1}]}
    assert cs.compare(old, old) == ([], [])                                       # НЕсрабатывание: идентичные деревья
    new = {"a": {"c": [1, 2]}, "d": [{"id": "x", "v": 1}]}
    import json, tempfile
    d = Path(tempfile.mkdtemp())
    (d / "o.json").write_text(json.dumps(old), encoding="utf-8"); (d / "n.json").write_text(json.dumps(new), encoding="utf-8")
    assert not cs.check(d / "o.json", d / "n.json")["pass"]
    r = cs.check(d / "o.json", d / "n.json", allow=["$.a.b"])
    assert r["pass"] and r["removed_allowed"] == ["$.a.b"]
    assert cs.main([str(d / "o.json"), str(d / "n.json")]) == 1 and cs.main([str(d / "o.json"), str(d / "n.json"), "--allow", "$.a.b"]) == 0


def test_ref_extraction_is_not_removal():
    old = {"schema": {"properties": {"items": {"items": {"type": "object", "required": ["a"], "properties": {"a": {"type": "string"}}}}}}}
    new = {"schema": {"properties": {"items": {"items": {"$ref": "#/schema/$defs/item"}}}, "$defs": {"item": {"type": "object", "required": ["a"], "properties": {"a": {"type": "string"}}}}}}
    assert cs.compare(cs.deref(old, old), cs.deref(new, new)) == ([], [])
    lost = {"schema": {"properties": {"items": {"items": {"$ref": "#/schema/$defs/item"}}}, "$defs": {"item": {"type": "object", "properties": {"a": {"type": "string"}}}}}}
    assert cs.compare(cs.deref(old, old), cs.deref(lost, lost))[0] == ["$.schema.properties.items.items.required"]   # пропажа внутри $ref видна
    cyc = {"a": {"$ref": "#/a"}}
    assert cs.deref(cyc, cyc) is not None                                                                              # цикл не зависает


@pytest.mark.skipif(not (WS / "from_imma" / "Dozor_Verification_Protocol_v1.1.yaml").exists(), reason="workspace недоступен")
def test_live_dozor_v12_is_incomplete_and_artifact_v104_was_complete():
    r = cs.check(WS / "from_imma" / "Dozor_Verification_Protocol_v1.1.yaml", WS / "from_imma" / "Dozor_v1.2_and_Artifact_v1.0.5" / "Dozor_Verification_Protocol_v1.2.yaml")
    assert not r["pass"] and {"$.principles", "$.kpi_rules", "$.axis_verification.runtime_write_rules", "$.event_verification.independence_rule"} <= set(r["removed"])
    assert not [x for x in r["removed"] if x.startswith("$.output_report_schema")]                              # вынос в $defs — не пропажа
    r2 = cs.check(WS / "from_imma" / "Company_Artifact_Schema_v1.0.3.yaml", WS / "from_imma" / "Company_Artifact_Schema_v1.0.4.yaml")
    assert r2["pass"], r2["removed"][:5]                                                # v1.0.4 был полным переизданием
    r3 = cs.check(WS / "from_imma" / "Company_Artifact_Schema_v1.0.4.yaml", WS / "from_imma" / "Dozor_v1.2_and_Artifact_v1.0.5" / "Company_Artifact_Schema_v1.0.5.yaml")
    assert not r3["pass"] and r3["removed"] == ["$.known_migrations_v1_0_3_to_v1_0_4"]
