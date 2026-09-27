"""Дозапись state.json по иммутабельному отчёту дозора (AGENTS.md §9, протокол v1.2, Artifact Schema v1.0.5) — роль интегратора,
когда исполнитель записал отчёт, но упал до обновления runtime (NVDA run1: биллинг OpenRouter).
Наблюдение с тем же kpi_id + period_end + значением обновляется (ART-REF-031), run_id добавляется в verification_run_ids
(ART-REF-030); иное значение/период — новая строка. Файл должен быть дамп-идемпотентным (иначе отказ)."""
import json
import sys
from pathlib import Path

WS = Path(sys.argv[1]); folder = sys.argv[2]; run_id = sys.argv[3]; APPLY = "--apply" in sys.argv
fd = WS / "portfolio" / folder
rep = json.loads((fd / "_verify" / f"{run_id}.json").read_text(encoding="utf-8"))
sp = fd / "state.json"; raw = open(sp, encoding="utf-8", newline="").read(); sj = json.loads(raw)
assert json.dumps(sj, ensure_ascii=False, indent=2) + "\n" == raw.replace("\r\n", "\n"), "state.json не дамп-идемпотентен — нужен построчный патч"
assert sj.get("verification", {}).get("run_id") != run_id, "прогон уже записан"
VERIFIED = {"verified_match", "verified_match_with_normalization"}
NULLS = {"source_unavailable_technical", "source_conflict", "not_found"}


def numf(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v


log = []
obs = sj.setdefault("kpi_observations", [])
for it in rep["items"]:
    st = it["status"]; f = it["found"]
    period_end = None
    # period_end берём из существующей строки того же KPI (у NVDA — 2026-07-26), иначе из as_of документа
    same = [o for o in obs if o["kpi_id"] == it["kpi_id"]]
    cand_val = it["candidate"].get("last_value")
    # подтверждённый KPI = то же наблюдение, что канонический кандидат (нормализация округления — не новое значение):
    # ищем строку по candidate.last_value; found с большей точностью (0.45283 при 0.4528) строку не плодит
    match = [o for o in same if numf(o.get("value")) == numf(cand_val) and (o.get("value_range") or None) == (it["candidate"].get("value_range") or None)]
    verified = True if st in VERIFIED else (None if st in NULLS else False)
    if match:
        o = match[-1]
        o.update({"value_type": f.get("value_type") or o.get("value_type"), "observation_qualifier": f.get("observation_qualifier") or o.get("observation_qualifier"),
                  "source_url": it["source_check"].get("url") or o.get("source_url"), "verified": verified, "verification_run_id": run_id})
        ids = list(o.get("verification_run_ids") or [])
        if run_id not in ids:
            ids.append(run_id)
        o["verification_run_ids"] = ids
        log.append(f"{it['kpi_id']}: обновлено ({st})")
    else:
        obs.append({"kpi_id": it["kpi_id"], "period_end": same[-1].get("period_end") if same else None, "value": f.get("value"), "value_range": f.get("value_range"),
                    "value_type": f.get("value_type"), "observation_qualifier": f.get("observation_qualifier"), "unit": f.get("unit"), "source_url": it["source_check"].get("url"),
                    "provenance": "verified_fact", "verified": verified, "verification_run_id": run_id, "verification_run_ids": [run_id]})
        log.append(f"{it['kpi_id']}: НОВАЯ строка ({st}, found {f.get('value')} ≠ прежнего)")
for a in rep.get("axis_items", []):
    s = sj["scenario_state"].get(a["axis_id"])
    if s is None:
        continue
    if a["status"] == "state_supported":
        s["verified"] = True; s["verification_run_id"] = run_id
    elif a["status"] in ("state_not_supported", "state_pending_verification"):
        s["verified"] = False; s["verification_run_id"] = run_id
    log.append(f"ось {a['axis_id']}: {a['status']}")
for e in rep.get("event_items", []):
    if e["status"] in ("event_confirmed_primary", "event_confirmed_two_media"):
        sj.setdefault("events_reported", []).append({"trigger_id": e["trigger_id"], "event_date": e.get("event_date"), "claim": e["event_claim"], "verification_run_id": run_id})
        log.append(f"событие {e['trigger_id']}: записано в events_reported")
summ = rep["summary"]
sj["verification"] = {"run_id": run_id, "as_of": rep["as_of"], "overall_status": summ["overall_status"]}
sj.setdefault("info_log", []).append({"timestamp": rep["as_of"], "kind": "verification", "summary":
    f"Сверка по Dozor Verification Protocol v1.2 (гейт G8), run_id {run_id}: итог {summ['overall_status']}; KPI {summ['counts']}; оси {summ.get('axis_counts')}; "
    f"переходы {summ.get('transition_counts')} (pending: {summ.get('pending_transition_checks')}); события {summ.get('event_counts')} (pending: {summ.get('pending_events')}). "
    "Отчёт записан исполнителем-дозором; runtime дописан интегратором по отчёту (прогон прерван ошибкой биллинга OpenRouter после записи отчёта)."})
sj["updated"] = rep["as_of"]
for l in log:
    print("-", l)
if APPLY:
    with open(sp, "w", encoding="utf-8", newline="\r\n" if "\r\n" in raw else "\n") as fh:
        fh.write(json.dumps(sj, ensure_ascii=False, indent=2) + "\n")
print("режим:", "ЗАПИСЬ" if APPLY else "сухой прогон")
