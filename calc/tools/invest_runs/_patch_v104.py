"""Правки lab под Company Artifact Schema v1.0.4 и Dozor Protocol v1.1: миграция, валидатор (режим dozor_report с осями и
событиями по status_registry), тесты."""
from pathlib import Path

C = Path("C:/openclaw-lab/calc")

# --- миграция: цель 1.0.4
p = C / "tools/migrate_artifacts_v1_0_1.py"; s = p.read_text(encoding="utf-8")
old = 'SCHEMA_VERSION = "1.0.3"  # цепочка патчей v1.0.1 → v1.0.2 (MIG-112/113) → v1.0.3 (MIG-114/115); bump — той же утилитой'
assert s.count(old) <= 1
s = s.replace(old, 'SCHEMA_VERSION = "1.0.4"  # цепочка патчей v1.0.1 → v1.0.2 (MIG-112/113) → v1.0.3 (MIG-114/115) → v1.0.4 (MIG-117); bump — той же утилитой')
p.write_text(s, encoding="utf-8", newline="\n")

# --- валидатор
p = C / "engine/artifact_validator.py"; s = p.read_text(encoding="utf-8")
rep = [
    ('VERSION = "1.1.0"\nSCHEMA_VERSION = "1.0.3"            # Company Artifact Schema (v1.0.3: paused, verification linkage)',
     'VERSION = "1.2.0"\nSCHEMA_VERSION = "1.0.4"            # Company Artifact Schema (v1.0.4: recorded_at, verification_run_id у осей/событий)'),
    ('DOZOR_PROTOCOL_VERSION = "1.0"      # Dozor Verification Protocol (схема отчёта output_report_schema)',
     'DOZOR_PROTOCOL_VERSION = "1.1"      # Dozor Verification Protocol (схема отчёта output_report_schema; отчёты v1.0 валидны)'),
    ('"""Валидатор артефактов компаний v1.1 — гейт G5 (Runtime_Quality_Gates: schema + ID + references) по Company Artifact\nSchema v1.0.3',
     '"""Валидатор артефактов компаний v1.2 — гейт G5 (Runtime_Quality_Gates: schema + ID + references) по Company Artifact\nSchema v1.0.4'),
]
for a, b in rep:
    assert s.count(a) == 1, a[:60]
    s = s.replace(a, b)
import re
DOC_NEW = ('"folders": ["<папка>"] для сверки с kpis/states/triggers папки; правила DZR-001..010: тикер, kpi_id, runtime_verified и\n'
           '        patch_required по status_registry протокола, согласованность summary, оси/состояния/kpi_item_refs, trigger_id, fact_only, итог)')
