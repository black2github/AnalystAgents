"""Нормативный сценарный раунд 2 под Joint v1.1 (25.09): 14 компаний (переиздания NBIS/NVDA v1.0.3, MSFT v1.0.1, META v1.0.2, ASML v1.0.2; RKLB BASE перепрогнан под v1.1; ETN v1.0.2 и SPOT v1.0 — партия 6; итого 15 компаний) × {TAIWAN_SEIZURE, CHIP_COLD_WAR} × 500k путей на общих
шоках (global_seed 20260920, chunk 50000; BASE — принятые нормативные прогоны), store_paths, save=True. Затем portfolio_paths в
режиме смеси с probability null (pending_owner_judgment) — по-сценарные метрики и дельты к BASE на текущих весах и на оптимуме
захода 4. Вероятности не заданы → смесь, impacts и ScenarioConcentration недоступны (§2)."""
import json
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

import yaml

S = Path(__file__).parent; WS = Path("C:/openclaw-lab/data/workspace-invest"); URL = "http://127.0.0.1:18791/run"
CAL = {"SPCX": ("spacex", "mc_calibration_v1.1.2.yaml"), "NBIS": ("nbis", "mc_calibration_v1.0.3.yaml"), "NVDA": ("nvda", "mc_calibration_v1.0.3.yaml"), "HOOD": ("hood", "mc_calibration_v1.0.1.yaml"),
       "RKLB": ("rklb", "mc_calibration_v1.0.1.yaml"), "LLY": ("lly", "mc_calibration_v1.0.yaml"), "META": ("meta", "mc_calibration_v1.0.2.yaml"), "ASML": ("asml", "mc_calibration_v1.0.2.yaml"),
       "MSFT": ("msft", "mc_calibration_v1.0.1.yaml"), "PLTR": ("pltr", "mc_calibration_v1.0.yaml"), "NET": ("net", "mc_calibration_v1.0.yaml"), "ETN": ("etn", "mc_calibration_v1.0.2.yaml"), "ASTS": ("asts", "mc_calibration_v1.0.yaml"), "CRWV": ("crwv", "mc_calibration_v1.0.1.yaml"), "SPOT": ("spot", "mc_calibration_v1.0.yaml")}
NORM = {"SPCX": "20260924T073336Z-company_mc-e55d7d", "NBIS": "20260924T073647Z-company_mc-0daf30", "NVDA": "20260924T073919Z-company_mc-d5afc5", "HOOD": "20260924T074150Z-company_mc-038894",
        "RKLB": "20260924T074358Z-company_mc-224958", "LLY": "20260924T074630Z-company_mc-89318c", "META": "20260924T074844Z-company_mc-965cab", "ASML": "20260924T075104Z-company_mc-aa8132",
        "MSFT": "20260924T175814Z-company_mc-a26670", "PLTR": "20260924T180209Z-company_mc-460fe8", "NET": "20260924T180403Z-company_mc-a8783a", "ETN": "20260924T183027Z-company_mc-c0c4ef", "ASTS": "20260925T082018Z-company_mc-17e2e2", "CRWV": "20260925T115341Z-company_mc-a1b31f"}
NORM.update(json.load(open(S / "_norm_runs_joint11.json", encoding="utf-8")))   # NBIS/NVDA/MSFT/META/ASML/RKLB под Joint v1.1
SCEN = {"TAIWAN_SEIZURE": "TAIWAN_SEIZURE_v1.0.yaml", "CHIP_COLD_WAR": "CHIP_COLD_WAR_v1.0.yaml"}
ONLY = [a for a in sys.argv[1:] if a in SCEN] or list(SCEN)


def post(payload):
    req = urllib.request.Request(URL, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=12 * 3600) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode("utf-8", "replace")[:600]}


