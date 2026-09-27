"""Интеграция принятых калибровок MC v1.1.2 / v1.0.2 и RV v1.0 в папки компаний (роль интегратора).
Копирует файлы из from_imma, добавляет записи calc_runs и info_log в state.json (дамп-идемпотентные файлы — полная
перезапись json.dumps indent=2; иначе отказ), переводит стадию NBIS/NVDA в _candidates.yaml (построчно).
Запуск: python _integrate_calibrations.py <workspace> <spcx_run> <nbis_run> <nvda_run> [--apply]"""
import json
import re
import sys
from pathlib import Path

WS = Path(sys.argv[1]); RUNS = {"SPCX": sys.argv[2], "NBIS": sys.argv[3], "NVDA": sys.argv[4]}; APPLY = "--apply" in sys.argv
RV_RUNS = {"NBIS": "20260923T133421Z-reverse_valuation-ba01b6", "NVDA": "20260923T133451Z-reverse_valuation-012879"}
SRC12 = WS / "from_imma" / "MC_v1.1.2_reissue"; SRCBC = WS / "from_imma" / "MC_v1.1_partBC"
PLAN = {
    "SPCX": ("spacex", [(SRC12 / "SPCX_mc_calibration_v1.1.2.yaml", "mc_calibration_v1.1.2.yaml")]),
    "NBIS": ("nbis", [(SRCBC / "NBIS_calibration_v1.0.yaml", "calibration_v1.0.yaml"), (SRC12 / "NBIS_mc_calibration_v1.0.2.yaml", "mc_calibration_v1.0.2.yaml")]),
    "NVDA": ("nvda", [(SRCBC / "NVDA_calibration_v1.0.yaml", "calibration_v1.0.yaml"), (SRC12 / "NVDA_mc_calibration_v1.0.2.yaml", "mc_calibration_v1.0.2.yaml")]),
}
NOW = "2026-09-23T15:00:00Z"


def run_record(run_id: str) -> dict:
    return json.load(open(WS / "portfolio" / "_runs" / f"{run_id}.json", encoding="utf-8"))


def mc_entry(tk: str, rid: str, cal_name: str) -> dict:
    r = run_record(rid); o = r["outputs"]; b = o["base"]; q = b["return"]["CAGR_5Y_quantiles"]; rb = o.get("robustness") or {}
    return {"run_id": rid, "model": "company_mc", "version": o.get("model_version"), "timestamp": r["run_id"][:15].replace("T", "T"),
            "spec": "Company_Conditional_Monte_Carlo_Specification_v1.1 + v1.1.2 (Joint_Simulation_Layer_Rules_v1.1/v1.1.1)",
            "calibration": cal_name, "purpose": "нормативный прогон принятой калибровки (валидатор: схема v1.0.1, MC-G5-013 pass, дисперсия в ориентирах)",
            "equity_value_0_b": round(r["inputs"]["equity_value_0"] / 1e9, 1), "paths": r["inputs"].get("paths") or 500000, "seed": r["seed"],
            "summary": {"median_CAGR_3Y": round(b["return"]["median_CAGR_3Y"], 4), "median_CAGR_5Y": round(b["return"]["median_CAGR_5Y"], 4), "median_CAGR_8Y": round(b["return"]["median_CAGR_8Y"], 4),
                        "CAGR_5Y_q05_q95": [round(q["0.05"], 3), round(q["0.95"], 3)], "P_2x_5Y": round(b["return"]["P_2x_5Y"], 4), "P_loss_gt_30pct_5Y": round(b["downside"]["P_loss_gt_30pct_5Y"], 4),
                        "P_loss_gt_50pct_5Y": round(b["downside"]["P_loss_gt_50pct_5Y"], 4), "ES5": round(b["downside"]["expected_shortfall_5pct_5Y"], 4),
                        "median_equity_value_5Y_b": round(b["median_equity_value_5Y_b"], 1), "RV_Growth_Gap": round(b["gap_metrics"]["RV_Growth_Gap"], 4), "Price_Expectation_Gap": round(b["gap_metrics"]["Price_Expectation_Gap"], 4),
                        "convergence_stable": (o.get("convergence") or {}).get("stable"), "robustness_pass": rb.get("pass"), "robustness_shares": [rb.get("same_sign_share"), rb.get("within_delta_tolerance_share")]},
            "paths_file": (o.get("paths_file") or "").replace("/data/workspace-invest/", "")}


