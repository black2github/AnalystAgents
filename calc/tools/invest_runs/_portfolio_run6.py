"""Заход 6 (27.09): 15 бумаг на схеме 1.0.2 (SPCX v1.1.3), СМЕСЬ 4 сценариев по решениям владельца: TAIWAN_SEIZURE 0.10, CHIP_COLD_WAR 0.07,
TAIWAN_QUARANTINE 0.175, BASE 0.655. Шаги: 1) нормативная взвешенная смесь §6 (portfolio_paths, текущие веса, save) + концентрация (вариант «а»);
2) mixture_export → файлы-смеси (тег mix-p10-p07-p175); сверка метрик; 3) оптимизатор стадии A (потолки Conviction Overlay по BASE-нормативам,
fixed GLD/UFO); 4) концентрация и метрики смеси на оптимуме (portfolio_paths §6 с весами оптимума); 5) --sens: §3.3 (×0.75 / ×1.25 / +10 п.п.
каждому сценарию → оптимизатор ×5). Запуск: python _portfolio_run6.py [--sens]"""
import json
import sys
import urllib.request
from pathlib import Path

import yaml

WS = Path("C:/openclaw-lab/data/workspace-invest"); URL = "http://127.0.0.1:18791/run"; S = Path(__file__).parent
C = "/data/workspace-invest/portfolio/_runs"
NORM = {"HOOD": "20260924T074150Z-company_mc-038894", "LLY": "20260924T074630Z-company_mc-89318c", "PLTR": "20260924T180209Z-company_mc-460fe8",
        "NET": "20260924T180403Z-company_mc-a8783a", "ASTS": "20260925T082018Z-company_mc-17e2e2", "CRWV": "20260925T115341Z-company_mc-a1b31f"}
NORM.update(json.load(open(S / "_norm_runs_joint11.json", encoding="utf-8")))          # NBIS/NVDA/MSFT/META/ASML/RKLB/ETN/SPOT/SPCX
RES2 = json.load(open(S / "_scenario_normative2.json", encoding="utf-8")); RES3 = json.load(open(S / "_scenario_round3.json", encoding="utf-8"))
P = {"TAIWAN_SEIZURE": 0.10, "CHIP_COLD_WAR": 0.07, "TAIWAN_QUARANTINE": 0.175}
SEV = {"critical": 1.0, "high": 0.75, "medium": 0.5, "low": 0.25}; SENS = "--sens" in sys.argv


def post(payload):
    return json.load(urllib.request.urlopen(urllib.request.Request(URL, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}), timeout=4 * 3600))


def pf(sid, tk):
    if sid == "BASE":
        return f"{C}/{NORM[tk]}-paths.npz"
    if tk == "SPCX" or sid == "TAIWAN_QUARANTINE":
        return RES3[sid][tk]["paths_file"]
    return RES2[sid][tk]["paths_file"]


def scen_list(probs):
    return [{"id": "BASE", "paths_files": {tk: pf("BASE", tk) for tk in NORM}}] + [{"id": sid, "probability": p, "paths_files": {tk: pf(sid, tk) for tk in NORM}} for sid, p in probs.items()]


p = yaml.safe_load((WS / "portfolio/_portfolio.yaml").read_text(encoding="utf-8")); mo = p["machine_outputs"]; wcur = mo["current_weights"]; regime = mo["regime"]
sectors = {x["ticker"]: x.get("sector_id") for x in p["portfolio"]["positions"]}
cons = p["constraints"]; ap = cons["conviction_overlay_v1_0"]["approved_params"]; lim = cons["approved_limits_v1_0"]; conv = set(cons["conviction_overlay_v1_0"].get("active_conviction_tags") or [])
cash_w = round(1.0 - sum(wcur.values()), 4)
caps = {}
for tk, rid in NORM.items():
    b = json.load(open(WS / "portfolio/_runs" / f"{rid}.json", encoding="utf-8"))["outputs"]["base"]["downside"]
    dd = min(max(max(abs(b["expected_shortfall_5pct_5Y"]), abs(b["max_drawdown_5Y_quantiles"]["0.25"])), ap["plausible_drawdown_floor"]), ap["plausible_drawdown_ceiling"])
    hard = (min(max(ap["L_max_conviction"] / dd, ap["conviction_hard_cap_floor"]), ap["conviction_hard_cap_ceiling"]) if tk in conv else min(max(ap["L_max_standard"] / dd, ap["standard_hard_cap_floor"]), ap["standard_hard_cap_ceiling"]))
    caps[tk] = round(ap["target_safety_buffer"] * hard, 4)
cc = {}
for d in sorted((WS / "portfolio").glob("*/mpc_inputs.yaml")):
    m = yaml.safe_load(d.read_text(encoding="utf-8")); tk = (m.get("ticker") or d.parent.name).upper(); tk = "SPCX" if tk == "SPACEX" else tk
    for fm in m.get("failure_modes", []):
        c = fm.get("common_cause_id"); s_ = str(fm.get("severity", "")).lower()
        if c:
            cc.setdefault(c, {}); cc[c][tk] = max(cc[c].get(tk, 0.0), SEV.get(s_, 0.5))
fixed = {tk: w for tk, w in wcur.items() if tk not in NORM}
limits = {"sector_max": lim["sector_max"], "top3_aggregate_max": lim["top3_aggregate_max"], "common_cause_effective_max": lim["common_cause_effective_max"], "roles": lim["roles"], "dry_powder": lim["dry_powder"], "risk_5y": lim["risk_5y"]}
print("режим", regime, "| кэш", cash_w, "| fixed", fixed, "| потолки:", caps, flush=True)