spec = yaml.safe_load((WS / "methodology" / "Joint_Simulation_Layer_Schema_v1.1.yaml").read_text(encoding="utf-8"))
res_path = S / "_scenario_normative2.json"; RES = json.load(open(res_path, encoding="utf-8")) if res_path.exists() else {}
for sid in ONLY:
    scen = yaml.safe_load((WS / "portfolio/_scenarios" / SCEN[sid]).read_text(encoding="utf-8")); RES.setdefault(sid, {})
    print(f"===== {sid} =====", flush=True)
    for tk, (folder, fname) in CAL.items():
        if tk in RES[sid] and RES[sid][tk].get("run_id"):
            continue
        cal = yaml.safe_load((WS / "portfolio" / folder / fname).read_text(encoding="utf-8"))
        eq0 = json.load(open(WS / "portfolio/_runs" / f"{NORM[tk]}.json", encoding="utf-8"))["inputs"]["equity_value_0"]
        t0 = time.time()
        r = post({"model": "company_mc", "inputs": {"calibration": cal, "equity_value_0": eq0, "joint_layer_spec": spec, "paths": 500000, "chunk": 50000, "convergence_check": False, "robustness": False, "store_paths": True, "scenario": scen}, "seed": 20260920, "save": True})
        if r.get("error"):
            print(f"  {tk}: ERROR {r['error'][:200]}", flush=True); RES[sid][tk] = {"error": r["error"][:300]}; continue
        o = r["outputs"]; b = o["base"]; q = b["return"]["CAGR_5Y_quantiles"]; js = o["joint_simulation"]
        rec = {"run_id": r["run_id"], "paths_file": o["paths_file"], "median_CAGR_5Y": b["return"]["median_CAGR_5Y"], "q05": q["0.05"], "q95": q["0.95"], "P_loss_gt_30pct_5Y": b["downside"]["P_loss_gt_30pct_5Y"],
               "P_loss_gt_50pct_5Y": b["downside"]["P_loss_gt_50pct_5Y"], "ES5": b["downside"]["expected_shortfall_5pct_5Y"], "P_2x_5Y": b["return"]["P_2x_5Y"], "scenario_mode": js.get("scenario_mode"),
               "unmapped": (js.get("scenario_phases") or {}).get("scenario_drivers_unmapped"), "applicable": (js.get("scenario_phases") or {}).get("scenario_drivers_applicable")}
        RES[sid][tk] = rec; json.dump(RES, open(res_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"  {tk}: {r['run_id'][-6:]} {time.time() - t0:.0f}s | median {rec['median_CAGR_5Y']:+.3f} q5..q95 {rec['q05']:+.3f}..{rec['q95']:+.3f} P(l30) {rec['P_loss_gt_30pct_5Y']:.3f} ES5 {rec['ES5']:+.3f} | unmapped {rec['unmapped']}", flush=True)
# портфель: по-сценарные метрики (вероятности pending)
p = yaml.safe_load((WS / "portfolio/_portfolio.yaml").read_text(encoding="utf-8")); wcur = p["machine_outputs"]["current_weights"]; cash_w = round(1.0 - sum(wcur.values()), 4)
opt = json.load(open(WS / "portfolio/_runs/20260924T183808Z-portfolio_optimizer-d58516.json", encoding="utf-8"))["outputs"]
w_opt = {t: w for t, w in opt["proposed_weights"].items() if w > 0}; dp_opt = opt["dry_powder_weight"]
base_files = {tk: f"/data/workspace-invest/portfolio/_runs/{NORM[tk]}-paths.npz" for tk in CAL}
if all(all(RES.get(sid, {}).get(tk, {}).get("paths_file") for tk in CAL) for sid in SCEN):
    scen_list = [{"id": "BASE", "paths_files": base_files}] + [{"id": sid, "probability": None, "paths_files": {tk: RES[sid][tk]["paths_file"] for tk in CAL}} for sid in SCEN]
    for label, w, dp in (("current", {tk: wcur[tk] for tk in CAL}, cash_w), ("optimum_run4", w_opt, dp_opt)):
        w = {tk: x for tk, x in w.items() if tk in CAL}
        s = sum(w.values()) + dp
        r = post({"model": "portfolio_paths", "inputs": {"scenarios": scen_list, "weights": {tk: x / s for tk, x in w.items()}, "dry_powder_weight": dp / s, "dry_powder_return_annual": 0.04}, "seed": 0, "save": True})
        if r.get("error"):
            print(f"портфель [{label}] ERROR {r['error'][:300]}"); continue
        o = r["outputs"]; RES.setdefault("portfolio", {})[label] = {"run_id": r["run_id"], "by_scenario": o["by_scenario"], "delta": o["scenario_delta_vs_BASE"], "status": o["probability_status"]}
        print(f"портфель [{label}] {r['run_id'][-6:]} ({o['probability_status']}): " + " | ".join(f"{sid}: median {m['Y5']['median_CAGR']:+.3f} P(l30) {m['Y5']['P_loss_gt_30pct']:.3f} ES5 {m['Y5']['expected_shortfall_5pct']:+.3f}" for sid, m in o["by_scenario"].items()), flush=True)
    json.dump(RES, open(res_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("DONE", flush=True)
