"""Встраивание модели компании в СУЩЕСТВУЮЩИЙ реестр владельца (NET — партия 3, ETN — партия 4): states/kpis/mpc_inputs — новые файлы;
triggers.yaml — шаг маршрута vector, привязка legacy -E-/-X- к осям (binding LLM), новые переходы <TK>-E-NN из proposed_transitions_without_ids;
state.json — scenario_state и пр.; thesis.md — дописать раздел. Существующие записи не менять.
Использование: python _apply_merge.py TICKER папка "share_url" company '{"TK-E-01": ["Axis", ["KPI-01"]], ...}' next_id_start
Перед запуском: docker cp triggers.yaml/state.json/thesis.md из workspace в portfolio/<папка>/."""
import ast, json, re, sys
from pathlib import Path
import yaml
# словарь AXIS_RU берём из _apply_batch.py без импорта (тот модуль исполняет argv-логику на верхнем уровне)
AXIS_RU = ast.literal_eval(re.search(r"AXIS_RU = (\{.*?\n\})", Path("_apply_batch.py").read_text(encoding="utf-8"), flags=re.S).group(1))

TK, FOLDER, SHARE, COMPANY, BIND_JSON, NEXT = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], int(sys.argv[6])
BIND = json.loads(BIND_JSON)
D = Path("C:/Users/alexe/Downloads"); TODAY = "2026-09-21"
Q = json.load(open("_quotes_2026-09-20.json", encoding="utf-8"))
def dump(o): return yaml.safe_dump(o, allow_unicode=True, sort_keys=False, width=120)

d = yaml.safe_load((D / f"{TK}_company_state_v1.0.yaml").read_text(encoding="utf-8"))
out = Path("portfolio") / FOLDER; sources = d.get("sources", {})
src_note = f"inbox/received/{TK}_company_state_v1.0.yaml (другая LLM, {TODAY}, share {SHARE})"
axes_src = d["states"]["axes"]
kp_src = d["kpis"]["items"]; zone_sem = d["kpis"].get("zone_semantics")
tr_src = d["triggers"]

axes = {ax: {"name": ax.replace("_", " "), "name_ru": AXIS_RU.get(ax, ax),
             "states": {c: {"name": s.get("name"), "criteria": s.get("criteria")} for c, s in v["states"].items()},
             "current": v["current"], "current_evidence": v.get("current_evidence", []), "source_refs": v.get("source_refs", [])} for ax, v in axes_src.items()}
for ax, v in axes_src.items():
    for opt in ("current_note", "note"):
        if opt in v: axes[ax][opt] = v[opt]
new_ids = [f"{TK}-E-{i:02d}" for i in range(NEXT, NEXT + len(tr_src["proposed_transitions_without_ids"]))]
(out / "states.yaml").write_text(f"# Вектор состояний {TK} (оси и состояния). Переходы — triggers.yaml ({new_ids[0]}..{new_ids[-1]} + привязка legacy {TK}-E-*/X-* к осям), текущий вектор — state.json.\n" +
    dump({"version": "1.0", "artifact": f"{TK} State Vector", "as_of": TODAY, "ticker": TK, "source_artifact": src_note,
          "purpose": f"Оси и состояния компании поверх реестра владельца от 17.09: legacy-триггеры сохранены и привязаны к осям (поле axis), переходы состояний — {new_ids[0]}..{new_ids[-1]}.",
          "semantics": d.get("source_policy") or {}, "sources": sources, "axes": axes}), encoding="utf-8")

kp = []
for k in kp_src:
    e = {"id": k["id"], "name": k["name"], "unit": k.get("unit"), "period": k.get("period"), "source": "SEC" if "sec.gov" in str(k.get("source", "")) else "IR",
         "thresholds": k.get("zones"), "last_value": k.get("current_value"), "last_date": k.get("as_of"), "source_url": k.get("source"), "verified": False}
    for opt in ("formula", "note", "disclosure_status", "value_type", "source_channel", "sec_mirror", "ir_document"):
        if opt in k: e[opt] = k[opt]
    if e["last_value"] is None: e["verified"] = None; e["note"] = (e.get("note") or "") + " Не раскрывается компанией — не выдумывать."
    kp.append(e)
(out / "kpis.yaml").write_text(f"# KPI {TK} с порогами Green/Yellow/Red. История — state.json → kpi_observations.\n" +
    dump({"version": "1.0", "artifact": f"{TK} KPI Dashboard", "as_of": TODAY, "ticker": TK, "max_critical_kpis": 10, "source_artifact": src_note,
          "zone_semantics": zone_sem or {"thresholds_provenance": "model_assumption"},
          "source_policy": {"primary": ["SEC", f"{COMPANY} Investor Relations"], "secondary": ["Yahoo Finance"],
                            "rule": "Last value без подтверждённого источника (verified: true) не используется для перехода состояния."},
          "critical_kpis": kp}), encoding="utf-8")