s, n = re.subn(r'"?folders"?: \["<папка>"\] для сверки kpi_id/ticker[^\n]*\n[^\n]*согласованность summary\)', lambda m: DOC_NEW, s)
assert n == 1, n
old = s[s.index("        kp = None\n        if folders:"):s.index("        n_err = sum(1 for f in findings if f[\"severity\"] == \"error\")\n        return {\"model_version\": VERSION, \"protocol_version\"")]
new = '''        kp = st_doc = tr_doc = None
        if folders:
            fd = ws / "portfolio" / folders[0]
            kp = _load(fd / "kpis.yaml") if (fd / "kpis.yaml").exists() else None
            st_doc = _load(fd / "states.yaml") if (fd / "states.yaml").exists() else None
            tr_doc = _load(fd / "triggers.yaml") if (fd / "triggers.yaml").exists() else None
        if kp is not None:
            ids = {k.get("id") for k in kp.get("critical_kpis", [])}
            if kp.get("ticker") and rep.get("ticker") and kp.get("ticker") != rep.get("ticker"):
                findings.append(_f("DZR-001", "ticker", f"{rep.get('ticker')!r} ≠ kpis.yaml {kp.get('ticker')!r}"))
            for i, it in enumerate(rep.get("items") or []):
                if it.get("kpi_id") not in ids:
                    findings.append(_f("DZR-002", f"items/{i}/kpi_id", f"{it.get('kpi_id')!r} не найден в kpis.yaml"))
        # реестр статусов протокола (v1.1: status_registry.<группа>.<статус>; v1.0: runtime_verified_mapping)
        reg = proto.get("status_registry") or {}
        legacy_map = proto.get("runtime_verified_mapping") or {}
        patch_statuses = ("mismatch_value", "mismatch_period", "mismatch_semantics", "formula_mismatch", "source_not_allowed")

        def _expect(group, status):
            e = (reg.get(group) or {}).get(status)
            if e is not None:
                return e.get("runtime_verified"), bool(e.get("default_patch_required"))
            v = legacy_map.get(status)
            return (v if isinstance(v, bool) else None), status in patch_statuses

        def _check(group, path, obj):
            exp, need_patch = _expect(group, obj.get("status"))
            if isinstance(exp, bool) and obj.get("runtime_verified") is not exp:
                findings.append(_f("DZR-003", f"{path}/runtime_verified", f"для статуса {obj.get('status')!r} ожидается {exp!r}, получено {obj.get('runtime_verified')!r}"))
            if need_patch and obj.get("patch_required") is not True:
                findings.append(_f("DZR-004", f"{path}/patch_required", f"статус {obj.get('status')!r} требует patch_required=true"))

        for i, it in enumerate(rep.get("items") or []):
            _check("kpi", f"items/{i}", it)
        summ = rep.get("summary") or {}
        ids_patch = {it.get("kpi_id") for it in rep.get("items") or [] if it.get("patch_required")}
        if set(summ.get("patch_required_kpis") or []) != ids_patch:
            findings.append(_f("DZR-005", "summary/patch_required_kpis", f"не совпадает с items: {sorted(ids_patch)}"))
        # v1.1: оси и события
        axes = ((st_doc or {}).get("axes") or {}) if st_doc else None
        kpi_ids_rep = {it.get("kpi_id") for it in rep.get("items") or []}
        for i, a in enumerate(rep.get("axis_items") or []):
            ax = a.get("axis_id")
            if axes is not None and ax not in axes:
                findings.append(_f("DZR-006", f"axis_items/{i}/axis_id", f"ось {ax!r} не найдена в states.yaml"))
            elif axes is not None and a.get("current_state") not in ("pending_verification", None) and a.get("current_state") not in (axes[ax].get("states") or {}):
                findings.append(_f("DZR-006", f"axis_items/{i}/current_state", f"состояние {a.get('current_state')!r} не найдено в оси {ax!r}"))
            for r in a.get("kpi_item_refs") or []:
                if r not in kpi_ids_rep:
                    findings.append(_f("DZR-007", f"axis_items/{i}/kpi_item_refs", f"{r!r} не входит в items этого отчёта"))
            _check("axis", f"axis_items/{i}", a)
        trig_ids = {t.get("id") for t in (tr_doc or {}).get("triggers", [])} if tr_doc else None
        for i, ev in enumerate(rep.get("event_items") or []):
            if trig_ids is not None and ev.get("trigger_id") not in trig_ids:
                findings.append(_f("DZR-008", f"event_items/{i}/trigger_id", f"{ev.get('trigger_id')!r} не найден в triggers.yaml"))
            if ev.get("fact_only") is not True:
                findings.append(_f("DZR-009", f"event_items/{i}/fact_only", "событие подтверждает факт, не переход и не действие: fact_only должен быть true"))
            _check("event", f"event_items/{i}", ev)
        ax_patch = {a.get("axis_id") for a in rep.get("axis_items") or [] if a.get("patch_required")}
        if set(summ.get("patch_required_axes") or []) != ax_patch:
            findings.append(_f("DZR-005", "summary/patch_required_axes", f"не совпадает с axis_items: {sorted(ax_patch)}"))
        ev_patch = {e.get("trigger_id") for e in rep.get("event_items") or [] if e.get("patch_required")}
        if set(summ.get("patch_required_events") or []) != ev_patch:
            findings.append(_f("DZR-005", "summary/patch_required_events", f"не совпадает с event_items: {sorted(ev_patch)}"))
        if (ids_patch or ax_patch or ev_patch) and summ.get("overall_status") not in ("PATCH_REQUIRED", "BLOCKED_TECHNICAL", "BLOCKED_SOURCE_CONFLICT"):
            findings.append(_f("DZR-010", "summary/overall_status", "есть patch_required, а итог не PATCH_REQUIRED/BLOCKED_*"))
'''
s = s.replace(old, new)
p.write_text(s, encoding="utf-8", newline="\n")

# --- тесты
for name in ("tests/test_migrate_artifacts.py", "tests/test_artifact_validator.py"):
    t = C / name
    ts = t.read_text(encoding="utf-8").replace("Company_Artifact_Schema_v1.0.3.yaml", "Company_Artifact_Schema_v1.0.4.yaml").replace("Dozor_Verification_Protocol_v1.0.yaml", "Dozor_Verification_Protocol_v1.1.yaml")
    t.write_text(ts, encoding="utf-8", newline="\n")
t = C / "tests/test_artifact_validator.py"; ts = t.read_text(encoding="utf-8")
ts += '''

@pytest.mark.skipif(not DOZOR.exists(), reason="протокол дозора недоступен")
def test_live_v10_report_and_v11_example_pass():
    import json
    live = WS / "portfolio" / "nbis" / "_verify" / "verify-NBIS-20260922T201443Z.json"
    ex = WS / "inbox" / "received" / "verify-NBIS-v1.1-example.json"
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
'''
t.write_text(ts, encoding="utf-8", newline="\n")
print("lab patched: tool 1.0.4, validator 1.2.0, tests")
