"""Сценарный раунд 3 (25.09 ночь, партия 7): TAIWAN_QUARANTINE v1.0 на 15 компаниях × 500k на общих путях под Joint v1.1 (SPCX — на
v1.1.3, схема 1.0.2) + SPCX v1.1.3 по TAIWAN_SEIZURE и CHIP_COLD_WAR (перепрогон под новую семантику). Затем portfolio_paths: четыре
сценария (BASE, TS 0.10, CW 0.07, QUARANTINE null → pending: только по-сценарные метрики и дельты) на текущих весах и оптимуме захода 5.
Результаты: _scenario_round3.json. Возобновляемый (готовые пропускаются)."""
import json
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

import yaml

S = Path(__file__).parent; WS = Path("C:/openclaw-lab/data/workspace-invest"); URL = "http://127.0.0.1:18791/run"
CAL = {"SPCX": ("spacex", "mc_calibration_v1.1.3.yaml"), "NBIS": ("nbis", "mc_calibration_v1.0.3.yaml"), "NVDA": ("nvda", "mc_calibration_v1.0.3.yaml"), "HOOD": ("hood", "mc_calibration_v1.0.1.yaml"),
       "RKLB": ("rklb", "mc_calibration_v1.0.1.yaml"), "LLY": ("lly", "mc_calibration_v1.0.yaml"), "META": ("meta", "mc_calibration_v1.0.2.yaml"), "ASML": ("asml", "mc_calibration_v1.0.2.yaml"),
       "MSFT": ("msft", "mc_calibration_v1.0.1.yaml"), "PLTR": ("pltr", "mc_calibration_v1.0.yaml"), "NET": ("net", "mc_calibration_v1.0.yaml"), "ETN": ("etn", "mc_calibration_v1.0.2.yaml"),
       "ASTS": ("asts", "mc_calibration_v1.0.yaml"), "CRWV": ("crwv", "mc_calibration_v1.0.1.yaml"), "SPOT": ("spot", "mc_calibration_v1.0.yaml")}
SPCX_SRC = WS / "from_imma/Party7_TAIWAN_QUARANTINE_SPCX_v1.0/SPCX_mc_calibration_v1.1.3.yaml"     # до интеграции — из пакета
NORM = {"HOOD": "20260924T074150Z-company_mc-038894", "LLY": "20260924T074630Z-company_mc-89318c", "PLTR": "20260924T180209Z-company_mc-460fe8", "NET": "20260924T180403Z-company_mc-a8783a",
        "ASTS": "20260925T082018Z-company_mc-17e2e2", "CRWV": "20260925T115341Z-company_mc-a1b31f"}
NORM.update(json.load(open(S / "_norm_runs_joint11.json", encoding="utf-8")))
NORM["SPCX"] = json.load(open(S / "_spcx113_run.json", encoding="utf-8"))["SPCX"]                    # SPCX v1.1.3 норматив
RES2 = json.load(open(S / "_scenario_normative2.json", encoding="utf-8"))                             # раунд 2: TS/CW для 14 компаний (SPCX перепрогоняется)
res_path = S / "_scenario_round3.json"; RES = json.load(open(res_path, encoding="utf-8")) if res_path.exists() else {}
P_TS, P_CW = 0.10, 0.07


def post(payload):
    req = urllib.request.Request(URL, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=12 * 3600) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode("utf-8", "replace")[:600]}


