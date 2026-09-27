"""Независимая приёмка пакета Dozor v1.2 + Artifact Schema v1.0.5 (jsonschema Draft 2020-12, валидатор 1.4.0 с подменой протокола)."""
import copy
import json
import sys
from collections import Counter
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator as V

sys.path.insert(0, "C:/openclaw-lab/calc")
from engine import artifact_validator as av  # noqa: E402

WS = Path("C:/openclaw-lab/data/workspace-invest")
PK = Path("C:/Users/alexe/Downloads/Dozor_Verification_Protocol_v1.2_and_Artifact_v1.0.5")
proto = yaml.safe_load((PK / "Dozor_Verification_Protocol_v1.2.yaml").read_text(encoding="utf-8"))
art = yaml.safe_load((PK / "Company_Artifact_Schema_v1.0.5.yaml").read_text(encoding="utf-8"))
RS = proto["output_report_schema"]

print("== 1. схемы валидны (Draft 2020-12)")
V.check_schema(RS); print("  протокол v1.2 output_report_schema: OK")
for fn, spec in art["files"].items():
    sch = spec.get("schema") or spec
    V.check_schema(sch); print(f"  Artifact v1.0.5 {fn}: OK")

print("== 2. полнота реестра статусов")
reg = proto["status_registry"]
D = RS["$defs"]
enum_groups = {"kpi": D["kpi_item"]["properties"]["status"]["enum"], "axis": D["axis_item"]["properties"]["status"]["enum"],
               "event": D["event_item"]["properties"]["status"]["enum"], "transition_result": D["transition_check"]["properties"]["result"]["enum"],
               "overall": RS["properties"]["summary"]["properties"]["overall_status"]["enum"]}
for g, en in enum_groups.items():
    r = reg.get(g) or {}
    miss = [s for s in en if s not in r]; extra = [s for s in r if s not in en]
    need = ("label_ru",) if g == "overall" else ("label_ru", "runtime_verified", "gate_effect", "default_patch_required")
    incomplete = [s for s, e in r.items() if any(k not in e for k in need)]
    print(f"  {g}: enum {len(en)} / реестр {len(r)}; нет в реестре {miss}; лишние {extra}; неполные {incomplete}")

print("== 3. отчёты по схеме v1.2 (валидатор 1.4.0, протокол подменён)")
reports = {"NBIS v1.0 (run1)": ("nbis", WS / "portfolio/nbis/_verify/verify-NBIS-20260922T201443Z.json"),
           "NBIS v1.1 (run2)": ("nbis", WS / "portfolio/nbis/_verify/verify-NBIS-20260922T210122Z.json"),
           "ASTS v1.1 (live)": ("asts", WS / "portfolio/asts/_verify/verify-ASTS-20260923T060714Z.json"),
           "ASTS v1.2 example": ("asts", PK / "verify-ASTS-v1.2-example.json")}
loaded = {}
for name, (folder, p) in reports.items():
    rep = json.loads(p.read_text(encoding="utf-8")); loaded[name] = rep
    out = av.run({"mode": "dozor_report", "workspace": str(WS), "report": rep, "folders": [folder], "dozor_protocol_path": str(PK / "Dozor_Verification_Protocol_v1.2.yaml")}, 0)
    print(f"  {name}: schema_errors {len(out['schema_errors'])}, integrity {[(f['rule'], f['path']) for f in out['integrity']]}, pass {out['pass']}")
    for e in out["schema_errors"][:5]:
        print("     ", e)

print("== 4. семантика примера v1.2 (DZR-012..016 + согласованность summary)")
ex = loaded["ASTS v1.2 example"]; live = loaded["ASTS v1.1 (live)"]
items = {i["kpi_id"]: i for i in ex["items"]}; live_items = {i["kpi_id"]: i for i in live["items"]}
k9 = items["ASTS-KPI-09"]
print("  DZR-012 KPI-09: found.unit == candidate.unit:", k9["found"]["unit"] == k9["candidate"]["unit"], "| found.value == candidate.last_value:", k9["found"]["value"] == k9["candidate"]["last_value"],
      "| formula_recomputed_value:", k9["found"]["formula_recomputed_value"], "| found.period:", repr(k9["found"]["period"]))
