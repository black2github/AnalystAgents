"""NET (партия 3): модель компании встраивается в СУЩЕСТВУЮЩИЙ реестр владельца (17.09): states/kpis/mpc_inputs — новые файлы;
triggers.yaml — добавить шаг маршрута vector, привязать NET-E-*/X-* к осям (binding_guidance LLM), добавить переходы NET-E-06..E-11
из proposed_transitions_without_ids (ID присваивает дозор); state.json — добавить scenario_state и пр. Существующие записи не менять."""
import json
from pathlib import Path
import yaml

D = Path("C:/Users/alexe/Downloads"); TODAY = "2026-09-21"
SHARE = "https://chatgpt.com/share/6ab0ce43-9540-83eb-8e39-ec1d3e21002c"
Q = json.load(open("_quotes_2026-09-20.json", encoding="utf-8"))
AXIS_RU = {"Revenue_Growth": "рост выручки", "Expansion_Retention": "расширение и удержание (NRR)", "Contracted_Demand": "законтрактованный спрос (RPO)",
           "Profitability_Cash": "прибыльность и денежный поток", "AI_Edge_Monetization": "монетизация ИИ на edge (Workers AI)"}
def dump(o): return yaml.safe_dump(o, allow_unicode=True, sort_keys=False, width=120)

d = yaml.safe_load((D / "NET_company_state_v1.0.yaml").read_text(encoding="utf-8"))
out = Path("portfolio/net"); sources = d.get("sources", {})
src_note = f"inbox/received/NET_company_state_v1.0.yaml (другая LLM, партия 3, {TODAY}, share {SHARE})"
axes_src = d["states"]["axes"]

# states.yaml
axes = {ax: {"name": ax.replace("_", " "), "name_ru": AXIS_RU.get(ax, ax),
             "states": {c: {"name": s.get("name"), "criteria": s.get("criteria")} for c, s in v["states"].items()},
             "current": v["current"], "current_evidence": v.get("current_evidence", []), "source_refs": v.get("source_refs", [])} for ax, v in axes_src.items()}
(out / "states.yaml").write_text("# Вектор состояний NET (оси и состояния). Переходы — triggers.yaml (NET-E-06..E-11 + привязка legacy NET-E-*/X-* к осям), текущий вектор — state.json.\n" +
    dump({"version": "1.0", "artifact": "NET State Vector", "as_of": TODAY, "ticker": "NET", "source_artifact": src_note,
          "purpose": "Оси и состояния компании поверх реестра владельца от 17.09: legacy-триггеры NET-E-01..05 / X-01..03 сохранены и привязаны к осям (поле axis), переходы состояний — NET-E-06..E-11.",
          "semantics": d.get("source_policy") or {}, "sources": sources, "axes": axes}), encoding="utf-8")

# kpis.yaml
kp = []
for k in d["kpis"]["items"]:
    e = {"id": k["id"], "name": k["name"], "unit": k.get("unit"), "period": k.get("period"), "source": "SEC" if "sec.gov" in str(k.get("source", "")) else "IR",
         "thresholds": k.get("zones"), "last_value": k.get("current_value"), "last_date": k.get("as_of"), "source_url": k.get("source"), "verified": False}
    for opt in ("formula", "note", "disclosure_status", "value_type"):
        if opt in k: e[opt] = k[opt]
    if e["last_value"] is None: e["verified"] = None; e["note"] = (e.get("note") or "") + " Не раскрывается компанией (not_separately_disclosed) — не выдумывать (см. NET-E-05)."
    kp.append(e)
(out / "kpis.yaml").write_text("# KPI NET с порогами Green/Yellow/Red. История — state.json → kpi_observations.\n" +
    dump({"version": "1.0", "artifact": "NET KPI Dashboard", "as_of": TODAY, "ticker": "NET", "max_critical_kpis": 10, "source_artifact": src_note,
          "zone_semantics": d["kpis"].get("zone_semantics") or {"thresholds_provenance": "model_assumption"},
          "source_policy": {"primary": ["SEC", "Cloudflare Investor Relations"], "secondary": ["Yahoo Finance"],
                            "rule": "Last value без подтверждённого источника (verified: true) не используется для перехода состояния."},
          "critical_kpis": kp}), encoding="utf-8")

# mpc_inputs.yaml
(out / "mpc_inputs.yaml").write_text("# Входы MPC для NET: вектор экспозиций по драйверам и failure modes (Marginal_Portfolio_Contribution_Schema_v1.0).\n" +
    dump({"version": "1.0", "ticker": "NET", "artifact": "mpc_inputs", "as_of": TODAY, "source_artifact": src_note, **d["mpc_inputs"]}), encoding="utf-8")

