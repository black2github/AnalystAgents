"""Заход 7 (30.09): отбор по лимитам владельца DR-2026-09-27-01 (approved_limits_v1_1) — portfolio_optimizer 1.1.0 на файлах-смеси захода 6
(mix-p10-p07-p175) с сценарно-условными ограничениями и хеджем GLD. Три прогона «до/после»:
  A) отчётный: пороги не заданы (только картина под сценариями на оптимуме захода 6), GLD фиксирован 2.2 %;
  B) пороги V1 (p_min 0.10, ES5 ≥ −40 %, P(l30) ≤ 25 %, концентрация ≤ 60 %), GLD фиксирован;
  C) пороги V1 + GLD как хедж (≤ 10 % NAV, плоская доходность 0 %).
Затем нормативная смесь §6 (portfolio_paths) на оптимуме C — отчётный риск и концентрация. Запуск: python _portfolio_run7.py"""
import json
import urllib.request
from pathlib import Path

import yaml

WS = Path("C:/openclaw-lab/data/workspace-invest"); URL = "http://127.0.0.1:18791/run"; S = Path(__file__).parent
C = "/data/workspace-invest/portfolio/_runs"
NORM = {"HOOD": "20260924T074150Z-company_mc-038894", "LLY": "20260924T074630Z-company_mc-89318c", "PLTR": "20260924T180209Z-company_mc-460fe8",
        "NET": "20260924T180403Z-company_mc-a8783a", "ASTS": "20260925T082018Z-company_mc-17e2e2", "CRWV": "20260925T115341Z-company_mc-a1b31f"}
NORM.update(json.load(open(S / "_norm_runs_joint11.json", encoding="utf-8")))
RES2 = json.load(open(S / "_scenario_normative2.json", encoding="utf-8")); RES3 = json.load(open(S / "_scenario_round3.json", encoding="utf-8"))
P = {"TAIWAN_SEIZURE": 0.10, "CHIP_COLD_WAR": 0.07, "TAIWAN_QUARANTINE": 0.175}
SEV = {"critical": 1.0, "high": 0.75, "medium": 0.5, "low": 0.25}
RUN6 = json.load(open(S / "_opt_run6.json", encoding="utf-8")); FILES = RUN6["files"]


def post(payload):
    return json.load(urllib.request.urlopen(urllib.request.Request(URL, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}), timeout=4 * 3600))


def pf(sid, tk):
    if sid == "BASE":
        return f"{C}/{NORM[tk]}-paths.npz"
    if tk == "SPCX" or sid == "TAIWAN_QUARANTINE":
        return RES3[sid][tk]["paths_file"]
    return RES2[sid][tk]["paths_file"]


p = yaml.safe_load((WS / "portfolio/_portfolio.yaml").read_text(encoding="utf-8")); mo = p["machine_outputs"]; wcur = mo["current_weights"]; regime = mo["regime"]
sectors = {x["ticker"]: x.get("sector_id") for x in p["portfolio"]["positions"]}
cons = p["constraints"]; lim = cons["approved_limits_v1_0"]; l11 = cons["approved_limits_v1_1"]; sc11 = l11["scenario_conditional"]
cash_w = round(1.0 - sum(wcur.values()), 4); caps = RUN6["caps"]
cc = {}
for d in sorted((WS / "portfolio").glob("*/mpc_inputs.yaml")):
    m = yaml.safe_load(d.read_text(encoding="utf-8")); tk = (m.get("ticker") or d.parent.name).upper(); tk = "SPCX" if tk == "SPACEX" else tk
    for fm in m.get("failure_modes", []):
        c = fm.get("common_cause_id"); s_ = str(fm.get("severity", "")).lower()
        if c:
            cc.setdefault(c, {}); cc[c][tk] = max(cc[c].get(tk, 0.0), SEV.get(s_, 0.5))
limits = {"sector_max": lim["sector_max"], "top3_aggregate_max": lim["top3_aggregate_max"], "common_cause_effective_max": lim["common_cause_effective_max"], "roles": lim["roles"], "dry_powder": lim["dry_powder"], "risk_5y": lim["risk_5y"]}
scen_files = [{"id": sid, "probability": pr, "paths_files": {tk: pf(sid, tk) for tk in NORM}} for sid, pr in P.items()]
base_files = {tk: pf("BASE", tk) for tk in NORM}
print("режим", regime, "| кэш", cash_w, "| лимиты v1.1:", sc11, "| GLD max", l11["hedge_instruments"]["GLD_max_weight"], flush=True)