print("  DZR-013 claim_type:", Counter(e.get("claim_type") for e in ex["event_items"]))
print("  DZR-014 оси pending:", [(a["axis_id"], a["criteria"], a.get("pending_reason")) for a in ex["axis_items"] if a["current_state"] == "pending_verification"] or "нет таких осей в ASTS")
bad15 = [t["trigger_id"] for t in ex["transition_checks"] if t["result"] == "not_met" and (t["patch_required"] or t["runtime_verified"] is not False)]
print("  DZR-015 not_met с patch/runtime≠false:", bad15)
qps_state = []
for fd in sorted((WS / "portfolio").iterdir()):
    sp = fd / "state.json"
    if sp.exists() and "qualifier_patch_suggested" in sp.read_text(encoding="utf-8"):
        qps_state.append(fd.name)
print("  DZR-016 qualifier_patch_suggested в state.json workspace:", qps_state or "нет")
s = ex["summary"]
print("  counts == items:", dict(Counter(i["status"] for i in ex["items"])) == s["counts"], "| axis_counts:", dict(Counter(a["status"] for a in ex["axis_items"])) == s["axis_counts"],
      "| event_counts:", dict(Counter(e["status"] for e in ex["event_items"])) == s["event_counts"], "| transition_counts:", dict(Counter(t["result"] for t in ex["transition_checks"])) == s["transition_counts"])
print("  qualifier_patch_suggested_kpis == items:", sorted(k for k, i in items.items() if i.get("qualifier_patch_suggested")) == sorted(s["qualifier_patch_suggested_kpis"]))
# итог по precedence
pend = [t["trigger_id"] for t in ex["transition_checks"] if t["result"] == "pending_history"] + [e["trigger_id"] for e in ex["event_items"] if e["status"] == "event_unconfirmed"] \
    + [a["axis_id"] for a in ex["axis_items"] if a["status"] == "state_pending_verification" and not a["patch_required"]] + [i["kpi_id"] for i in ex["items"] if i["status"] == "not_found"]
patch = [x for x in ex["items"] + ex["axis_items"] + ex["event_items"] + ex["transition_checks"] if x["patch_required"]]
print("  pending:", pend, "| patch:", len(patch), "| ожидаемый итог:", "PATCH_REQUIRED" if patch else ("PASS_WITH_DECLARED_PENDING" if pend else "PASS"), "| в примере:", s["overall_status"])
# ссылочная целостность transition_checks против triggers.yaml / states.yaml ASTS
tr = av._load(WS / "portfolio/asts/triggers.yaml"); st = av._load(WS / "portfolio/asts/states.yaml")
trig = {t["id"]: t for t in tr["triggers"]}
print("  пример триггера ASTS:", {k: trig["ASTS-E-01"].get(k) for k in ("id", "axis", "transition", "from", "to", "type", "status")})
for t in ex["transition_checks"]:
    tt = trig.get(t["trigger_id"]); probs = []
    if tt is None: probs.append("нет в triggers.yaml")
    else:
        tr_ax = tt.get("axis"); tr_tr = tt.get("transition") or {}
        if tr_ax and tr_ax != t["axis"]: probs.append(f"axis {tr_ax}≠{t['axis']}")
        if isinstance(tr_tr, dict) and tr_tr and (tr_tr.get("from"), tr_tr.get("to")) != (t["transition"]["from"], t["transition"]["to"]): probs.append(f"transition {tr_tr}≠{t['transition']}")
    if t["axis"] not in st["axes"]: probs.append("оси нет в states.yaml")
    else:
        sts = st["axes"][t["axis"]].get("states") or {}
        for k in ("from", "to"):
            if t["transition"][k] not in sts: probs.append(f"{k}={t['transition'][k]} нет в оси")
    for r in t["kpi_item_refs"]:
        if r not in items: probs.append(f"kpi_ref {r} нет в items")
    for r in t.get("event_item_refs") or []:
        if r not in {e["trigger_id"] for e in ex["event_items"]}: probs.append(f"event_ref {r} нет в event_items")
    if probs: print("   ", t["trigger_id"], probs)
