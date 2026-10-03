"""Заход 11 (одобрен владельцем 04.10.2026): вселенная 18 бумаг (15 калиброванных + кандидаты CRWD / HPS.A / S, партии 14–15) в режиме
universe portfolio_compare 1.1.0 — веса считает оптимизатор на смеси (лимиты владельца v1.0/v1.1: потолки Conviction Overlay, сектор, топ-3,
общая причина, кэш по режиму, сценарные гейты V1, концентрация hard 70, 6…8 бумаг / мин. 3 %, тема AI_TOTAL ≤ база 0.5428), плюс оптимум под
каждым сценарием (BASE / TS / CW / Q, probability = 1, без гейтов). Варианты: current (веса 18.09), T_v1.0 (утверждённые целевые веса,
DR-2026-10-03-01), U18 (вселенная 18 — что добавить). Подготовка: файлы-смеси для трёх новых бумаг (portfolio_paths mixture_export, тот же тег
и разбиение path_id → совместимы с 15), потолки Conviction Overlay по BASE-нормативам (формула захода 6), сектора из _candidates.
Результат: portfolio/_compare/<дата>.json + latest.json, notes/compare-<дата>.md (через portfolio_compare), _opt_run11.json.
Время: 1 + 4 вызова оптимизатора ≈ 20–25 мин каждый ≈ 1.5–2 ч. Запуск: python _portfolio_run11.py"""
import datetime
import json
import time
from pathlib import Path

import yaml

import _portfolio_run7_lib as L

S = Path(__file__).parent; WS = L.WS; C = L.C
NEW = ["CRWD", "HPS.A", "S"]
assert all(tk in L.NORM for tk in NEW), "нормативные прогоны кандидатов не найдены в _norm_runs_joint11.json"
date = datetime.date.today().isoformat()
# 1) файлы-смеси для новых бумаг (тот же тег/разбиение path_id)
mixp = S / "_mixture_files_p10_p07_p175.json"; MIX = json.load(open(mixp, encoding="utf-8"))
need = [tk for tk in NEW if tk not in MIX]
if need:
    scen = [{"id": "BASE", "paths_files": {tk: L.pf("BASE", tk) for tk in need}}] + [{"id": sid, "probability": pr, "paths_files": {tk: L.pf(sid, tk) for tk in need}} for sid, pr in L.P.items()]
    r = L.post({"model": "portfolio_paths", "inputs": {"mode": "mixture_export", "scenarios": scen, "out_dir": C, "tag": "mix-p10-p07-p175"}, "seed": 0, "save": True})
    o = r["outputs"]; print(f"экспорт смеси для {need}: {r['run_id']} ranges {o['ranges']}", flush=True)
    MIX.update(o["paths_files"]); json.dump(MIX, open(mixp, "w", encoding="utf-8"), indent=1)
FILES = {tk: MIX[tk] for tk in L.NORM}
# 2) потолки Conviction Overlay для новых (формула захода 6: standard, buffer × hard cap по plausible drawdown)
p = yaml.safe_load((WS / "portfolio/_portfolio.yaml").read_text(encoding="utf-8")); cons = p["constraints"]; ap = cons["conviction_overlay_v1_0"]["approved_params"]; conv = set(cons["conviction_overlay_v1_0"].get("active_conviction_tags") or [])
caps = dict(L.caps)
for tk in NEW:
    b = json.load(open(WS / "portfolio/_runs" / f"{L.NORM[tk]}.json", encoding="utf-8"))["outputs"]["base"]["downside"]
    dd = min(max(max(abs(b["expected_shortfall_5pct_5Y"]), abs(b["max_drawdown_5Y_quantiles"]["0.25"])), ap["plausible_drawdown_floor"]), ap["plausible_drawdown_ceiling"])
    hard = (min(max(ap["L_max_conviction"] / dd, ap["conviction_hard_cap_floor"]), ap["conviction_hard_cap_ceiling"]) if tk in conv else min(max(ap["L_max_standard"] / dd, ap["standard_hard_cap_floor"]), ap["standard_hard_cap_ceiling"]))
    caps[tk] = round(ap["target_safety_buffer"] * hard, 4)