def mixture(weights, dp, probs, label, save=True):
    s = sum(weights.values()) + dp
    r = post({"model": "portfolio_paths", "inputs": {"scenarios": scen_list(probs), "weights": {tk: w / s for tk, w in weights.items()}, "dry_powder_weight": dp / s, "dry_powder_return_annual": 0.04}, "seed": 0, "save": save})
    o = r["outputs"]; y5 = o["horizons"]["Y5"]; sc = o["scenario_concentration"]
    print(f"смесь [{label}] {r['run_id']}: Y5 median {y5['median_CAGR']:+.4f} q5 {y5['CAGR_quantiles']['0.05']:+.3f} P(l30) {y5['P_loss_gt_30pct']:.4f} ES5 {y5['expected_shortfall_5pct']:+.4f} P2x {y5['P_2x']:.3f} | impacts {{k: (round(v['MedianImpact_Y5'], 4), round(v['ES5Impact_Y5'], 4)) for k, v in o['scenario_impacts'].items()}} | concentration {sc['status']} value {sc['value']} warning {sc['warning']} hard {sc['hard_limit_breach']}", flush=True)
    return r["run_id"], o


def export(probs, tag):
    r = post({"model": "portfolio_paths", "inputs": {"mode": "mixture_export", "scenarios": scen_list(probs), "out_dir": C, "tag": tag}, "seed": 0, "save": True}); o = r["outputs"]
    print(f"экспорт [{tag}] {r['run_id']}: ranges {o['ranges']}", flush=True); return o["paths_files"]


def optimize(files, label):
    inp = {"paths_files": files, "weights_current": wcur, "fixed_weights": fixed, "dry_powder_current": cash_w, "dry_powder_return_annual": 0.04, "regime": regime, "limits": limits, "per_name_caps": caps, "roles": {}, "sectors": sectors, "common_cause": cc, "objective_tolerance_pp": 0.5}
    r = post({"model": "portfolio_optimizer", "inputs": inp, "seed": 0, "save": True}); o = r["outputs"]; y5 = o["portfolio_return_distribution"]["Y5"]; d5 = o["portfolio_downside"]["Y5"]
    print(f"optimizer [{label}] {r['run_id']}: feasible {o['feasible']} | веса {{k: v for k, v in o['proposed_weights'].items() if v > 0}} | dp {o['dry_powder_weight']}", flush=True)
    print(f"   медиана CAGR 5Y {y5['median_CAGR']:.3f} (3Y {o['portfolio_return_distribution']['Y3']['median_CAGR']:.3f}) | P(l30) {d5['P_loss_gt_30pct']:.3f} P(l50) {d5['P_loss_gt_50pct']:.3f} ES5 {d5['expected_shortfall_5pct']:.3f} | turnover {o.get('turnover_from_current')} | связывающие {o['binding_constraints']} | нарушения {o['violations_at_optimum']}", flush=True)
    return r["run_id"], o


wc = {tk: wcur[tk] for tk in NORM}
if not SENS:
    mixture(wc, cash_w, P, "текущие веса, норматив")
    files = export(P, "mix-p10-p07-p175"); json.dump(files, open(S / "_mixture_files_p10_p07_p175.json", "w", encoding="utf-8"), indent=1)
    s = sum(wc.values()) + cash_w
    r1 = post({"model": "portfolio_paths", "inputs": {"paths_files": files, "weights": {tk: w / s for tk, w in wc.items()}, "dry_powder_weight": cash_w / s, "dry_powder_return_annual": 0.04}, "seed": 0, "save": True}); y5 = r1["outputs"]["horizons"]["Y5"]
    print(f"сверка на файлах {r1['run_id']}: median5 {y5['median_CAGR']:+.4f} P(l30) {y5['P_loss_gt_30pct']:.4f} ES5 {y5['expected_shortfall_5pct']:+.4f}", flush=True)
    rid, o = optimize(files, "смесь 0.10/0.07/0.175")
    w_opt = {tk: w for tk, w in o["proposed_weights"].items() if w > 0}
    mixture(w_opt, o["dry_powder_weight"], P, "оптимум захода 6 — концентрация")
    json.dump({"run_id": rid, "proposed_weights": o["proposed_weights"], "dry_powder_weight": o["dry_powder_weight"], "caps": caps, "files": files}, open(S / "_opt_run6.json", "w", encoding="utf-8"), indent=1)
else:
    base = json.load(open(S / "_opt_run6.json", encoding="utf-8")); print("база:", {k: v for k, v in base["proposed_weights"].items() if v > 0}, "dp", base["dry_powder_weight"], flush=True)
    for tag, probs in (("x075", {k: v * 0.75 for k, v in P.items()}), ("x125", {k: v * 1.25 for k, v in P.items()}), ("tsUp10", {**P, "TAIWAN_SEIZURE": 0.20}), ("cwUp10", {**P, "CHIP_COLD_WAR": 0.17}), ("qUp10", {**P, "TAIWAN_QUARANTINE": 0.275})):
        files = export(probs, f"mix6-{tag}"); rid, o = optimize(files, f"§3.3 {tag}: {probs}")
        diff = {tk: round(o["proposed_weights"].get(tk, 0.0) - base["proposed_weights"].get(tk, 0.0), 4) for tk in set(o["proposed_weights"]) | set(base["proposed_weights"])}
        print("   Δ весов к базе:", {k: v for k, v in diff.items() if abs(v) >= 0.005}, "| Δdp", round(o["dry_powder_weight"] - base["dry_powder_weight"], 4), flush=True)
print("DONE", flush=True)
