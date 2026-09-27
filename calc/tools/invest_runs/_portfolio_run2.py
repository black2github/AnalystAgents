"""Первая валидация портфеля (24.09, заход 2: движок 2.3.2, собственные розыгрыши по тикеру): сборка входов из реестров и запуск через сайдкар (save=true) — portfolio_paths (текущие веса) и
portfolio_optimizer (стадия A). Развилки владельца: некалиброванные позиции фиксированы на текущих весах (плоская доходность),
только сценарий BASE, без проекции на счета. Потолки на бумагу — Conviction Overlay по MC (plausible_dd = max(|ES5|, |Q25 maxdd|),
clamp 0.25–0.90; hard = clamp(L_max/dd, floor, ceiling); target = 0.75 × hard; L_max 10 % / 25 % conviction — approved_params)."""
import json
import sys
import urllib.request
from pathlib import Path

import yaml

WS = Path("C:/openclaw-lab/data/workspace-invest"); URL = "http://127.0.0.1:18791/run"
RUNS = {"SPCX": "20260924T073336Z-company_mc-e55d7d", "NBIS": "20260924T073647Z-company_mc-0daf30", "NVDA": "20260924T073919Z-company_mc-d5afc5",
        "HOOD": "20260924T074150Z-company_mc-038894", "RKLB": "20260924T074358Z-company_mc-224958", "LLY": "20260924T074630Z-company_mc-89318c",
        "META": "20260924T074844Z-company_mc-965cab", "ASML": "20260924T075104Z-company_mc-aa8132"}
SEV = {"critical": 1.0, "high": 0.75, "medium": 0.5, "low": 0.25}


def post(payload):
    req = urllib.request.Request(URL, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=3600))


p = yaml.safe_load((WS / "portfolio/_portfolio.yaml").read_text(encoding="utf-8"))
mo = p["machine_outputs"]; wcur = mo["current_weights"]; regime = mo["regime"]
positions = p["portfolio"]["positions"]
sectors = {x["ticker"]: x.get("sector_id") for x in positions}
cons = p["constraints"]; ap = cons["conviction_overlay_v1_0"]["approved_params"]; lim = cons["approved_limits_v1_0"]
conv = set(cons["conviction_overlay_v1_0"].get("active_conviction_tags") or [])
cash_w = round(1.0 - sum(wcur.values()), 4)
# потолки на бумагу по MC (только калиброванные — остальные фиксированы)
caps = {}; dd_used = {}
for tk, rid in RUNS.items():
    b = json.load(open(WS / "portfolio/_runs" / f"{rid}.json", encoding="utf-8"))["outputs"]["base"]["downside"]
    dd = max(abs(b["expected_shortfall_5pct_5Y"]), abs(b["max_drawdown_5Y_quantiles"]["0.25"]))
    dd = min(max(dd, ap["plausible_drawdown_floor"]), ap["plausible_drawdown_ceiling"])
    if tk in conv:
        hard = min(max(ap["L_max_conviction"] / dd, ap["conviction_hard_cap_floor"]), ap["conviction_hard_cap_ceiling"])
    else:
        hard = min(max(ap["L_max_standard"] / dd, ap["standard_hard_cap_floor"]), ap["standard_hard_cap_ceiling"])
    caps[tk] = round(ap["target_safety_buffer"] * hard, 4); dd_used[tk] = round(dd, 3)
# общая причина: severity-взвешенные факторы по failure modes (все модели, включая фиксированные позиции)
cc = {}
for d in sorted((WS / "portfolio").glob("*/mpc_inputs.yaml")):
    m = yaml.safe_load(d.read_text(encoding="utf-8")); tk = (m.get("ticker") or d.parent.name).upper()
    if tk == "SPACEX": tk = "SPCX"
    for fm in m.get("failure_modes", []):
        c = fm.get("common_cause_id"); s = str(fm.get("severity", "")).lower()
        if c:
            cc.setdefault(c, {}); cc[c][tk] = max(cc[c].get(tk, 0.0), SEV.get(s, 0.5))