sectors = dict(L.sectors); sectors.update({"CRWD": "SOFTWARE", "HPS.A": "ELECTRIFICATION", "S": "SOFTWARE"})     # как в _candidates.yaml (sector_id_provenance: provisional)
print("потолки новых:", {tk: caps[tk] for tk in NEW}, "| сектора:", {tk: sectors[tk] for tk in NEW}, flush=True)
# 3) входы сравнителя (как _portfolio_compare_run.py) + шаблон оптимизатора на 18
TH = json.load(open(S / "_theme_lookthrough.json", encoding="utf-8")); R_B = json.load(open(S / "_conditional_runs_partB.json", encoding="utf-8"))
conc = L.l11.get("scenario_concentration") or {}; card = L.l11["cardinality"]
sc = {"p_min": L.sc11["p_min"], "es5_min": L.sc11["es5_min"], "p_loss_gt_30_max": L.sc11["p_loss_gt_30_max"], "scenario_concentration_max": conc.get("hard_max", L.sc11["scenario_concentration_max"]), "scenarios": L.scen_files, "base_paths_files": L.base_files}
limits = {**L.limits, "cardinality": {"positions_min": card["positions_min"], "positions_max": card["positions_max"], "min_position_weight": card["min_position_weight"], "excludes": card["excludes"]},
          "theme_policy": {"policy_id": "AI_THEME_NOT_INCREASE_V1", "aggregate_id": "AI_TOTAL", "shares": {tk: v for tk, v in TH["shares"].items() if tk in L.NORM}, "baseline_value": TH["baseline_2026_09_21"], "tolerance": 1e-6, "baseline_status": "MATERIALIZED"}}
fixed = {k: float(v) for k, v in {"GLD": 0.022, "UFO": 0.0017}.items()}
fixed_opt = {tk: w for tk, w in L.wcur.items() if tk not in L.NORM}
tw = p["portfolio"]["target_weights"]; t_w = {w["ticker"]: float(w["weight"]) for w in tw["weights"] if w["ticker"] in L.NORM}
variants = [{"id": "current", "weights": {tk: x for tk, x in L.wcur.items() if tk in L.NORM}, "dry_powder": round(1.0 - sum(L.wcur.values()), 6), "note": "текущие веса (цены 18.09)"},
            {"id": "T_v1.0", "weights": t_w, "dry_powder": float(tw["dry_powder_weight"]), "note": "целевые веса v1.0 (DR-2026-10-03-01, вариант C захода 9)"},
            {"id": "U18", "universe": sorted(L.NORM), "note": "вселенная 18 бумаг (15 + CRWD / HPS.A / S) → оптимизатор"}]
for v in variants:
    if "weights" in v:
        v["dry_powder"] = round(1.0 - sum(v["weights"].values()) - sum(fixed.values()), 6)
cond = [{"scenario_id": k.split("|")[0], "phase_id": k.split("|")[1], "paths_files": {tk: c["paths_file"] for tk, c in b["companies"].items() if c.get("paths_file")}} for k, b in R_B.items() if "|" in k]
inp = {"variants": variants, "reference_id": "T_v1.0", "scenarios": [{"id": "BASE", "paths_files": L.base_files}] + L.scen_files, "dry_powder_return_annual": 0.04, "fixed_weights": fixed,
       "theme": {"aggregate_id": "AI_TOTAL", "shares": TH["shares"], "baseline_value": TH["baseline_2026_09_21"], "policy_id": "AI_THEME_NOT_INCREASE_V1"},
       "limits_check": {"limits": limits, "per_name_caps": caps, "roles": {}, "sectors": sectors, "common_cause": L.cc, "regime": L.regime, "scenario_constraints": sc}, "conditional": cond,
       "optimizer_inputs": {"paths_files": FILES, "weights_current": L.wcur, "fixed_weights": fixed_opt, "dry_powder_current": L.cash_w, "dry_powder_return_annual": 0.04, "regime": L.regime, "limits": limits,
                            "per_name_caps": caps, "roles": {}, "sectors": sectors, "common_cause": L.cc, "objective_tolerance_pp": 0.5, "scenario_constraints": sc, "starts": ["current", "equal", "empty", "given"],
                            "start_weights": t_w, "start_dry_powder": float(tw["dry_powder_weight"])},
       "universe_options": {"per_scenario": True, "conditional": False, "search": {"random_starts": 0, "basin_kicks": 0}}}
