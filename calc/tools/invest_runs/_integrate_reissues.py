"""Интеграция пяти переизданий под Joint v1.1 (пакет IMMA_Joint_v1.1_Taxonomy_v1.2.1_Company_Reissues): NBIS/NVDA v1.0.3, MSFT v1.0.1,
META v1.0.2, ASML v1.0.2 — файлы в portfolio/<tk>, старая версия mc-файла удаляется из папки (остаётся в from_imma и git), calc_runs +
info_log (в т.ч. патч экспозиций). RV не менялась. Запуск: python _integrate_reissues.py <workspace> NBIS=<run> NVDA=<run> MSFT=<run> META=<run> ASML=<run> [--apply]
Копирует файлы из from_imma, добавляет записи calc_runs и info_log в state.json (дамп-идемпотентные файлы — полная
перезапись json.dumps indent=2; иначе отказ), переводит стадию NBIS/NVDA в _candidates.yaml (построчно).
Запуск: python _integrate_calibrations.py <workspace> <spcx_run> <nbis_run> <nvda_run> [--apply]"""
import json
import re
import sys
from pathlib import Path


def dump(st: dict, raw: str) -> str:
    """Формат файла определяется по содержимому (как _update_calc_runs_232.py): однострочные наблюдения kpi_observations —
    только если они такие в файле; строковые массивы verification_run_ids — в одну строку, если так в файле; завершающий
    перевод строки — как в файле."""
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


import os
WS = Path(sys.argv[1]); RUNS = dict(a.split("=", 1) for a in sys.argv[2:] if "=" in a); APPLY = "--apply" in sys.argv
ONLY = set(RUNS)
RV_RUNS = {}
NEWFILE = {"NBIS": "NBIS_mc_calibration_v1.0.3.yaml", "NVDA": "NVDA_mc_calibration_v1.0.3.yaml", "MSFT": "MSFT_mc_calibration_v1.0.1.yaml", "META": "META_mc_calibration_v1.0.2.yaml", "ASML": "ASML_mc_calibration_v1.0.2.yaml"}
OLDFILE = {"NBIS": "mc_calibration_v1.0.2.yaml", "NVDA": "mc_calibration_v1.0.2.yaml", "MSFT": "mc_calibration_v1.0.yaml", "META": "mc_calibration_v1.0.1.yaml", "ASML": "mc_calibration_v1.0.1.yaml"}
VALRUN = {"NBIS": "dc309a", "NVDA": "cab5d4", "MSFT": "87cf9f", "META": "a5afb8", "ASML": "e551d8"}
DELTA = {"NBIS": "миграция схемы 1.0.1→1.0.2 (parity-gated смесь; migration delta ожидаема) + ACCELERATOR_PRICE_COMPETITION (+1)", "NVDA": "миграция схемы 1.0.1→1.0.2 (parity-gated смесь; migration delta ожидаема) + ACCELERATOR_PRICE_COMPETITION (−2)", "MSFT": "ACCELERATOR_PRICE_COMPETITION (+1) + знаки TAIWAN_SUPPLY исправлены (−1→+1, канон «здоровье поставок»)", "META": "ACCELERATOR_PRICE_COMPETITION (+1) + знаки TAIWAN_SUPPLY исправлены (−1→+1)", "ASML": "ACCELERATOR_PRICE_COMPETITION (−1)"}
SRC2 = WS / "from_imma" / "Joint_v1.1_Taxonomy_v1.2.1_Reissues"
PLAN = {tk: (tk.lower(), [(SRC2 / NEWFILE[tk], NEWFILE[tk].split("_", 1)[1])]) for tk in NEWFILE if tk in ONLY}
NOW = "2026-09-25T14:00:00Z"


def run_record(run_id: str) -> dict:
    return json.load(open(WS / "portfolio" / "_runs" / f"{run_id}.json", encoding="utf-8"))