# triggers.yaml — текстовые правки, чтобы сохранить комментарии и формат владельца
t = out / "triggers.yaml"; s = t.read_text(encoding="utf-8")
assert "step: vector" not in s and "NET-E-06" not in s
s = s.replace("  registry_updated: 2026-09-17\n", f"  registry_updated: {TODAY}  # 17.09: реестр владельца; 21.09: вектор состояний (states.yaml), legacy-триггеры привязаны к осям, добавлены NET-E-06..E-11\n", 1)
s = s.replace('    - { id: taiwan, kind: scenario, name: "Сценарий «Тайвань» (portfolio/_scenarios/taiwan.yaml)", ref: portfolio/_scenarios/taiwan.yaml }\n',
              '    - { id: taiwan, kind: scenario, name: "Сценарий «Тайвань» (portfolio/_scenarios/taiwan.yaml)", ref: portfolio/_scenarios/taiwan.yaml }\n'
              '    - { id: vector, kind: axis, name: "Вектор состояний по осям states.yaml (Revenue_Growth / Expansion_Retention / Contracted_Demand / Profitability_Cash / AI_Edge_Monetization) — независим от фазы" }\n', 1)
# привязка legacy-триггеров к осям (binding_guidance LLM; ID сохранены)
bind = {"NET-E-01": ("Revenue_Growth", ["NET-KPI-01"]), "NET-E-02": ("Revenue_Growth", ["NET-KPI-07"]), "NET-E-03": ("AI_Edge_Monetization", ["NET-KPI-08", "NET-KPI-09"]),
        "NET-E-04": ("Expansion_Retention", ["NET-KPI-02", "NET-KPI-10"]), "NET-E-05": ("AI_Edge_Monetization", ["NET-KPI-08", "NET-KPI-09"]),
        "NET-X-01": ("Revenue_Growth", ["NET-KPI-01"]), "NET-X-02": ("Revenue_Growth", ["NET-KPI-07"]), "NET-X-03": ("Expansion_Retention", ["NET-KPI-02"])}
for tid, (ax, kpis) in bind.items():
    key = f"  - id: {tid}\n    class: event\n    step: confirm\n"
    assert s.count(key) == 1, tid
    s = s.replace(key, key + f"    axis: {ax}\n    kpis: [{', '.join(kpis)}]\n", 1)
# новые переходы состояний
new = []
for i, p in enumerate(d["triggers"]["proposed_transitions_without_ids"], start=6):
    fr, to = p["transition"]["from"], p["transition"]["to"]
    new.append({"id": f"NET-E-{i:02d}", "class": "event", "step": "vector", "axis": p["axis"], "transition": {"from": fr, "to": to}, "level": p.get("level", "E2"),
                "kpis": p.get("kpis", []), "condition": p["condition"], "period": p.get("period"),
                "source": "Cloudflare 10-Q / earnings release (первичный источник по kpis.yaml)",
                "action": f"Зафиксировать переход {p['axis']} {fr}→{to} в state.json (state_transitions, scenario_state) и отправить Decision Request владельцу; инвестиционное действие не предопределено",
                "automation": None, "status": "planned", "fired": [],
                "notes": "ID присвоен дозором 21.09 (LLM дала переход без ID, чтобы не конфликтовать с реестром владельца)"})
block = "\n  # ---------- переходы вектора состояний (states.yaml), партия 3 от другой LLM, 21.09.2026 ----------\n" + "".join("  - " + dump(x).replace("\n", "\n    ").rstrip() + "\n" for x in new)
anchor = "  - id: NET-C-01\n"
assert s.count(anchor) == 1
s = s.replace(anchor, block + "\n" + anchor, 1)
t.write_text(s, encoding="utf-8"); tr = yaml.safe_load(s)
ids = [x["id"] for x in tr["triggers"]]; assert len(ids) == len(set(ids)) and "NET-E-11" in ids

# state.json — дополнить, не трогая существующее
j = out / "state.json"; st = json.loads(j.read_text(encoding="utf-8"))
assert "scenario_state" not in st
st["scenario_state"] = {ax: {"state": v["current"], "since": TODAY, "evidence": v.get("current_evidence", []),
                             "source": ", ".join(str(sources.get(r, r)) for r in v.get("source_refs", [])), "verified": False} for ax, v in axes_src.items()}
st.setdefault("state_transitions", []); st.setdefault("kpi_observations", []); st.setdefault("calc_runs", [])
st.setdefault("info_log", []).append({"timestamp": f"{TODAY}T07:10:00Z", "kind": "onboarding",
    "summary": "Модель компании NET v1.0 (партия 3) встроена в реестр владельца: вектор " + " + ".join(f"{a}={v['current']}" for a, v in axes_src.items()) + "; legacy NET-E/X привязаны к осям; добавлены NET-E-06..E-11; KPI не сверены"})
st["updated"] = f"{TODAY}T07:10:00Z"
j.write_text(json.dumps(st, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

# thesis.md — дописать раздел
th = out / "thesis.md"; ts = th.read_text(encoding="utf-8")
if "Вектор состояний" not in ts:
    th.write_text(ts.rstrip("\n") + f"""

## Вектор состояний (модель компании, партия 3, {TODAY})
Оси в `states.yaml`, KPI в `kpis.yaml`, входы MPC в `mpc_inputs.yaml`. Снимок LLM: {" + ".join(f"{a}={v['current']}" for a, v in axes_src.items())}.
Legacy-триггеры NET-E-01..05 и X-01..03 сохранены и привязаны к осям; переходы состояний — NET-E-06..E-11. Денежный KPI
Workers AI / edge (NET-KPI-08/09) компанией не раскрывается — не выдумывать (совпадает с NET-E-05).
""", encoding="utf-8")
print("NET merged: triggers", len(ids), "| new E-06..E-11 |", "axes", list(axes))