fixed = {tk: w for tk, w in wcur.items() if tk not in RUNS}
paths_files = {tk: f"/data/workspace-invest/portfolio/_runs/{rid}-paths.npz" for tk, rid in RUNS.items()}
limits = {"sector_max": lim["sector_max"], "top3_aggregate_max": lim["top3_aggregate_max"], "common_cause_effective_max": lim["common_cause_effective_max"],
          "roles": lim["roles"], "dry_powder": lim["dry_powder"], "risk_5y": lim["risk_5y"]}
print("режим", regime, "| кэш", cash_w, "| fixed", round(sum(fixed.values()), 4), fixed)
print("потолки (target_cap по MC):", caps, "| plausible_dd:", dd_used)
# 1) текущий портфель по совместным путям (только калиброванные 88 % + кэш, перенормировка — диагностика)
wc = {tk: wcur[tk] for tk in RUNS}; s = sum(wc.values()) + cash_w
r1 = post({"model": "portfolio_paths", "inputs": {"paths_files": paths_files, "weights": {tk: w / s for tk, w in wc.items()}, "dry_powder_weight": cash_w / s, "dry_powder_return_annual": 0.04}, "seed": 0, "save": True})
o = r1["outputs"]; y5 = o["horizons"]["Y5"]
print(f"portfolio_paths (текущие веса, 88 % NAV перенормированы) run {r1['run_id']}: медиана CAGR 3/5/8 {o['horizons']['Y3']['median_CAGR']:.3f}/{y5['median_CAGR']:.3f}/{o['horizons']['Y8']['median_CAGR']:.3f} | P(loss>30) {y5['P_loss_gt_30pct']:.3f} P(loss>50) {y5['P_loss_gt_50pct']:.3f} | ES5 {y5['expected_shortfall_5pct']:.3f} | P(2x) {y5['P_2x']:.3f} | q5..q95 {y5['CAGR_quantiles']['0.05']:.3f}..{y5['CAGR_quantiles']['0.95']:.3f}")
print("   вклад в медиану Y5:", {k: round(v, 3) for k, v in o["median_contribution_Y5"].items()})
print("   корреляции log-стоимости Y5 (top):", sorted(o["log_value_correlation_Y5"].items(), key=lambda x: -x[1])[:6])
# 2) оптимизатор, стадия A
inp = {"paths_files": paths_files, "weights_current": wcur, "fixed_weights": fixed, "dry_powder_current": cash_w, "dry_powder_return_annual": 0.04, "regime": regime,
       "limits": limits, "per_name_caps": caps, "roles": {}, "sectors": sectors, "common_cause": cc, "objective_tolerance_pp": 0.5}
r2 = post({"model": "portfolio_optimizer", "inputs": inp, "seed": 0, "save": True})
o = r2["outputs"]
print(f"portfolio_optimizer run {r2['run_id']}: feasible {o['feasible']} (старт {o['start_used']}) | веса {o['proposed_weights']} | dp {o['dry_powder_weight']} (pref max {o['dry_powder_preferred_max']})")
y5 = o["portfolio_return_distribution"]["Y5"]; d5 = o["portfolio_downside"]["Y5"]
print(f"   оптимум: медиана CAGR 5Y {y5['median_CAGR']:.3f} (3Y {o['portfolio_return_distribution']['Y3']['median_CAGR']:.3f}, 8Y {o['portfolio_return_distribution']['Y8']['median_CAGR']:.3f}) | P(loss>30) {d5['P_loss_gt_30pct']:.3f} P(loss>50) {d5['P_loss_gt_50pct']:.3f} ES5 {d5['expected_shortfall_5pct']:.3f} | P(2x) {y5['P_2x']:.3f} | оборот {o['turnover_from_current']}")
print("   текущий (в той же постановке):", {k: round(v, 3) for k, v in o["current_portfolio"]["return_distribution_Y5"].items()})
print("   нарушения в оптимуме:", o["violations_at_optimum"], "| minimum_relaxations:", o["minimum_relaxations"])
print("   связывающие:", o["binding_constraints"])
print("   полосы:", o["feasible_weight_bands"])
print("   концентрации:", {k: (v if not isinstance(v, dict) else {kk: round(vv, 3) for kk, vv in v.items()}) for k, v in o["concentrations"].items()})
print("   разрывы к текущему:", [(g["constraint"], round(g["value"], 3), g["bound"]) for g in o["constraint_gaps_vs_current"]])
print("   кандидаты:", o["candidates"])