def optimize(label, thresholds: bool, hedge: bool):
    fixed = {tk: w for tk, w in wcur.items() if tk not in NORM and not (hedge and tk == "GLD")}
    sc = {"p_min": sc11["p_min"], "es5_min": sc11["es5_min"] if thresholds else None, "p_loss_gt_30_max": sc11["p_loss_gt_30_max"] if thresholds else None,
          "scenario_concentration_max": sc11["scenario_concentration_max"] if thresholds else None, "scenarios": scen_files, "base_paths_files": base_files}
    inp = {"paths_files": FILES, "weights_current": wcur, "fixed_weights": fixed, "dry_powder_current": cash_w, "dry_powder_return_annual": 0.04, "regime": regime, "limits": limits,
           "per_name_caps": caps, "roles": {}, "sectors": sectors, "common_cause": cc, "objective_tolerance_pp": 0.5, "scenario_constraints": sc}
    if hedge:
        inp["hedge_instruments"] = {"GLD": {"max_weight": l11["hedge_instruments"]["GLD_max_weight"], "return_annual": 0.0}}
    r = post({"model": "portfolio_optimizer", "inputs": inp, "seed": 0, "save": True}); o = r["outputs"]; y5 = o["portfolio_return_distribution"]["Y5"]; d5 = o["portfolio_downside"]["Y5"]
    print(f"\n[{label}] {r['run_id']}: feasible {o['feasible']} | веса {{k: v for k, v in o['proposed_weights'].items() if v > 0}} | dp {o['dry_powder_weight']}", flush=True)
    print(f"   смесь на оптимуме: медиана CAGR 5Y {y5['median_CAGR']:.3f} | P(l30) {d5['P_loss_gt_30pct']:.3f} ES5 {d5['expected_shortfall_5pct']:.3f} | turnover {o.get('turnover_from_current')} | связывающие {o['binding_constraints']} | нарушения {o['violations_at_optimum']}", flush=True)
    b = o["scenario_constraints"]
    for tag, blk in (("оптимум", b["at_optimum"]), ("текущие", b["at_current"])):
        print(f"   под сценариями ({tag}): " + " | ".join(f"{sid}: med {m['median_CAGR']:+.3f} ES5 {m['expected_shortfall_5pct']:+.3f} P(l30) {m['P_loss_gt_30pct']:.3f}" for sid, m in blk["by_scenario"].items())
              + f" | BASE: med {blk['base']['median_CAGR']:+.3f} ES5 {blk['base']['expected_shortfall_5pct']:+.3f} | B {{k: round(v, 4) for k, v in blk['burdens_B'].items()}} | concentration {blk['scenario_concentration']['status']} {blk['scenario_concentration']['value']}", flush=True)
    return r["run_id"], o


ra, oa = optimize("A: отчёт без порогов, GLD fixed", thresholds=False, hedge=False)
rb, ob = optimize("B: пороги V1, GLD fixed", thresholds=True, hedge=False)
rc, oc = optimize("C: пороги V1 + GLD хедж ≤ 10 %", thresholds=True, hedge=True)
for lab, o in (("B−A", ob), ("C−A", oc)):
    diff = {tk: round(o["proposed_weights"].get(tk, 0.0) - oa["proposed_weights"].get(tk, 0.0), 4) for tk in set(o["proposed_weights"]) | set(oa["proposed_weights"])}
    print(f"Δ весов {lab}:", {k: v for k, v in diff.items() if abs(v) >= 0.005}, "| Δdp", round(o["dry_powder_weight"] - oa["dry_powder_weight"], 4), flush=True)
# нормативная смесь §6 на оптимуме C (веса бумаг с путями; GLD и UFO — вне смеси, как в заходе 6)
wopt = {tk: w for tk, w in oc["proposed_weights"].items() if tk in NORM and w > 0}; s = sum(wopt.values()) + oc["dry_powder_weight"]
r = post({"model": "portfolio_paths", "inputs": {"scenarios": [{"id": "BASE", "paths_files": base_files}] + scen_files, "weights": {tk: w / s for tk, w in wopt.items()}, "dry_powder_weight": oc["dry_powder_weight"] / s, "dry_powder_return_annual": 0.04}, "seed": 0, "save": True})
o = r["outputs"]; y5 = o["horizons"]["Y5"]; scn = o["scenario_concentration"]
print(f"\nсмесь §6 на оптимуме C {r['run_id']}: Y5 median {y5['median_CAGR']:+.4f} P(l30) {y5['P_loss_gt_30pct']:.4f} ES5 {y5['expected_shortfall_5pct']:+.4f} | impacts {{k: (round(v['MedianImpact_Y5'], 4), round(v['ES5Impact_Y5'], 4)) for k, v in o['scenario_impacts'].items()}} | concentration {scn['status']} {scn['value']} warning {scn['warning']}", flush=True)
json.dump({"A": {"run_id": ra, "weights": oa["proposed_weights"], "dp": oa["dry_powder_weight"]}, "B": {"run_id": rb, "weights": ob["proposed_weights"], "dp": ob["dry_powder_weight"], "feasible": ob["feasible"]},
           "C": {"run_id": rc, "weights": oc["proposed_weights"], "dp": oc["dry_powder_weight"], "feasible": oc["feasible"]}, "mixture_C": r["run_id"]}, open(S / "_opt_run7.json", "w", encoding="utf-8"), indent=1)
print("DONE", flush=True)
