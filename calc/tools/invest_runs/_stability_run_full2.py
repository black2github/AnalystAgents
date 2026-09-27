"""Stability Test — срез 2 (пересимуляция) через сайдкар: семейства terminal (точная маржа ±5 п.п. через margin_shift и
мультипликатор ±20 %), milestone (±10 п.п. вероятности вех у RKLB) и driver_knockout (материальные драйверы: knockout у
компаний с положительной экспозицией). Частичный прогон (partial=true), 12 бумаг, 100k путей (2 чанка по 50k → выравнивание
с нормативными прогонами 500k). Входы оптимизатора — _opt_inputs.json (заход 4)."""
import json
import sys
import time
import urllib.request
from pathlib import Path

import yaml

S = Path(__file__).parent; WS = Path("C:/openclaw-lab/data/workspace-invest"); URL = "http://127.0.0.1:18791/run"
CAL = {"SPCX": "spacex/mc_calibration_v1.1.2.yaml", "NBIS": "nbis/mc_calibration_v1.0.2.yaml", "NVDA": "nvda/mc_calibration_v1.0.2.yaml", "HOOD": "hood/mc_calibration_v1.0.1.yaml",
       "RKLB": "rklb/mc_calibration_v1.0.1.yaml", "LLY": "lly/mc_calibration_v1.0.yaml", "META": "meta/mc_calibration_v1.0.1.yaml", "ASML": "asml/mc_calibration_v1.0.1.yaml",
       "MSFT": "msft/mc_calibration_v1.0.yaml", "PLTR": "pltr/mc_calibration_v1.0.yaml", "NET": "net/mc_calibration_v1.0.yaml", "ETN": "etn/mc_calibration_v1.0.1.yaml"}
NORM = {"SPCX": "20260924T073336Z-company_mc-e55d7d", "NBIS": "20260924T073647Z-company_mc-0daf30", "NVDA": "20260924T073919Z-company_mc-d5afc5", "HOOD": "20260924T074150Z-company_mc-038894",
        "RKLB": "20260924T074358Z-company_mc-224958", "LLY": "20260924T074630Z-company_mc-89318c", "META": "20260924T074844Z-company_mc-965cab", "ASML": "20260924T075104Z-company_mc-aa8132",
        "MSFT": "20260924T175814Z-company_mc-a26670", "PLTR": "20260924T180209Z-company_mc-460fe8", "NET": "20260924T180403Z-company_mc-a8783a", "ETN": "20260924T183027Z-company_mc-c0c4ef"}
FOLDER = {"SPCX": "spacex"}
FAMILIES = [a for a in sys.argv[1:]] or ["return_shift", "terminal", "correlation", "combined", "loo", "milestone", "driver_knockout"]

inp = json.load(open(S / "_opt_inputs.json", encoding="utf-8"))
inp["paths_files"] = {k: v.replace("C:/openclaw-lab/data/workspace-invest/", "/data/workspace-invest/") for k, v in inp["paths_files"].items()}
spec = yaml.safe_load((WS / "methodology" / "Joint_Simulation_Layer_Schema_v1.0.yaml").read_text(encoding="utf-8"))
cals, e0, milestones, expo = {}, {}, [], {}
for tk, f in CAL.items():
    c = yaml.safe_load(open(WS / "portfolio" / f, encoding="utf-8")); cals[tk] = c
    e0[tk] = json.load(open(WS / "portfolio/_runs" / f"{NORM[tk]}.json", encoding="utf-8"))["inputs"]["equity_value_0"]
    if "milestone_model" in c:
        milestones.append(tk)
    m = yaml.safe_load(open(WS / "portfolio" / FOLDER.get(tk, tk.lower()) / "mpc_inputs.yaml", encoding="utf-8"))
    expo[tk] = {d: int(v) for d, v in m["driver_exposure_vector"].items() if v}
inp["stability"] = {"families": FAMILIES, "max_paths": 100000, "search_paths": 100000, "milestone_companies": milestones, "driver_exposures": expo,
                    "central_run_ref": "20260924T183808Z-portfolio_optimizer-d58516", "supersedes": ["20260924T233153Z-portfolio_stability-86cfbf", "20260925T072809Z-portfolio_stability-f3468c"], "combined_runs": 500,
                    "resimulate": {"calibrations": cals, "equity_value_0": e0, "joint_layer_spec": spec, "global_seed": 20260920, "chunk": 50000, "milestone_pp": 0.10},
                    "universe_note": "нормативный прогон с пересимуляцией: все семейства, 12 бумаг (94.5 % NAV), маржа точно, вехи, knockout"}
print("companies", len(cals), "| milestones", milestones, "| families", FAMILIES, flush=True)
t0 = time.time()
req = urllib.request.Request(URL, data=json.dumps({"model": "portfolio_stability", "inputs": inp, "seed": 20260924, "save": True}).encode(), headers={"Content-Type": "application/json"})
r = json.load(urllib.request.urlopen(req, timeout=12 * 3600)); o = r["outputs"]
print(f"run {r['run_id']} | {time.time() - t0:.0f} s | версия {o['model_version']} partial {o['partial']} resimulate {o['resimulate']} check {o.get('resimulate_check')} | runs {o['runs_total']} {o['runs_by_family']} | feasibility {o['feasibility_rate']}")
print("central:", o["central"]["weights"], "dp", o["central"]["dry_powder"], "| median", round(o["central"]["median_CAGR_5Y"], 4))
ts = o["terminal_sensitivity"]
for t in sorted(ts):
    mg = ts[t].get("margin"); ms = ts[t].get("milestone_probability")
    if isinstance(mg, dict) and mg:
        print(f"  {t} маржа: " + " | ".join(f"{k}: вес {v['weight']} медиана порт. {v['median_CAGR_5Y']:.4f}, компания {v.get('company_summary', {}).get('median_CAGR_5Y', float('nan')):+.3f}" for k, v in mg.items()))
    if isinstance(ms, dict) and ms:
        print(f"  {t} вехи: " + " | ".join(f"{k}: вес {v['weight']} медиана порт. {v['median_CAGR_5Y']:.4f}, компания {v.get('company_summary', {}).get('median_CAGR_5Y', float('nan')):+.3f}" for k, v in ms.items()))
ds = o["driver_sensitivity"]; print("knockout status:", ds["status"])
for d, v in (ds.get("runs") or {}).items():
    print(f"  KO {d}: feasible {v['feasible']} | компании {v['companies']} | медиана порт. {v['median_CAGR_5Y']:.4f} ES5 {v['ES5']:+.3f} | оборот {v['turnover_from_central']:.3f} | веса {v['weights']} | Δ компаний: " + ", ".join(f"{t} {s['median_CAGR_5Y']:+.3f}" for t, s in v['company_summaries'].items()))
print("критерий knockout:", o["portfolio_stability_classification"]["criteria"]["driver_knockout_feasible_replacement"])
print("классы:", {t: c["class"] for t, c in o["company_stability_classification"].items()})
json.dump(o, open(S / "_stability_full2.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
