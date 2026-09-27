"""RKLB v1.0.1: нормативный BASE перепрогнан под Joint v1.1 (INDUSTRIAL_RESHORING получил корни; калибровка не менялась) —
запись calc_runs + info_log в portfolio/rklb/state.json (дамп-идемпотентно, как _integrate_batch5.py).
Запуск: python _integrate_rklb_joint11.py <workspace> <run_id> [--apply]"""
import json
import re
import sys
from pathlib import Path


def dump(st: dict, raw: str) -> str:
    one_line = bool(re.search(r'\n\s*\{"kpi_id": ', raw))
    inline_ids = bool(re.search(r'"verification_run_ids": \[[ \t]*"', raw))
    st2 = dict(st); obs = st.get("kpi_observations") or []
    if one_line and obs:
        st2["kpi_observations"] = [f"@@OBS{i}@@" for i in range(len(obs))]
    txt = json.dumps(st2, ensure_ascii=False, indent=2) + "\n"
    if one_line:
        for i, o in enumerate(obs):
            txt = txt.replace(f'"@@OBS{i}@@"', json.dumps(o, ensure_ascii=False))
    if inline_ids:
        txt = re.sub(r'"verification_run_ids": \[\n((?:[ \t]*"[^"\n]*",?\n)+)[ \t]*\]', lambda m: '"verification_run_ids": [' + ", ".join(x.strip().rstrip(",") for x in m.group(1).strip().split("\n")) + "]", txt)
    return txt if raw.endswith("\n") else txt.rstrip("\n")


WS = Path(sys.argv[1]); RID = sys.argv[2]; APPLY = "--apply" in sys.argv; NOW = "2026-09-25T14:00:00Z"
r = json.load(open(WS / "portfolio" / "_runs" / f"{RID}.json", encoding="utf-8")); o = r["outputs"]; b = o["base"]; q = b["return"]["CAGR_5Y_quantiles"]; rb = o.get("robustness") or {}
entry = {"run_id": RID, "model": "company_mc", "version": o.get("model_version"), "timestamp": RID[:15],
         "spec": "Company_Conditional_Monte_Carlo_Specification_v1.1.3 (Joint_Simulation_Layer_Schema v1.1, Rules v1.1.2; company_mc 2.3.2)",
         "calibration": "mc_calibration_v1.0.1.yaml", "supersedes": "20260924T074358Z-company_mc-224958",
         "purpose": "нормативный BASE RKLB v1.0.1 под Joint_Simulation_Layer_Schema v1.1 (INDUSTRIAL_RESHORING получил корни AI_CAPEX_CYCLE/POWER_BUILDOUT/GLOBAL_GROWTH → пути драйвера изменились; калибровка не менялась; валидатор 1.7.0 …-5858af pass под v1.1, post_service_growth σ 0.113/0.15). Отличие от 224958 в пределах шума (P(2x) 0.1206 → 0.1214); прежний прогон остаётся записью воспроизводимости",
         "equity_value_0_b": round(r["inputs"]["equity_value_0"] / 1e9, 1), "paths": r["inputs"].get("paths") or 500000, "seed": r["seed"],
         "summary": {"median_CAGR_3Y": round(b["return"]["median_CAGR_3Y"], 4), "median_CAGR_5Y": round(b["return"]["median_CAGR_5Y"], 4), "median_CAGR_8Y": round(b["return"]["median_CAGR_8Y"], 4),
                     "CAGR_5Y_q05_q95": [round(q["0.05"], 3), round(q["0.95"], 3)], "P_2x_5Y": round(b["return"]["P_2x_5Y"], 4), "P_loss_gt_30pct_5Y": round(b["downside"]["P_loss_gt_30pct_5Y"], 4),
                     "P_loss_gt_50pct_5Y": round(b["downside"]["P_loss_gt_50pct_5Y"], 4), "ES5": round(b["downside"]["expected_shortfall_5pct_5Y"], 4),
                     "median_equity_value_5Y_b": round(b["median_equity_value_5Y_b"], 1), "RV_Growth_Gap": round(b["gap_metrics"]["RV_Growth_Gap"], 4), "Price_Expectation_Gap": round(b["gap_metrics"]["Price_Expectation_Gap"], 4),
                     "convergence_stable": (o.get("convergence") or {}).get("stable"), "robustness_pass": rb.get("pass"), "robustness_shares": [rb.get("same_sign_share"), rb.get("within_delta_tolerance_share")]},
         "paths_file": (o.get("paths_file") or "").replace("/data/workspace-invest/", ""), "valuation_crossover": (b.get("valuation_crossover") or {}).get("mode"), "basis_parity_margin_Y5": (b.get("basis_parity_margin") or {}).get("Y5")}
sp = WS / "portfolio" / "rklb" / "state.json"; raw = open(sp, encoding="utf-8", newline="").read(); st = json.loads(raw)
idem = dump(st, raw.replace("\r\n", "\n")) == raw.replace("\r\n", "\n")
if RID in {e.get("run_id") for e in st.get("calc_runs", [])}:
    print("уже есть"); sys.exit(0)
if not idem:
    print("state.json НЕ идемпотентен для дампа — нужен построчный патч"); sys.exit(1)
print(f"rklb/state.json: +1 calc_runs ({RID}, supersedes 224958) | режим: {'ЗАПИСЬ' if APPLY else 'сухой прогон'}")
if APPLY:
    st.setdefault("calc_runs", []).append(entry)
    st.setdefault("info_log", []).append({"timestamp": NOW, "kind": "calc", "summary": f"Joint_Simulation_Layer_Schema v1.1 принята (25.09): калибровка RKLB v1.0.1 не менялась, валидатор 1.7.0 …-5858af pass под v1.1; нормативный BASE перепрогнан под v1.1: {RID} (supersedes 224958; отличие в пределах шума)"})
    st["updated"] = NOW
    with open(sp, "w", encoding="utf-8", newline="\r\n" if "\r\n" in raw else "\n") as fh:
        fh.write(dump(st, raw.replace("\r\n", "\n")))