(out / "mpc_inputs.yaml").write_text(f"# Входы MPC для {TK}: вектор экспозиций по драйверам и failure modes (Marginal_Portfolio_Contribution_Schema_v1.0).\n" +
    dump({"version": "1.0", "ticker": TK, "artifact": "mpc_inputs", "as_of": TODAY, "source_artifact": src_note, **d["mpc_inputs"]}), encoding="utf-8")

t = out / "triggers.yaml"; s = t.read_text(encoding="utf-8")
assert "step: vector" not in s and new_ids[0] not in s
assert s.count("  registry_updated: 2026-09-17\n") == 1
s = s.replace("  registry_updated: 2026-09-17\n", f"  registry_updated: {TODAY}  # 17.09: реестр владельца; 21.09: вектор состояний (states.yaml), legacy-триггеры привязаны к осям, добавлены {new_ids[0]}..{new_ids[-1]}\n", 1)
tw = '    - { id: taiwan, kind: scenario, name: "Сценарий «Тайвань» (portfolio/_scenarios/taiwan.yaml)", ref: portfolio/_scenarios/taiwan.yaml }\n'
assert s.count(tw) == 1
s = s.replace(tw, tw + f'    - {{ id: vector, kind: axis, name: "Вектор состояний по осям states.yaml ({" / ".join(axes)}) — независим от фазы" }}\n', 1)
for tid, (ax, kpis) in BIND.items():
    key = f"  - id: {tid}\n    class: event\n    step: confirm\n"
    assert s.count(key) == 1, tid
    s = s.replace(key, key + f"    axis: {ax}\n    kpis: [{', '.join(kpis)}]\n", 1)
new = []
for nid, p in zip(new_ids, tr_src["proposed_transitions_without_ids"]):
    fr, to = p["transition"]["from"], p["transition"]["to"]
    new.append({"id": nid, "class": "event", "step": "vector", "axis": p["axis"], "transition": {"from": fr, "to": to}, "level": p.get("level", "E2"),
                "kpis": p.get("kpis", []), "condition": p["condition"], "period": p.get("period"),
                "source": f"{COMPANY} 10-Q / earnings release (первичный источник по kpis.yaml)",
                "action": f"Зафиксировать переход {p['axis']} {fr}→{to} в state.json (state_transitions, scenario_state) и отправить Decision Request владельцу; инвестиционное действие не предопределено",
                "automation": None, "status": "planned", "fired": [],
                "notes": "ID присвоен дозором 21.09 (LLM дала переход без ID, чтобы не конфликтовать с реестром владельца)"})
block = f"\n  # ---------- переходы вектора состояний (states.yaml), от другой LLM, {TODAY} ----------\n" + "".join("  - " + dump(x).replace("\n", "\n    ").rstrip() + "\n" for x in new)
anchor = f"  - id: {TK}-C-01\n"
assert s.count(anchor) == 1
s = s.replace(anchor, block + "\n" + anchor, 1)
t.write_text(s, encoding="utf-8"); tr = yaml.safe_load(s)
ids = [x["id"] for x in tr["triggers"]]; assert len(ids) == len(set(ids)) and new_ids[-1] in ids

j = out / "state.json"; st = json.loads(j.read_text(encoding="utf-8"))
assert "scenario_state" not in st
vec = " + ".join(f"{a}={v['current']}" for a, v in axes_src.items())
st["scenario_state"] = {ax: {"state": v["current"], "since": TODAY, "evidence": v.get("current_evidence", []),
                             "source": ", ".join(str(sources.get(r, r)) for r in v.get("source_refs", [])), "verified": False} for ax, v in axes_src.items()}
st.setdefault("state_transitions", []); st.setdefault("kpi_observations", []); st.setdefault("calc_runs", [])
st.setdefault("info_log", []).append({"timestamp": f"{TODAY}T08:10:00Z", "kind": "onboarding",
    "summary": f"Модель компании {TK} v1.0 встроена в реестр владельца: вектор {vec}; legacy -E/-X привязаны к осям; добавлены {new_ids[0]}..{new_ids[-1]}; KPI не сверены"})
st["updated"] = f"{TODAY}T08:10:00Z"
j.write_text(json.dumps(st, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

th = out / "thesis.md"; ts = th.read_text(encoding="utf-8")
if "Вектор состояний" not in ts:
    th.write_text(ts.rstrip("\n") + f"""

## Вектор состояний (модель компании, {TODAY})
Оси в `states.yaml`, KPI в `kpis.yaml`, входы MPC в `mpc_inputs.yaml`. Снимок LLM: {vec}.
Legacy-триггеры реестра сохранены и привязаны к осям; переходы состояний — {new_ids[0]}..{new_ids[-1]}.
""", encoding="utf-8")
print(f"{TK} merged: triggers {len(ids)} | new {new_ids[0]}..{new_ids[-1]} | axes {list(axes)} | вектор {vec}")