spec = yaml.safe_load((WS / "methodology" / "Joint_Simulation_Layer_Schema_v1.1.yaml").read_text(encoding="utf-8"))
scen_files = {"TAIWAN_SEIZURE": "TAIWAN_SEIZURE_v1.0.yaml", "CHIP_COLD_WAR": "CHIP_COLD_WAR_v1.0.yaml", "TAIWAN_QUARANTINE": "TAIWAN_QUARANTINE_v1.0.yaml"}
jobs = [("TAIWAN_QUARANTINE", tk) for tk in CAL] + [("TAIWAN_SEIZURE", "SPCX"), ("CHIP_COLD_WAR", "SPCX")]
for sid, tk in jobs:
    RES.setdefault(sid, {})
    if RES[sid].get(tk, {}).get("run_id"):
        continue
    folder, fname = CAL[tk]
    cal = yaml.safe_load((SPCX_SRC if tk == "SPCX" and not (WS / "portfolio" / folder / fname).exists() else WS / "portfolio" / folder / fname).read_text(encoding="utf-8"))
    eq0 = json.load(open(WS / "portfolio/_runs" / f"{NORM[tk]}.json", encoding="utf-8"))["inputs"]["equity_value_0"]
    scen = yaml.safe_load((WS / "portfolio/_scenarios" / scen_files[sid]).read_text(encoding="utf-8"))
    t0 = time.time()
    r = post({"model": "company_mc", "inputs": {"calibration": cal, "equity_value_0": eq0, "joint_layer_spec": spec, "paths": 500000, "chunk": 50000, "convergence_check": False, "robustness": False, "store_paths": True, "scenario": scen}, "seed": 20260920, "save": True})
    if r.get("error"):
        print(f"  {sid}/{tk}: ERROR {r['error'][:200]}", flush=True); RES[sid][tk] = {"error": r["error"][:300]}; continue
    o = r["outputs"]; b = o["base"]; q = b["return"]["CAGR_5Y_quantiles"]; js = o["joint_simulation"]
    RES[sid][tk] = {"run_id": r["run_id"], "paths_file": o["paths_file"], "median_CAGR_5Y": b["return"]["median_CAGR_5Y"], "q05": q["0.05"], "q95": q["0.95"], "P_loss_gt_30pct_5Y": b["downside"]["P_loss_gt_30pct_5Y"],
                    "P_loss_gt_50pct_5Y": b["downside"]["P_loss_gt_50pct_5Y"], "ES5": b["downside"]["expected_shortfall_5pct_5Y"], "P_2x_5Y": b["return"]["P_2x_5Y"], "scenario_mode": js.get("scenario_mode"),
                    "unmapped": (js.get("scenario_phases") or {}).get("scenario_drivers_unmapped"), "applicable": (js.get("scenario_phases") or {}).get("scenario_drivers_applicable")}
    json.dump(RES, open(res_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"  {sid}/{tk}: {r['run_id'][-6:]} {time.time() - t0:.0f}s | median {b['return']['median_CAGR_5Y']:+.3f} q5..q95 {q['0.05']:+.3f}..{q['0.95']:+.3f} P(l30) {b['downside']['P_loss_gt_30pct_5Y']:.3f} ES5 {b['downside']['expected_shortfall_5pct_5Y']:+.3f}", flush=True)
# портфель: BASE + TS (0.10) + CW (0.07) + QUARANTINE (null → pending → только по-сценарные метрики)
def pf(sid, tk):
    if sid == "BASE":
        return f"/data/workspace-invest/portfolio/_runs/{NORM[tk]}-paths.npz"
    if tk == "SPCX" or sid == "TAIWAN_QUARANTINE":
        return RES[sid][tk]["paths_file"]
    return RES2[sid][tk]["paths_file"]
if all(RES.get(sid, {}).get(tk, {}).get("paths_file") for sid, tk in jobs):
    scen_list = [{"id": "BASE", "paths_files": {tk: pf("BASE", tk) for tk in CAL}}, {"id": "TAIWAN_SEIZURE", "probability": P_TS, "paths_files": {tk: pf("TAIWAN_SEIZURE", tk) for tk in CAL}},
                 {"id": "CHIP_COLD_WAR", "probability": P_CW, "paths_files": {tk: pf("CHIP_COLD_WAR", tk) for tk in CAL}}, {"id": "TAIWAN_QUARANTINE", "probability": None, "paths_files": {tk: pf("TAIWAN_QUARANTINE", tk) for tk in CAL}}]
    p = yaml.safe_load((WS / "portfolio/_portfolio.yaml").read_text(encoding="utf-8")); wcur = p["machine_outputs"]["current_weights"]; cash_w = round(1.0 - sum(wcur.values()), 4)
    opt = json.load(open(S / "_opt_run5.json", encoding="utf-8")); w_opt = {t: w for t, w in opt["proposed_weights"].items() if w > 0}; dp_opt = opt["dry_powder_weight"]
    for label, w, dp in (("current", {tk: wcur[tk] for tk in CAL}, cash_w), ("optimum_run5", w_opt, dp_opt)):
        w = {tk: x for tk, x in w.items() if tk in CAL}; s = sum(w.values()) + dp
        r = post({"model": "portfolio_paths", "inputs": {"scenarios": scen_list, "weights": {tk: x / s for tk, x in w.items()}, "dry_powder_weight": dp / s, "dry_powder_return_annual": 0.04}, "seed": 0, "save": True})
        if r.get("error"):
            print(f"портфель [{label}] ERROR {r['error'][:300]}", flush=True); continue
        o = r["outputs"]; RES.setdefault("portfolio", {})[label] = {"run_id": r["run_id"], "by_scenario": o["by_scenario"], "delta": o["scenario_delta_vs_BASE"], "status": o["probability_status"]}
        print(f"портфель [{label}] {r['run_id'][-6:]} ({o['probability_status']}): " + " | ".join(f"{sid}: median {m['Y5']['median_CAGR']:+.3f} P(l30) {m['Y5']['P_loss_gt_30pct']:.3f} ES5 {m['Y5']['expected_shortfall_5pct']:+.3f}" for sid, m in o["by_scenario"].items()), flush=True)
    json.dump(RES, open(res_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("DONE", flush=True)