t0 = time.time()
r = L.post({"model": "portfolio_compare", "inputs": inp, "seed": 0, "save": True}); o = r["outputs"]
print(f"compare run {r['run_id']} за {time.time() - t0:.0f}s | ranking {o['ranking']['order'] if o.get('ranking') else None}", flush=True)
out_dir = WS / "portfolio/_compare"; out_dir.mkdir(exist_ok=True)
for name in (f"{date}.json", "latest.json"):
    json.dump({"run_id": r["run_id"], "date": date, **o}, open(out_dir / name, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
json.dump({"run_id": r["run_id"], "caps_new": {tk: caps[tk] for tk in NEW}, "mixture_files": {tk: MIX[tk] for tk in NEW}, "variants": {k: {"weights": v["weights"], "dry_powder": v["dry_powder"], "positions_count": v["positions_count"], "mixture_Y5": v["mixture"]["Y5"] if v["mixture"] else None,
                                                                                                                                             "violations": v["violations"], "optimized": v.get("optimized")} for k, v in o["variants"].items()}}, open(S / "_opt_run11.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
u = o["variants"]["U18"]; opt = u["optimized"]
print("U18 смесь:", {t: round(100 * w, 1) for t, w in u["weights"].items()}, "кэш", round(100 * u["dry_powder"], 1), "| Y5", {k: round(v, 4) for k, v in u["mixture"]["Y5"].items() if k in ("median_CAGR", "expected_shortfall_5pct", "P_loss_gt_30pct")}, "| нарушений", len(u["violations"] or []), flush=True)
for sid, x in opt["by_scenario"].items():
    print(f"  под {sid}:", ({t: round(100 * w, 1) for t, w in x["weights"].items()} if "weights" in x else x), flush=True)
# заметка для владельца и агента
V = o["variants"]; ids = list(V); sids = [x["id"] for x in o["scenarios"]]; tks = sorted({t for v in V.values() for t in v["weights"]})


def f3(m):
    return f"{100 * m['median_CAGR']:+.1f} / {100 * m['expected_shortfall_5pct']:+.1f} / {100 * m['P_loss_gt_30pct']:.1f}"


NL = "\n"
lines = [f"# Заход 11 — вселенная 18 бумаг (portfolio_compare 1.1.0 universe), {date}, run {r['run_id']}", "",
         "Варианты: current (веса 18.09), T_v1.0 (целевые веса, DR-2026-10-03-01), U18 (15 калиброванных + CRWD / HPS.A / S → оптимизатор на смеси; лимиты владельца, "
         "сценарные гейты V1, 6…8 бумаг / мин. 3 %, тема AI_TOTAL ≤ база). Оптимумы под сценариями — probability = 1, без гейтов; 0 = не покупать / продать "
         "под сценарием. Позиции вне вселенной считаются проданными в кэш. Все числа — derived_fact из путей; decision: none.", "",
         "## 1. Веса, % NAV", "", "| бумага | " + " | ".join(ids) + " |", "|---|" + "---|" * len(ids)]
for t in tks:
    lines.append(f"| {t} | " + " | ".join(f"{100 * V[i]['weights'].get(t, 0):.1f}" for i in ids) + " |")
lines += ["| кэш | " + " | ".join(f"{100 * V[i]['dry_powder']:.1f}" for i in ids) + " |", "| позиций | " + " | ".join(str(V[i]["positions_count"]) for i in ids) + " |",
          "| тема ИИ | " + " | ".join(f"{100 * V[i]['theme']['value']:.1f} %" for i in ids) + " |", "| нарушений лимитов | " + " | ".join(str(len(V[i]["violations"] or [])) for i in ids) + " |",
          "", "## 2. Картина Y5: медиана CAGR / ES5 / P(loss>30 %), %", "", "| сценарий | " + " | ".join(ids) + " |", "|---|" + "---|" * len(ids)]
for sid in sids:
    lines.append(f"| {sid} | " + " | ".join(f3(V[i]["by_scenario_Y5"][sid]) for i in ids) + " |")
lines.append("| **смесь** | " + " | ".join(f"**{f3(V[i]['mixture']['Y5'])}**" for i in ids) + " |")
cols = list(next(iter(opt["weights_by_scenario"].values())).keys())
lines += ["", "## 3. U18: оптимальные веса под сценариями, % NAV (0 = не покупать / продать)", "", "| бумага | " + " | ".join(cols) + " |", "|---|" + "---|" * len(cols)]
for t in opt["universe"]:
    if any(opt["weights_by_scenario"][t][c] > 0 for c in cols):
        lines.append(f"| {t} | " + " | ".join(f"{100 * opt['weights_by_scenario'][t][c]:.1f}" for c in cols) + " |")
lines += ["| кэш | " + " | ".join(f"{100 * opt['dry_powder_by_scenario'][c]:.1f}" for c in cols) + " |",
          "| медиана / ES5 Y5 | " + " | ".join((f"{100 * x['median_CAGR_5Y']:+.1f} / {100 * x['ES5']:+.1f}" if "median_CAGR_5Y" in x else "—") for x in [opt["mixture"]] + [opt["by_scenario"].get(c, {}) for c in cols[1:]]) + " |",
          "", "Всегда 0 во вселенной: " + ", ".join(t for t in opt["universe"] if all(opt["weights_by_scenario"][t][c] == 0 for c in cols)) + ".",
          "", f"## 4. Ранжирование допустимых: {' > '.join(o['ranking']['order']) if o.get('ranking') else '—'}; вне ранжирования: {o['ranking']['excluded_infeasible'] if o.get('ranking') else '—'}", ""]
(WS / "notes" / f"run11-universe18-{date}.md").write_text(NL.join(lines) + NL, encoding="utf-8")
print("DONE", flush=True)