print("  transition_checks: ссылочная проверка выполнена")
# KPI примера == живой отчёт (кроме KPI-09)
diff = [k for k in items if k != "ASTS-KPI-09" and (items[k]["status"], items[k]["found"]["value"], items[k]["found"]["period"]) != (live_items[k]["status"], live_items[k]["found"]["value"], live_items[k]["found"]["period"])]
print("  KPI примера отличаются от живого v1.1 (кроме KPI-09):", diff or "нет")
we = [c.get("window_entailment") for a in ex["axis_items"] for c in a["criterion_checks"] if c.get("window_entailment")]
print("  window_entailment:", we)

print("== 5. Artifact Schema v1.0.5 по 13 папкам (const schema_version ослаблен до 1.0.4|1.0.5)")
art_relaxed = copy.deepcopy(art)
txt = yaml.safe_dump(art_relaxed, allow_unicode=True).replace("const: 1.0.5", "enum: ['1.0.4', '1.0.5']")
art_relaxed = yaml.safe_load(txt)
av_sv = av.SCHEMA_VERSION; av.SCHEMA_VERSION = "1.0.4"
tot = 0
for fd in sorted((WS / "portfolio").iterdir()):
    if not fd.is_dir() or fd.name.startswith("_") or fd.name == "spacex" or not (fd / "triggers.yaml").exists():
        continue
    docs = {fn: av._load(fd / fn) for fn in av.ARTIFACT_FILES if (fd / fn).exists()}
    r = av.validate_documents(docs, art_relaxed, WS)
    n = sum(len(v.get("schema_errors", [])) for v in r["files"].values()); tot += n
    errs = [f for f in r["integrity"] if f["severity"] == "error"]
    if n or errs: print(f"  {fd.name}: schema_errors {n}, integrity_errors {[(f['rule'], f['path']) for f in errs]}")
print("  суммарно schema_errors:", tot)
# fixture: история run IDs
docs = {fn: av._load(WS / "portfolio/asts" / fn) for fn in av.ARTIFACT_FILES if (WS / "portfolio/asts" / fn).exists()}
obs = docs["state.json"]["kpi_observations"][0]; obs["verification_run_ids"] = [obs["verification_run_id"] + "-old", obs["verification_run_id"]]
r = av.validate_documents(docs, art_relaxed, WS); print("  fixture verification_run_ids (2 записи): schema_errors", sum(len(v.get("schema_errors", [])) for v in r["files"].values()))
obs["verification_run_ids"] = [obs["verification_run_id"], obs["verification_run_id"]]
r = av.validate_documents(docs, art_relaxed, WS); print("  fixture дубликат в списке (uniqueItems): schema_errors", sum(len(v.get("schema_errors", [])) for v in r["files"].values()))
obs["verification_run_ids"] = ["verify-X"]  # ART-REF-030: последний ≠ verification_run_id — только правило, схема не ловит
r = av.validate_documents(docs, art_relaxed, WS); print("  fixture последний ≠ alias (ART-REF-030): schema_errors", sum(len(v.get("schema_errors", [])) for v in r["files"].values()), "(ожидаемо 0 — правило, не схема)")
av.SCHEMA_VERSION = av_sv

print("== 6. предпросмотр MIG-122 и ART-REF-031 по state.json")
for fd in sorted((WS / "portfolio").iterdir()):
    sp = fd / "state.json"
    if not sp.exists(): continue
    sj = json.loads(sp.read_text(encoding="utf-8")); ko = sj.get("kpi_observations") or []
    with_run = [o for o in ko if o.get("verification_run_id")]
    keys = Counter((o.get("kpi_id"), o.get("period_end"), json.dumps(o.get("value"), sort_keys=True), json.dumps(o.get("value_range"), sort_keys=True)) for o in ko)
    dups = [k for k, n in keys.items() if n > 1]
    if ko: print(f"  {fd.name}: наблюдений {len(ko)}, с verification_run_id {len(with_run)} ({sorted({o['verification_run_id'] for o in with_run})}), дубликаты kpi+period+value: {len(dups)}")
