"""Валидация портфеля, заход 5 (25.09 поздно): 15 калиброванных бумаг (97.2 % NAV) под Joint v1.1 на СМЕСИ сценариев по
вероятностям владельца (DR-2026-09-25-01: TAIWAN_SEIZURE 0.10, CHIP_COLD_WAR 0.07, BASE 0.83). Шаги:
1) portfolio_paths mixture_export → файлы-смеси по 15 компаниям (разбиение path_id; тег mix-p10-p07);
2) portfolio_paths на файлах-смеси (текущие веса) — сверка со взвешенной смесью (§6, run с probabilities);
3) portfolio_optimizer стадия A на файлах-смеси: потолки Conviction Overlay по MC BASE-нормативов (как заход 4: plausible_dd =
   max(|ES5|, |Q25 maxdd|), clamp; hard = clamp(L_max/dd); target = 0.75 × hard), фиксированы только GLD/UFO, режим из реестра;
4) --sens: §3.3 Stability по вероятностям как скрипт — смеси при ×0.75 / ×1.25 / +10 п.п. на каждый сценарий → оптимизатор ×4,
   сравнение весов и целевой (долг: перенести в portfolio_stability).
Запуск: python _portfolio_run5.py [--sens]"""
import json
import sys
import urllib.request
from pathlib import Path

import yaml

WS = Path("C:/openclaw-lab/data/workspace-invest"); URL = "http://127.0.0.1:18791/run"; S = Path(__file__).parent
C = "/data/workspace-invest/portfolio/_runs"
NORM = {"SPCX": "20260924T073336Z-company_mc-e55d7d", "HOOD": "20260924T074150Z-company_mc-038894", "LLY": "20260924T074630Z-company_mc-89318c",
        "PLTR": "20260924T180209Z-company_mc-460fe8", "NET": "20260924T180403Z-company_mc-a8783a", "ASTS": "20260925T082018Z-company_mc-17e2e2",
        "CRWV": "20260925T115341Z-company_mc-a1b31f"}
NORM.update(json.load(open(S / "_norm_runs_joint11.json", encoding="utf-8")))
RES2 = json.load(open(S / "_scenario_normative2.json", encoding="utf-8"))
P_TS, P_CW = 0.10, 0.07
SEV = {"critical": 1.0, "high": 0.75, "medium": 0.5, "low": 0.25}
SENS = "--sens" in sys.argv


def post(payload):
    req = urllib.request.Request(URL, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=4 * 3600))


def scen_list(p_ts, p_cw):
    return [{"id": "BASE", "paths_files": {tk: f"{C}/{rid}-paths.npz" for tk, rid in NORM.items()}},
            {"id": "TAIWAN_SEIZURE", "probability": p_ts, "paths_files": {tk: RES2["TAIWAN_SEIZURE"][tk]["paths_file"] for tk in NORM}},
            {"id": "CHIP_COLD_WAR", "probability": p_cw, "paths_files": {tk: RES2["CHIP_COLD_WAR"][tk]["paths_file"] for tk in NORM}}]


p = yaml.safe_load((WS / "portfolio/_portfolio.yaml").read_text(encoding="utf-8"))
mo = p["machine_outputs"]; wcur = mo["current_weights"]; regime = mo["regime"]
positions = p["portfolio"]["positions"]; sectors = {x["ticker"]: x.get("sector_id") for x in positions}
cons = p["constraints"]; ap = cons["conviction_overlay_v1_0"]["approved_params"]; lim = cons["approved_limits_v1_0"]
conv = set(cons["conviction_overlay_v1_0"].get("active_conviction_tags") or [])
cash_w = round(1.0 - sum(wcur.values()), 4)
caps = {}; dd_used = {}
for tk, rid in NORM.items():
    b = json.load(open(WS / "portfolio/_runs" / f"{rid}.json", encoding="utf-8"))["outputs"]["base"]["downside"]
    dd = max(abs(b["expected_shortfall_5pct_5Y"]), abs(b["max_drawdown_5Y_quantiles"]["0.25"]))
    dd = min(max(dd, ap["plausible_drawdown_floor"]), ap["plausible_drawdown_ceiling"])
    if tk in conv:
        hard = min(max(ap["L_max_conviction"] / dd, ap["conviction_hard_cap_floor"]), ap["conviction_hard_cap_ceiling"])
    else:
        hard = min(max(ap["L_max_standard"] / dd, ap["standard_hard_cap_floor"]), ap["standard_hard_cap_ceiling"])
    caps[tk] = round(ap["target_safety_buffer"] * hard, 4); dd_used[tk] = round(dd, 3)
cc = {}
for d in sorted((WS / "portfolio").glob("*/mpc_inputs.yaml")):
    m = yaml.safe_load(d.read_text(encoding="utf-8")); tk = (m.get("ticker") or d.parent.name).upper()
    if tk == "SPACEX": tk = "SPCX"
    for fm in m.get("failure_modes", []):
        c = fm.get("common_cause_id"); s = str(fm.get("severity", "")).lower()
        if c:
            cc.setdefault(c, {}); cc[c][tk] = max(cc[c].get(tk, 0.0), SEV.get(s, 0.5))
fixed = {tk: w for tk, w in wcur.items() if tk not in NORM}
limits = {"sector_max": lim["sector_max"], "top3_aggregate_max": lim["top3_aggregate_max"], "common_cause_effective_max": lim["common_cause_effective_max"],
          "roles": lim["roles"], "dry_powder": lim["dry_powder"], "risk_5y": lim["risk_5y"]}