def mc_entry(tk: str, rid: str, cal_name: str) -> dict:
    r = run_record(rid); o = r["outputs"]; b = o["base"]; q = b["return"]["CAGR_5Y_quantiles"]; rb = o.get("robustness") or {}
    return {"run_id": rid, "model": "company_mc", "version": o.get("model_version"), "timestamp": r["run_id"][:15].replace("T", "T"),
            "spec": "Company_Conditional_Monte_Carlo_Specification_v1.1.3 (Joint_Simulation_Layer_Rules_v1.1.2; company_mc 2.3.2, parity-gated blend)",
            "calibration": cal_name, "purpose": f"нормативный прогон переиздания {tk} {cal_name} под Joint_Simulation_Layer_Schema v1.1 (пакет IMMA 25.09: {DELTA[tk]}; check_supersedes к предыдущей версии — пропаж 0; валидатор 1.7.0 …-{VALRUN[tk]} pass, MC-G5-013 по измеренной σ под Joint v1.1; экспозиции mpc_inputs по Scenario_Company_Exposure_Patch_v1.1, таксономия 1.2.1)",
            "equity_value_0_b": round(r["inputs"]["equity_value_0"] / 1e9, 1), "paths": r["inputs"].get("paths") or 500000, "seed": r["seed"],
            "summary": {"median_CAGR_3Y": round(b["return"]["median_CAGR_3Y"], 4), "median_CAGR_5Y": round(b["return"]["median_CAGR_5Y"], 4), "median_CAGR_8Y": round(b["return"]["median_CAGR_8Y"], 4),
                        "CAGR_5Y_q05_q95": [round(q["0.05"], 3), round(q["0.95"], 3)], "P_2x_5Y": round(b["return"]["P_2x_5Y"], 4), "P_loss_gt_30pct_5Y": round(b["downside"]["P_loss_gt_30pct_5Y"], 4),
                        "P_loss_gt_50pct_5Y": round(b["downside"]["P_loss_gt_50pct_5Y"], 4), "ES5": round(b["downside"]["expected_shortfall_5pct_5Y"], 4),
                        "median_equity_value_5Y_b": round(b["median_equity_value_5Y_b"], 1), "RV_Growth_Gap": round(b["gap_metrics"]["RV_Growth_Gap"], 4), "Price_Expectation_Gap": round(b["gap_metrics"]["Price_Expectation_Gap"], 4),
                        "convergence_stable": (o.get("convergence") or {}).get("stable"), "robustness_pass": rb.get("pass"), "robustness_shares": [rb.get("same_sign_share"), rb.get("within_delta_tolerance_share")]},
            "paths_file": (o.get("paths_file") or "").replace("/data/workspace-invest/", ""), "valuation_crossover": (b.get("valuation_crossover") or {}).get("mode"), "basis_parity_margin_Y5": (b.get("basis_parity_margin") or {}).get("Y5")}


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
    old = fd / OLDFILE[tk]
    if old.exists():
        changes.append(f"{folder}/{OLDFILE[tk]}: удалить (прежняя версия; копия в from_imma и git)")
        if APPLY: old.unlink()
    sp = fd / "state.json"; raw = open(sp, encoding="utf-8", newline="").read(); st = json.loads(raw)
    idem = dump(st, raw.replace("\r\n", "\n")) == raw.replace("\r\n", "\n")
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
                st.setdefault("info_log", []).append({"timestamp": NOW, "kind": "calc", "summary": f"Переиздание {tk} {files[-1][1]} под Joint v1.1 (пакет IMMA 25.09; {DELTA[tk]}): принято (check_supersedes OK, валидатор 1.7.0 …-{VALRUN[tk]} pass); прежний файл {OLDFILE[tk]} удалён из папки (from_imma/git); mpc_inputs: Scenario_Company_Exposure_Patch_v1.1 применён, driver_taxonomy_version 1.2.1; прежние прогоны остаются записями воспроизводимости; новый нормативный прогон: " + ", ".join(e["run_id"] for e in new) + ""})
                st["updated"] = NOW
                with open(sp, "w", encoding="utf-8", newline="\r\n" if "\r\n" in raw else "\n") as fh:
                    fh.write(dump(st, raw.replace("\r\n", "\n")))
for c in changes: print("-", c)
print("режим:", "ЗАПИСЬ" if APPLY else "сухой прогон")
