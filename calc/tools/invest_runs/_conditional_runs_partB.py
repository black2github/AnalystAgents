"""Часть B слоя действий v1.2 (01.10): условные прогоны подтверждённых фаз (Scenario_Engine_Specification v1.1 §21, company_mc 2.5.0
conditional_run) и условные оптимумы (portfolio_optimizer 1.1.1) по фазам TAIWAN_SEIZURE (BLOCKADE, CONFLICT, RECOVERY) и TAIWAN_QUARANTINE
(QUARANTINE, NORMALIZATION_OR_FROZEN). Фаза RESTRICTIONS у обоих сценариев уже fixed_quarter 0 — условный прогон побитно равен
безусловному (тест PR#1), поэтому для неё берутся пути раундов 2–3, а условный оптимум считается на них.
Прогоны компаний: 15 калиброванных бумаг × 5 фаз × 500k путей на общих path_id (seed 20260920, как в раундах 2–3), store_paths.
Условный оптимум: оптимизатор на путях фазы (probability = 1 — сама вселенная), лимиты владельца approved_limits_v1_0, потолки
Conviction Overlay захода 6, fixed GLD/UFO, старты current/equal/empty/given (оптимум C2 захода 7). Сценарно-условные ограничения
не подаются: условная картина — это уже сценарий при p = 1 (Action Layer §4 — «те же owner structural limits и risk rules»).
Результаты: _conditional_runs_partB.json (возобновляемый: готовые пропускаются). Запуск: python _conditional_runs_partB.py"""
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

import yaml

S = Path(__file__).parent; WS = Path("C:/openclaw-lab/data/workspace-invest"); URL = "http://127.0.0.1:18791/run"; C = "/data/workspace-invest/portfolio/_runs"
CAL = {"SPCX": ("spacex", "mc_calibration_v1.1.3.yaml"), "NBIS": ("nbis", "mc_calibration_v1.0.3.yaml"), "NVDA": ("nvda", "mc_calibration_v1.0.3.yaml"), "HOOD": ("hood", "mc_calibration_v1.0.1.yaml"),
       "RKLB": ("rklb", "mc_calibration_v1.0.1.yaml"), "LLY": ("lly", "mc_calibration_v1.0.yaml"), "META": ("meta", "mc_calibration_v1.0.2.yaml"), "ASML": ("asml", "mc_calibration_v1.0.2.yaml"),
       "MSFT": ("msft", "mc_calibration_v1.0.1.yaml"), "PLTR": ("pltr", "mc_calibration_v1.0.yaml"), "NET": ("net", "mc_calibration_v1.0.yaml"), "ETN": ("etn", "mc_calibration_v1.0.2.yaml"),
       "ASTS": ("asts", "mc_calibration_v1.0.yaml"), "CRWV": ("crwv", "mc_calibration_v1.0.1.yaml"), "SPOT": ("spot", "mc_calibration_v1.0.yaml")}
NORM = {"HOOD": "20260924T074150Z-company_mc-038894", "LLY": "20260924T074630Z-company_mc-89318c", "PLTR": "20260924T180209Z-company_mc-460fe8", "NET": "20260924T180403Z-company_mc-a8783a",
        "ASTS": "20260925T082018Z-company_mc-17e2e2", "CRWV": "20260925T115341Z-company_mc-a1b31f"}
NORM.update(json.load(open(S / "_norm_runs_joint11.json", encoding="utf-8")))
RES2 = json.load(open(S / "_scenario_normative2.json", encoding="utf-8")); RES3 = json.load(open(S / "_scenario_round3.json", encoding="utf-8"))
R7 = json.load(open(S / "_opt_run7.json", encoding="utf-8")); RUN6 = json.load(open(S / "_opt_run6.json", encoding="utf-8"))
PHASES = {"TAIWAN_SEIZURE": ["RESTRICTIONS", "BLOCKADE", "CONFLICT", "RECOVERY"], "TAIWAN_QUARANTINE": ["RESTRICTIONS", "QUARANTINE", "NORMALIZATION_OR_FROZEN"]}
SCEN_FILES = {"TAIWAN_SEIZURE": "TAIWAN_SEIZURE_v1.1.yaml", "TAIWAN_QUARANTINE": "TAIWAN_QUARANTINE_v1.1.yaml"}
SEV = {"critical": 1.0, "high": 0.75, "medium": 0.5, "low": 0.25}
res_path = S / "_conditional_runs_partB.json"; RES = json.load(open(res_path, encoding="utf-8")) if res_path.exists() else {}