print("режим", regime, "| кэш", cash_w, "| fixed", round(sum(fixed.values()), 4), fixed, flush=True)
print("потолки (target_cap по MC BASE):", caps, "| plausible_dd:", dd_used, flush=True)


def export(p_ts, p_cw, tag):
    r = post({"model": "portfolio_paths", "inputs": {"mode": "mixture_export", "scenarios": scen_list(p_ts, p_cw), "out_dir": C, "tag": tag}, "seed": 0, "save": True})
    if r.get("error"):
        raise SystemExit("export ERROR: " + r["error"][:400])
    o = r["outputs"]; print(f"экспорт смеси [{tag}] run {r['run_id']}: ranges {o['ranges']} paths {o['paths']}", flush=True)
    return o["paths_files"]


def optimize(paths_files, label, save=True):
    inp = {"paths_files": paths_files, "weights_current": wcur, "fixed_weights": fixed, "dry_powder_current": cash_w, "dry_powder_return_annual": 0.04, "regime": regime,
           "limits": limits, "per_name_caps": caps, "roles": {}, "sectors": sectors, "common_cause": cc, "objective_tolerance_pp": 0.5}
    r = post({"model": "portfolio_optimizer", "inputs": inp, "seed": 0, "save": save})
    if r.get("error"):
        raise SystemExit("optimizer ERROR: " + r["error"][:600])
    o = r["outputs"]; y5 = o["portfolio_return_distribution"]["Y5"]; d5 = o["portfolio_downside"]["Y5"]
    print(f"optimizer [{label}] run {r['run_id']}: feasible {o['feasible']} (старт {o['start_used']}) | веса {o['proposed_weights']} | dp {o['dry_powder_weight']}", flush=True)
    print(f"   оптимум: медиана CAGR 5Y {y5['median_CAGR']:.3f} (3Y {o['portfolio_return_distribution']['Y3']['median_CAGR']:.3f}) | P(l30) {d5['P_loss_gt_30pct']:.3f} P(l50) {d5['P_loss_gt_50pct']:.3f} ES5 {d5['expected_shortfall_5pct']:.3f} | turnover {o.get('turnover_from_current')}", flush=True)
    print("   текущий (в той же постановке):", {k: round(v, 3) for k, v in o["current_portfolio"]["return_distribution_Y5"].items()}, flush=True)
    print("   нарушения в оптимуме:", o["violations_at_optimum"], "| связывающие:", o["binding_constraints"], flush=True)
    print("   разрывы к текущему:", [(g["constraint"], round(g["value"], 3), g["bound"]) for g in o["constraint_gaps_vs_current"]], flush=True)
    return r["run_id"], o


if not SENS:
    files = export(P_TS, P_CW, "mix-p10-p07")
    json.dump(files, open(S / "_mixture_files_p10_p07.json", "w", encoding="utf-8"), indent=1)
    wc = {tk: wcur[tk] for tk in NORM}; s = sum(wc.values()) + cash_w
    r1 = post({"model": "portfolio_paths", "inputs": {"paths_files": files, "weights": {tk: w / s for tk, w in wc.items()}, "dry_powder_weight": cash_w / s, "dry_powder_return_annual": 0.04}, "seed": 0, "save": True})
    y5 = r1["outputs"]["horizons"]["Y5"]
    r0 = post({"model": "portfolio_paths", "inputs": {"scenarios": scen_list(P_TS, P_CW), "weights": {tk: w / s for tk, w in wc.items()}, "dry_powder_weight": cash_w / s, "dry_powder_return_annual": 0.04}, "seed": 0, "save": True})
    w5 = r0["outputs"]["horizons"]["Y5"]
    print(f"смесь на файлах {r1['run_id']}: median5 {y5['median_CAGR']:+.4f} P(l30) {y5['P_loss_gt_30pct']:.4f} ES5 {y5['expected_shortfall_5pct']:+.4f} | взвешенная §6 {r0['run_id']}: {w5['median_CAGR']:+.4f} {w5['P_loss_gt_30pct']:.4f} {w5['expected_shortfall_5pct']:+.4f}", flush=True)
    rid, o = optimize(files, "смесь 0.10/0.07")
    json.dump({"run_id": rid, "proposed_weights": o["proposed_weights"], "dry_powder_weight": o["dry_powder_weight"], "caps": caps, "files": files}, open(S / "_opt_run5.json", "w", encoding="utf-8"), indent=1)
else:
    base = json.load(open(S / "_opt_run5.json", encoding="utf-8"))
    print("база (0.10/0.07):", base["proposed_weights"], "dp", base["dry_powder_weight"], flush=True)
    for tag, pts, pcw in (("x075", 0.075, 0.0525), ("x125", 0.125, 0.0875), ("tsUp10", 0.20, 0.07), ("cwUp10", 0.10, 0.17)):
        files = export(pts, pcw, f"mix-{tag}")
        rid, o = optimize(files, f"§3.3 {tag}: TS {pts} CW {pcw}", save=True)
        diff = {tk: round(o["proposed_weights"].get(tk, 0.0) - base["proposed_weights"].get(tk, 0.0), 4) for tk in set(o["proposed_weights"]) | set(base["proposed_weights"])}
        print("   Δ весов к базе:", {k: v for k, v in diff.items() if abs(v) >= 0.005}, "| Δdp", round(o["dry_powder_weight"] - base["dry_powder_weight"], 4), flush=True)
print("DONE", flush=True)
