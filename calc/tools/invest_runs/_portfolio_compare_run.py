"""Сравнение вариантов состава одним запуском (portfolio_compare 1.0.0): варианты — из portfolio/_compare/variants.yaml (текущие веса, оптимумы
прогонов по run_id, ручные варианты владельца), сценарии — BASE + TS/CW/Q с вероятностями владельца, условные фазы части B, тема AI_TOTAL,
проверка лимитов (approved_limits_v1_0/v1_1, потолки захода 6, сценарные гейты V1, концентрация hard 70, cardinality, тема).
Выход: portfolio/_compare/<дата>.json (+ latest.json) и notes/compare-<дата>.md (таблица для владельца и агента). Расчёт — секунды–минуты.
Запуск: python _portfolio_compare_run.py [--date YYYY-MM-DD]"""
import datetime
import json
import sys
import textwrap
from pathlib import Path

import yaml

import _portfolio_run7_lib as L

S = Path(__file__).parent; WS = L.WS
cfg = yaml.safe_load((WS / "portfolio/_compare/variants.yaml").read_text(encoding="utf-8"))
date = sys.argv[sys.argv.index("--date") + 1] if "--date" in sys.argv else datetime.date.today().isoformat()
fixed = {k: float(v) for k, v in (cfg.get("fixed_weights") or {}).items()}
variants = []
for v in cfg["variants"]:
    if v.get("source") == "machine_outputs.current_weights":
        w = {tk: x for tk, x in L.wcur.items() if tk in L.NORM}; dp = round(1.0 - sum(L.wcur.values()), 6)
        variants.append({"id": v["id"], "weights": w, "dry_powder": dp, "note": v.get("note", "текущие веса")})
    elif v.get("optimum_run"):
        r = json.load(open(WS / "portfolio/_runs" / f"{v['optimum_run']}.json", encoding="utf-8"))["outputs"]
        w = {tk: x for tk, x in r["proposed_weights"].items() if tk in L.NORM and x > 0}
        variants.append({"id": v["id"], "weights": w, "dry_powder": float(r["dry_powder_weight"]), "note": f"{v.get('note', '')} [{v['optimum_run'][-6:]}]"})
    else:
        variants.append({"id": v["id"], "weights": {k: float(x) for k, x in v["weights"].items()}, "dry_powder": float(v["dry_powder"]), "note": v.get("note")})
for v in variants:                                                      # нормировка: веса + dp + fixed = 1 (кэш досчитывается)
    tot = sum(v["weights"].values()) + v["dry_powder"] + sum(fixed.values())
    if abs(tot - 1.0) > 1e-4:
        v["dry_powder"] = round(1.0 - sum(v["weights"].values()) - sum(fixed.values()), 6)
TH = json.load(open(S / "_theme_lookthrough.json", encoding="utf-8")); R_B = json.load(open(S / "_conditional_runs_partB.json", encoding="utf-8"))
cond = [{"scenario_id": k.split("|")[0], "phase_id": k.split("|")[1], "paths_files": {tk: c["paths_file"] for tk, c in b["companies"].items()}} for k, b in R_B.items() if "|" in k]
conc = L.l11.get("scenario_concentration") or {}; card = L.l11["cardinality"]
sc = {"p_min": L.sc11["p_min"], "es5_min": L.sc11["es5_min"], "p_loss_gt_30_max": L.sc11["p_loss_gt_30_max"], "scenario_concentration_max": conc.get("hard_max", L.sc11["scenario_concentration_max"]), "scenarios": L.scen_files, "base_paths_files": L.base_files}
limits = {**L.limits, "cardinality": {"positions_min": card["positions_min"], "positions_max": card["positions_max"], "min_position_weight": card["min_position_weight"], "excludes": card["excludes"]},
          "theme_policy": {"policy_id": "AI_THEME_NOT_INCREASE_V1", "aggregate_id": "AI_TOTAL", "shares": {tk: v for tk, v in TH["shares"].items() if tk in L.NORM}, "baseline_value": TH["baseline_2026_09_21"], "tolerance": 1e-6, "baseline_status": "MATERIALIZED"}}
inp = {"variants": variants, "reference_id": cfg.get("reference_id", "current"), "scenarios": [{"id": "BASE", "paths_files": L.base_files}] + L.scen_files, "dry_powder_return_annual": 0.04, "fixed_weights": fixed,
       "theme": {"aggregate_id": "AI_TOTAL", "shares": TH["shares"], "baseline_value": TH["baseline_2026_09_21"], "policy_id": "AI_THEME_NOT_INCREASE_V1"},
       "limits_check": {"limits": limits, "per_name_caps": L.caps, "roles": {}, "sectors": L.sectors, "common_cause": L.cc, "regime": L.regime, "scenario_constraints": sc}, "conditional": cond}
