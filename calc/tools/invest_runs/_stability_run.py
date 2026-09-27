"""Portfolio Stability Test — прогон через сайдкар (24.09): входы оптимизатора из _opt_inputs.json (та же постановка, что заход 2:
Stress, фиксированные некалиброванные 11.6 % NAV, лимиты approved_limits_v1_0, потолки по Conviction Overlay) + слой stability:
терминальные маржи из калибровок (A: terminal_margin_Y5.mode; B: ocf_Y5 − capex_Y5; SPCX: nodes.Y5.mode; RKLB: service_margin),
экспозиции драйверов из mpc_inputs, вехи — RKLB. Режимы: smoke (combined 3, 20k путей, без записи) | full (500, 100k, save=true)."""
import json
import sys
import time
import urllib.request
from pathlib import Path

import yaml

MODE = sys.argv[1] if len(sys.argv) > 1 else "smoke"
S = Path(__file__).parent; WS = Path("C:/openclaw-lab/data/workspace-invest"); URL = "http://127.0.0.1:18791/run"
CAL = {"SPCX": "spacex/mc_calibration_v1.1.2.yaml", "NBIS": "nbis/mc_calibration_v1.0.2.yaml", "NVDA": "nvda/mc_calibration_v1.0.2.yaml", "HOOD": "hood/mc_calibration_v1.0.1.yaml",
       "RKLB": "rklb/mc_calibration_v1.0.1.yaml", "LLY": "lly/mc_calibration_v1.0.yaml", "META": "meta/mc_calibration_v1.0.1.yaml", "ASML": "asml/mc_calibration_v1.0.1.yaml",
       "MSFT": "msft/mc_calibration_v1.0.yaml", "PLTR": "pltr/mc_calibration_v1.0.yaml", "NET": "net/mc_calibration_v1.0.yaml", "ETN": "etn/mc_calibration_v1.0.1.yaml"}
FOLDER = {"SPCX": "spacex"}


def mode(x):
    return x.get("mode", x.get("value", x.get("median")))


inp = json.load(open(S / "_opt_inputs.json", encoding="utf-8"))
inp["paths_files"] = {k: v.replace("C:/openclaw-lab/data/workspace-invest/", "/data/workspace-invest/") for k, v in inp["paths_files"].items()}
margins, milestones = {}, []
for tk, f in CAL.items():
    c = yaml.safe_load(open(WS / "portfolio" / f, encoding="utf-8")); mm = c.get("margin_model") or {}; cm = c.get("cash_model") or {}
    if mm.get("method") == "mean_reverting_positive_margin":
        margins[tk] = mode(mm["terminal_margin_Y5"])
    elif mm.get("method") == "ocf_capex_decomposition":
        margins[tk] = round(mode(mm["ocf_margin_nodes"]["Y5"]) - mode(mm["capex_revenue_nodes"]["Y5"]), 4)
    elif mm.get("method") == "direct_fcf_nodes":
        margins[tk] = mode(mm["nodes"]["Y5_terminal_margin"])
    elif cm.get("service_margin"):
        margins[tk] = mode(cm["service_margin"]["terminal_margin_Y5"])
    if "milestone_model" in c:
        milestones.append(tk)
expo = {}
for tk in CAL:
    m = yaml.safe_load(open(WS / "portfolio" / FOLDER.get(tk, tk.lower()) / "mpc_inputs.yaml", encoding="utf-8"))
    expo[tk] = {d: int(v) for d, v in m["driver_exposure_vector"].items() if v}
stab = {"terminal_margins": margins, "milestone_companies": milestones, "driver_exposures": expo, "central_run_ref": "20260924T183808Z-portfolio_optimizer-d58516", "supersedes": ["20260924T113548Z-portfolio_stability-f42e9b"], "universe_note": "заход 4: 12 калиброванных бумаг (94.5 % NAV), партия 4 полностью"}
if MODE == "smoke":
    stab.update({"combined_runs": 3, "max_paths": 20000, "search_paths": 20000}); save = False
else:
    stab.update({"combined_runs": 500, "max_paths": 100000, "search_paths": 100000}); save = True
inp["stability"] = stab
print("margins:", margins, "| milestones:", milestones, "| mode:", MODE, flush=True)
t0 = time.time()
req = urllib.request.Request(URL, data=json.dumps({"model": "portfolio_stability", "inputs": inp, "seed": 20260924, "save": save}).encode(), headers={"Content-Type": "application/json"})
r = json.load(urllib.request.urlopen(req, timeout=12 * 3600))
o = r["outputs"]; print(f"run {r.get('run_id')} | {time.time() - t0:.0f} s | runs {o['runs_total']} {o['runs_by_family']} | valid {o['valid_runs']} | feasibility {o['feasibility_rate']}")
print("central:", o["central"]["weights"], "dp", o["central"]["dry_powder"], "| median", round(o["central"]["median_CAGR_5Y"], 4), "ES5", round(o["central"]["ES5"], 4))
print("inclusion:", o["inclusion_frequency_by_asset"])
print("weights p10/p50/p90:", o["weight_p10_p50_p90"])
print("classes:", {t: c["class"] for t, c in o["company_stability_classification"].items()})
print("portfolio:", o["portfolio_stability_classification"]["class"], {k: (c["value"], c["pass"]) for k, c in o["portfolio_stability_classification"]["criteria"].items()})
print("turnover:", o["turnover_distribution"], "| binding freq:", o["binding_constraint_frequency"])
print("corr:", {k: (v["feasible"], round(v["median_CAGR_5Y"], 4), round(v["achieved_mean_offdiag_shift"], 3), v["psd_repaired"]) for k, v in o["correlation_sensitivity"]["runs"].items()})
print("LOO:", {t: (v["feasible"], round(v["median_CAGR_5Y_delta_vs_central"], 4), round(v["turnover_from_central"], 3)) for t, v in o["leave_one_out"].items()})
print("material drivers:", o["driver_sensitivity"]["material_drivers"])
print("combined:", {k: v for k, v in o["combined"].items() if k != "runs_detail"})
json.dump(o, open(S / f"_stability_{MODE}.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