def post(payload):
    req = urllib.request.Request(URL, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=12 * 3600) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode("utf-8", "replace")[:600]}


def save():
    json.dump(RES, open(res_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def unconditional_paths(sid, tk):
    """Пути сценария из раундов 2–3 (= условный прогон RESTRICTIONS, fixed_quarter 0)."""
    if tk == "SPCX" or sid == "TAIWAN_QUARANTINE":
        return RES3[sid][tk]["paths_file"]
    return RES2[sid][tk]["paths_file"]


spec = yaml.safe_load((WS / "methodology" / "Joint_Simulation_Layer_Schema_v1.1.yaml").read_text(encoding="utf-8"))
# ---------------------------------------------------------------- 1) условные прогоны компаний
for sid, phases in PHASES.items():
    scen = yaml.safe_load((WS / "portfolio/_scenarios" / SCEN_FILES[sid]).read_text(encoding="utf-8"))
    for pid in phases:
        key = f"{sid}|{pid}"; RES.setdefault(key, {"companies": {}})
        if pid == "RESTRICTIONS":
            for tk in CAL:
                RES[key]["companies"].setdefault(tk, {"paths_file": unconditional_paths(sid, tk), "run_id": None, "note": "RESTRICTIONS = fixed_quarter 0: условный прогон побитно равен безусловному (раунды 2–3)"})
            save(); continue
        for tk in CAL:
            if RES[key]["companies"].get(tk, {}).get("run_id"):
                continue
            folder, fname = CAL[tk]
            cal = yaml.safe_load((WS / "portfolio" / folder / fname).read_text(encoding="utf-8"))
            eq0 = json.load(open(WS / "portfolio/_runs" / f"{NORM[tk]}.json", encoding="utf-8"))["inputs"]["equity_value_0"]
            t0 = time.time()
            r = post({"model": "company_mc", "inputs": {"calibration": cal, "equity_value_0": eq0, "joint_layer_spec": spec, "paths": 500000, "chunk": 50000, "convergence_check": False, "robustness": False,
                                                        "store_paths": True, "scenario": scen, "conditional_run": {"confirmed_phase": pid}}, "seed": 20260920, "save": True})
            if r.get("error"):
                print(f"  {key}/{tk}: ERROR {r['error'][:200]}", flush=True); RES[key]["companies"][tk] = {"error": r["error"][:300]}; save(); continue
            o = r["outputs"]; b = o["base"]; q = b["return"]["CAGR_5Y_quantiles"]; js = o["joint_simulation"]; cr = o.get("conditional_run") or {}
            RES[key]["companies"][tk] = {"run_id": r["run_id"], "paths_file": o["paths_file"], "median_CAGR_5Y": b["return"]["median_CAGR_5Y"], "q05": q["0.05"], "q95": q["0.95"],
                                         "P_loss_gt_30pct_5Y": b["downside"]["P_loss_gt_30pct_5Y"], "ES5": b["downside"]["expected_shortfall_5pct_5Y"], "P_2x_5Y": b["return"]["P_2x_5Y"],
                                         "scenario_mode": js.get("scenario_mode"), "state_at_t0": cr.get("state_at_t0"), "historical_phases": cr.get("historical_phases")}
            save()
            print(f"  {key}/{tk}: {r['run_id'][-6:]} {time.time() - t0:.0f}s | median {b['return']['median_CAGR_5Y']:+.3f} q5..q95 {q['0.05']:+.3f}..{q['0.95']:+.3f} P(l30) {b['downside']['P_loss_gt_30pct_5Y']:.3f} ES5 {b['downside']['expected_shortfall_5pct_5Y']:+.3f} | mode {js.get('scenario_mode')} t0={cr.get('state_at_t0')}", flush=True)

# ---------------------------------------------------------------- 2) условные оптимумы по фазам
p = yaml.safe_load((WS / "portfolio/_portfolio.yaml").read_text(encoding="utf-8")); mo = p["machine_outputs"]; wcur = mo["current_weights"]; regime = mo["regime"]
sectors = {x["ticker"]: x.get("sector_id") for x in p["portfolio"]["positions"]}
lim = p["constraints"]["approved_limits_v1_0"]; caps = RUN6["caps"]; cash_w = round(1.0 - sum(wcur.values()), 4)
cc = {}
for d in sorted((WS / "portfolio").glob("*/mpc_inputs.yaml")):
    m = yaml.safe_load(d.read_text(encoding="utf-8")); tk = (m.get("ticker") or d.parent.name).upper(); tk = "SPCX" if tk == "SPACEX" else tk
    for fm in m.get("failure_modes", []):
        c = fm.get("common_cause_id"); s_ = str(fm.get("severity", "")).lower()
        if c:
            cc.setdefault(c, {}); cc[c][tk] = max(cc[c].get(tk, 0.0), SEV.get(s_, 0.5))
fixed = {tk: w for tk, w in wcur.items() if tk not in CAL}
limits = {"sector_max": lim["sector_max"], "top3_aggregate_max": lim["top3_aggregate_max"], "common_cause_effective_max": lim["common_cause_effective_max"], "roles": lim["roles"], "dry_powder": lim["dry_powder"], "risk_5y": lim["risk_5y"]}
given = {tk: w for tk, w in R7["C2"]["weights"].items() if tk in CAL}; given_dp = R7["C2"]["dp"]
for key, blk in list(RES.items()):
    if "|" not in key or blk.get("optimum", {}).get("run_id"):
        continue
    comp = blk["companies"]
    if any(not comp.get(tk, {}).get("paths_file") for tk in CAL):
        print(f"[{key}] оптимум пропущен: не все пути готовы", flush=True); continue
    files = {tk: comp[tk]["paths_file"] for tk in CAL}
    t0 = time.time()
    r = post({"model": "portfolio_optimizer", "inputs": {"paths_files": files, "weights_current": wcur, "fixed_weights": fixed, "dry_powder_current": cash_w, "dry_powder_return_annual": 0.04, "regime": regime, "limits": limits,
                                                          "per_name_caps": caps, "roles": {}, "sectors": sectors, "common_cause": cc, "objective_tolerance_pp": 0.5,
                                                          "starts": ["current", "equal", "empty", "given"], "start_weights": given, "start_dry_powder": given_dp}, "seed": 0, "save": True})
    if r.get("error"):
        print(f"[{key}] optimizer ERROR {r['error'][:300]}", flush=True); blk["optimum"] = {"error": r["error"][:300]}; save(); continue
    o = r["outputs"]; y5 = o["portfolio_return_distribution"]["Y5"]; d5 = o["portfolio_downside"]["Y5"]; cur = o["current_portfolio"]["return_distribution_Y5"]
    blk["optimum"] = {"run_id": r["run_id"], "feasible": o["feasible"], "weights": o["proposed_weights"], "dry_powder": o["dry_powder_weight"], "start_used": o["start_used"], "turnover": o["turnover_from_current"],
                      "median_CAGR_5Y": y5["median_CAGR"], "ES5": d5["expected_shortfall_5pct"], "P_loss_gt_30pct": d5["P_loss_gt_30pct"], "binding": o["binding_constraints"], "violations": o["violations_at_optimum"],
                      "current_under_phase": {"median_CAGR_5Y": cur["median_CAGR"], "ES5": cur["expected_shortfall_5pct"], "P_loss_gt_30pct": cur["P_loss_gt_30pct"]},
                      "candidates": [(c["start"], c["feasible"], c["median_CAGR_5Y"], c["ES5"]) for c in o["candidates"]]}
    save()
    print(f"[{key}] optimum {r['run_id'][-6:]} {time.time() - t0:.0f}s feasible {o['feasible']} start {o['start_used']} | медиана {y5['median_CAGR']:+.3f} ES5 {d5['expected_shortfall_5pct']:+.3f} P(l30) {d5['P_loss_gt_30pct']:.3f} | текущие под фазой: медиана {cur['median_CAGR']:+.3f} ES5 {cur['expected_shortfall_5pct']:+.3f} | turnover {o['turnover_from_current']} | веса {{k: v for k, v in o['proposed_weights'].items() if v > 0}} dp {o['dry_powder_weight']} | связывающие {o['binding_constraints']}", flush=True)
print("DONE", flush=True)
