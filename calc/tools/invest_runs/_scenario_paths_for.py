"""Пути бумаг под сценариями TS/CW/Q и условными фазами части B для списка тикеров из argv (папка и действующий mc_file — из
portfolio/_calibration_lifecycle.yaml); обобщение _candidate_scenario_paths.py (карты RES2 / RES3 / partB дополняются). Возобновляемый.
Запуск: python _scenario_paths_for.py ETN MSFT NET PLTR"""
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

import yaml

S = Path(__file__).parent; WS = Path("C:/openclaw-lab/data/workspace-invest"); URL = "http://127.0.0.1:18791/run"
import sys
_life = yaml.safe_load((WS / "portfolio/_calibration_lifecycle.yaml").read_text(encoding="utf-8"))
_ALL = {c["ticker"]: (c["folder"], c["mc_file"]) for c in _life["calibrations"]}
CAL = {tk: _ALL[tk] for tk in (sys.argv[1:] or ["CRWD", "HPS.A", "S"])}   # тикеры из argv; папка и действующий mc_file — из lifecycle-реестра
NORM = json.load(open(S / "_norm_runs_joint11.json", encoding="utf-8"))
SCEN_FILES = {"TAIWAN_SEIZURE": "TAIWAN_SEIZURE_v1.1.1.yaml", "CHIP_COLD_WAR": "CHIP_COLD_WAR_v1.1.1.yaml", "TAIWAN_QUARANTINE": "TAIWAN_QUARANTINE_v1.1.1.yaml"}
PHASES = {"TAIWAN_SEIZURE": ["BLOCKADE", "CONFLICT", "RECOVERY"], "TAIWAN_QUARANTINE": ["QUARANTINE", "NORMALIZATION_OR_FROZEN"]}
P2 = S / "_scenario_normative2.json"; P3 = S / "_scenario_round3.json"; PB = S / "_conditional_runs_partB.json"
RES2 = json.load(open(P2, encoding="utf-8")); RES3 = json.load(open(P3, encoding="utf-8")); RESB = json.load(open(PB, encoding="utf-8"))
spec = yaml.safe_load((WS / "methodology" / "Joint_Simulation_Layer_Schema_v1.1.yaml").read_text(encoding="utf-8"))


def post(payload):
    req = urllib.request.Request(URL, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=4 * 3600) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode("utf-8", "replace")[:600]}


def save():
    json.dump(RES2, open(P2, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(RES3, open(P3, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(RESB, open(PB, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def run_company(tk, scen, phase=None):
    folder, fname = CAL[tk]
    cal = yaml.safe_load((WS / "portfolio" / folder / fname).read_text(encoding="utf-8"))
    eq0 = json.load(open(WS / "portfolio/_runs" / f"{NORM[tk]}.json", encoding="utf-8"))["inputs"]["equity_value_0"]
    inp = {"calibration": cal, "equity_value_0": eq0, "joint_layer_spec": spec, "paths": 500000, "chunk": 50000, "convergence_check": False, "robustness": False, "store_paths": True, "scenario": scen}
    if phase:
        inp["conditional_run"] = {"confirmed_phase": phase}
    t0 = time.time()
    r = post({"model": "company_mc", "inputs": inp, "seed": 20260920, "save": True})
    if r.get("error"):
        return {"error": r["error"][:300]}, time.time() - t0
    o = r["outputs"]; b = o["base"]; q = b["return"]["CAGR_5Y_quantiles"]; js = o["joint_simulation"]; cr = o.get("conditional_run") or {}
    rec = {"run_id": r["run_id"], "paths_file": o["paths_file"], "median_CAGR_5Y": b["return"]["median_CAGR_5Y"], "q05": q["0.05"], "q95": q["0.95"], "P_loss_gt_30pct_5Y": b["downside"]["P_loss_gt_30pct_5Y"],
           "P_loss_gt_50pct_5Y": b["downside"]["P_loss_gt_50pct_5Y"], "ES5": b["downside"]["expected_shortfall_5pct_5Y"], "P_2x_5Y": b["return"]["P_2x_5Y"], "scenario_mode": js.get("scenario_mode"),
           "unmapped": (js.get("scenario_phases") or {}).get("scenario_drivers_unmapped"), "applicable": (js.get("scenario_phases") or {}).get("scenario_drivers_applicable"), "scenario_calibration": SCEN_FILES[scen["scenario_id"]] if scen.get("scenario_id") else None}
    if phase:
        rec.update({"state_at_t0": cr.get("state_at_t0"), "historical_phases": cr.get("historical_phases")})
    return rec, time.time() - t0


def line(tag, rec, dt):
    if "error" in rec:
        return f"  {tag}: ERROR {rec['error'][:200]}"
    return f"  {tag}: {rec['run_id'][-6:]} {dt:.0f}s | median {rec['median_CAGR_5Y']:+.3f} q5..q95 {rec['q05']:+.3f}..{rec['q95']:+.3f} P(l30) {rec['P_loss_gt_30pct_5Y']:.3f} ES5 {rec['ES5']:+.3f} | mode {rec.get('scenario_mode')} | unmapped {rec.get('unmapped')}"


scen_docs = {sid: yaml.safe_load((WS / "portfolio/_scenarios" / f).read_text(encoding="utf-8")) for sid, f in SCEN_FILES.items()}
# (а) сценарии: TS/CW → RES2, Q → RES3
for sid in ("TAIWAN_SEIZURE", "CHIP_COLD_WAR", "TAIWAN_QUARANTINE"):
    target = RES3 if sid == "TAIWAN_QUARANTINE" else RES2
    target.setdefault(sid, {})
    for tk in CAL:
        if target[sid].get(tk, {}).get("run_id"):
            continue
        rec, dt = run_company(tk, scen_docs[sid])
        target[sid][tk] = rec; save(); print(line(f"{sid}/{tk}", rec, dt), flush=True)
# (б) условные фазы → RESB companies (+ RESTRICTIONS = пути сценария)
for sid, phases in PHASES.items():
    key0 = f"{sid}|RESTRICTIONS"; RESB.setdefault(key0, {"companies": {}})
    for tk in CAL:
        src = (RES3 if sid == "TAIWAN_QUARANTINE" else RES2)[sid].get(tk, {})
        if src.get("paths_file") and not RESB[key0]["companies"].get(tk, {}).get("paths_file"):
            RESB[key0]["companies"][tk] = {"paths_file": src["paths_file"], "run_id": None, "note": "RESTRICTIONS = fixed_quarter 0: условный прогон побитно равен безусловному (пути сценария)"}
    save()
    for pid in phases:
        key = f"{sid}|{pid}"; RESB.setdefault(key, {"companies": {}})
        for tk in CAL:
            if RESB[key]["companies"].get(tk, {}).get("run_id"):
                continue
            rec, dt = run_company(tk, scen_docs[sid], phase=pid)
            RESB[key]["companies"][tk] = rec; save(); print(line(f"{key}/{tk}", rec, dt), flush=True)
print("DONE", flush=True)