r = L.post({"model": "portfolio_compare", "inputs": inp, "seed": 0, "save": True}); o = r["outputs"]
out_dir = WS / "portfolio/_compare"; out_dir.mkdir(exist_ok=True)
for name in (f"{date}.json", "latest.json"):
    json.dump({"run_id": r["run_id"], "date": date, **o}, open(out_dir / name, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
ids = [v["id"] for v in variants]; V = o["variants"]; sids = [s["id"] for s in o["scenarios"]]
tks = sorted({t for v in V.values() for t in v["weights"]})


def f3(v):
    return f"{100 * v['median_CAGR']:+.1f} / {100 * v['expected_shortfall_5pct']:+.1f} / {100 * v['P_loss_gt_30pct']:.1f}"


lines = [f"# Сравнение вариантов состава портфеля — {date} (portfolio_compare {o['model_version']}, run {r['run_id']})\n",
         textwrap.fill(f"Варианты из portfolio/_compare/variants.yaml; сценарии BASE + TS 0.10 / CW 0.07 / Q 0.175 (решения владельца); пути 500k на общих path_id; смесь §6; лимиты approved_limits_v1_0/v1_1 (потолки Conviction Overlay, сценарные гейты V1, концентрация hard 70 %, 6…8 бумаг / мин. 3 %, тема AI_TOTAL ≤ база 21.09 = {TH['baseline_2026_09_21']:.4f}). Все числа — derived_fact из путей; ничего не решается (decision: none).", 118), ""]
lines.append("## 1. Веса, % NAV\n"); lines.append("| бумага | " + " | ".join(ids) + " |"); lines.append("|---|" + "---|" * len(ids))
for t in tks:
    lines.append(f"| {t} | " + " | ".join(f"{100 * V[i]['weights'].get(t, 0):.1f}" for i in ids) + " |")
lines.append("| кэш | " + " | ".join(f"{100 * V[i]['dry_powder']:.1f}" for i in ids) + " |")
lines.append("| позиций | " + " | ".join(str(V[i]["positions_count"]) for i in ids) + " |")
lines.append("| тема ИИ (look-through) | " + " | ".join(f"{100 * V[i]['theme']['value']:.1f} %" for i in ids) + " |")
lines.append("| нарушений лимитов | " + " | ".join((str(len(V[i]["violations"])) if V[i]["violations"] is not None else "—") for i in ids) + " |")
lines.append("\n## 2. Картина Y5: медиана CAGR / ES5 / P(loss>30 %), %\n"); lines.append("| сценарий | " + " | ".join(ids) + " |"); lines.append("|---|" + "---|" * len(ids))
for sid in sids:
    lines.append(f"| {sid} | " + " | ".join(f3(V[i]["by_scenario_Y5"][sid]) for i in ids) + " |")
if all(V[i]["mixture"] for i in ids):
    lines.append("| **смесь** | " + " | ".join(f"**{f3(V[i]['mixture']['Y5'])}**" for i in ids) + " |")
    lines.append("| концентрация сценариев | " + " | ".join((f"{100 * V[i]['scenario_concentration']['value']:.0f} %" if V[i]["scenario_concentration"]["value"] is not None else "н/п") for i in ids) + " |")
if any(V[i].get("conditional_phases_Y5") for i in ids):
    lines.append("\n## 3. Условные фазы (probability = 1): медиана / ES5, %\n"); lines.append("| фаза | " + " | ".join(ids) + " |"); lines.append("|---|" + "---|" * len(ids))
    for key in V[ids[0]]["conditional_phases_Y5"]:
        lines.append(f"| {key.replace('|', ' / ')} | " + " | ".join((f"{100 * V[i]['conditional_phases_Y5'][key]['median_CAGR']:+.1f} / {100 * V[i]['conditional_phases_Y5'][key]['expected_shortfall_5pct']:+.1f}" if "median_CAGR" in V[i]["conditional_phases_Y5"][key] else "—") for i in ids) + " |")
lines.append("\n## 4. Нарушения лимитов владельца (разрыв ≠ приказ)\n")
for i in ids:
    vi = V[i]["violations"]
    if vi is None:
        lines.append(f"- {i}: проверка не выполнена")
    elif not vi:
        lines.append(f"- {i}: нет")
    else:
        lines.append(f"- {i}: " + "; ".join((f"{x['constraint']} {x['value']:.3f} vs {x['bound']}" if isinstance(x.get("value"), (int, float)) else str(x["constraint"])) for x in vi))
if o.get("ranking"):
    lines.append(f"\n## 5. Ранжирование допустимых (лексикографически): {' > '.join(o['ranking']['order'])}; вне ранжирования (нарушения): {o['ranking']['excluded_infeasible'] or 'нет'}\n")
(WS / "notes" / f"compare-{date}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"run {r['run_id']} | вариантов {len(ids)} | ranking {o['ranking']['order'] if o.get('ranking') else None} | notes/compare-{date}.md", flush=True)