def rv_entry(tk: str, rid: str) -> dict:
    r = run_record(rid); o = r["outputs"]; c = o["calculated"]; ms = o.get("model_stability") or {}
    return {"run_id": rid, "model": f"reverse_valuation {o.get('model_version')}", "spec": o.get("spec_version"), "calibration": f"{tk}_calibration_v1.0", "valuation_date": r["inputs"].get("valuation_date"),
            "price": r["inputs"]["market"]["price"], "shares_outstanding": r["inputs"]["market"]["shares_outstanding"], "equity_value_b": round(c["equity_value"] / 1e9, 2),
            "implied_revenue_cagr_5y": round(c["implied_revenue_cagr_5y"], 4), "terminal_value_share_of_pv": round(c["terminal_value_share_of_pv"], 4), "model_stability": ms.get("class"),
            "note": "Первый нормативный RV-прогон; класс устойчивости по Reverse_Valuation_Rules_v1.1 §1 — " + str(ms.get("class")) + ("; при model_fragile Decision Request обязан содержать флаг риска модели и сетку чувствительности" if ms.get("class") == "model_fragile" else "")}


changes = []
for tk, (folder, files) in PLAN.items():
    fd = WS / "portfolio" / folder
    for src, name in files:
        dst = fd / name
        if not dst.exists() or dst.read_bytes() != src.read_bytes():
            changes.append(f"{folder}/{name} ← {src.name}")
            if APPLY: dst.write_bytes(src.read_bytes())
    sp = fd / "state.json"; raw = open(sp, encoding="utf-8", newline="").read(); st = json.loads(raw)
    idem = json.dumps(st, ensure_ascii=False, indent=2) + "\n" == raw.replace("\r\n", "\n")
    entries = [e for e in [rv_entry(tk, RV_RUNS[tk]) if tk in RV_RUNS else None, mc_entry(tk, RUNS[tk], files[-1][1])] if e]
    have = {e.get("run_id") for e in st.get("calc_runs", [])}
    new = [e for e in entries if e["run_id"] not in have]
    if new:
        if not idem:
            changes.append(f"{folder}/state.json: НЕ идемпотентен для дампа — записи calc_runs НЕ добавлены (нужен построчный патч)")
        else:
            changes.append(f"{folder}/state.json: +{len(new)} calc_runs ({', '.join(e['run_id'] for e in new)})")
            if APPLY:
                st.setdefault("calc_runs", []).extend(new)
                st.setdefault("info_log", []).append({"timestamp": NOW, "kind": "calc", "summary": f"Интеграция калибровок (23.09): {', '.join(n for _, n in files)} приняты (валидатор режим calibration pass); нормативные прогоны: " + ", ".join(e["run_id"] for e in new) + (". Прежний норматив SPCX conditional_mc …-861006 и сравнительный …-e169f2 — исторические" if tk == "SPCX" else "")})
                st["updated"] = NOW
                with open(sp, "w", encoding="utf-8", newline="\r\n" if "\r\n" in raw else "\n") as fh:
                    fh.write(json.dumps(st, ensure_ascii=False, indent=2) + "\n")
# _candidates.yaml: стадия NBIS/NVDA → conditional_mc; SPCX note
cp = WS / "portfolio" / "_candidates.yaml"; raw = cp.read_bytes(); text = raw.decode("utf-8").replace("\r\n", "\n"); out = text
for tk in ("NBIS", "NVDA"):
    out = re.sub(rf"(\{{ticker: {tk},[^\n]*?stage: )company_model", rf"\1conditional_mc", out, count=1)
if out != text:
    changes.append("_candidates.yaml: NBIS/NVDA stage company_model → conditional_mc")
    if APPLY: cp.write_bytes((out.replace("\n", "\r\n") if b"\r\n" in raw else out).encode("utf-8"))
for c in changes: print("-", c)
print("режим:", "ЗАПИСЬ" if APPLY else "сухой прогон")
