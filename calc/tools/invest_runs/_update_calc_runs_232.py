"""Обновление calc_runs после перепрогона на company_mc 2.3.2 (24.09): в state.json каждой из 8 компаний добавляется запись
нового нормативного прогона (прежний остаётся историческим, помечается superseded_by), строка info_log. Формат файла
определяется по содержимому (однострочные наблюдения / inline verification_run_ids / CRLF) и сохраняется."""
import json
import re
import sys
from pathlib import Path

WS = Path(sys.argv[1]); APPLY = "--apply" in sys.argv
NEW = {"SPCX": ("spacex", "20260923T143532Z-company_mc-0484ce", "20260924T073336Z-company_mc-e55d7d"), "NBIS": ("nbis", "20260923T143929Z-company_mc-28c1e0", "20260924T073647Z-company_mc-0daf30"),
       "NVDA": ("nvda", "20260923T144500Z-company_mc-4a7d0d", "20260924T073919Z-company_mc-d5afc5"), "HOOD": ("hood", "20260923T211400Z-company_mc-6fb7ec", "20260924T074150Z-company_mc-038894"),
       "RKLB": ("rklb", "20260923T211620Z-company_mc-dbbce2", "20260924T074358Z-company_mc-224958"), "LLY": ("lly", "20260923T220341Z-company_mc-e5a5c8", "20260924T074630Z-company_mc-89318c"),
       "META": ("meta", "20260924T062553Z-company_mc-410567", "20260924T074844Z-company_mc-965cab"), "ASML": ("asml", "20260924T062843Z-company_mc-7106fc", "20260924T075104Z-company_mc-aa8132")}
NOW = "2026-09-24T08:00:00Z"


def dump(st: dict, raw: str) -> str:
    one_line = bool(re.search(r'\n\s*\{"kpi_id": ', raw))
    inline_ids = bool(re.search(r'"verification_run_ids": \[[ 	]*"', raw))
    st2 = dict(st); obs = st.get("kpi_observations") or []
    if one_line and obs:
        st2["kpi_observations"] = [f"@@OBS{i}@@" for i in range(len(obs))]
    txt = json.dumps(st2, ensure_ascii=False, indent=2) + "\n"
    if one_line:
        for i, o in enumerate(obs):
            txt = txt.replace(f'"@@OBS{i}@@"', json.dumps(o, ensure_ascii=False))
    if inline_ids:
        txt = re.sub(r'"verification_run_ids": \[\n((?:[ \t]*"[^"\n]*",?\n)+)[ \t]*\]', lambda m: '"verification_run_ids": [' + ", ".join(x.strip().rstrip(",") for x in m.group(1).strip().split("\n")) + "]", txt)
    return txt if raw.endswith("\n") else txt.rstrip("\n")   # файл без завершающего перевода строки (дозор) — сохраняем как есть


for tk, (folder, old_id, new_id) in NEW.items():
    sp = WS / "portfolio" / folder / "state.json"; raw = open(sp, encoding="utf-8", newline="").read(); st = json.loads(raw)
    t = raw.replace("\r\n", "\n")
    if dump(st, t) != t:
        print(f"- {folder}: НЕ идемпотентен для дампа — пропуск"); continue
    runs = st.setdefault("calc_runs", [])
    if any(e.get("run_id") == new_id for e in runs):
        print(f"- {folder}: уже есть"); continue
    old = next((e for e in runs if e.get("run_id") == old_id), None)
    r = json.load(open(WS / "portfolio/_runs" / f"{new_id}.json", encoding="utf-8")); o = r["outputs"]; b = o["base"]; q = b["return"]["CAGR_5Y_quantiles"]; rb = o.get("robustness") or {}
    entry = {"run_id": new_id, "model": "company_mc", "version": o.get("model_version"), "timestamp": new_id[:15],
             "spec": (old or {}).get("spec") or "Company_Conditional_Monte_Carlo_Specification_v1.1.3", "calibration": (old or {}).get("calibration"),
             "purpose": "нормативный прогон после исправления движка 2.3.2 (собственные розыгрыши от (seed, ticker); сводка компании изменилась в пределах MC-шума); совместные пути для портфеля",
             "supersedes": old_id, "equity_value_0_b": round(r["inputs"]["equity_value_0"] / 1e9, 1), "paths": r["inputs"].get("paths") or 500000, "seed": r["seed"],
             "summary": {"median_CAGR_3Y": round(b["return"]["median_CAGR_3Y"], 4), "median_CAGR_5Y": round(b["return"]["median_CAGR_5Y"], 4), "median_CAGR_8Y": round(b["return"]["median_CAGR_8Y"], 4),
                         "CAGR_5Y_q05_q95": [round(q["0.05"], 3), round(q["0.95"], 3)], "P_2x_5Y": round(b["return"]["P_2x_5Y"], 4), "P_loss_gt_30pct_5Y": round(b["downside"]["P_loss_gt_30pct_5Y"], 4),
                         "P_loss_gt_50pct_5Y": round(b["downside"]["P_loss_gt_50pct_5Y"], 4), "ES5": round(b["downside"]["expected_shortfall_5pct_5Y"], 4),
                         "median_equity_value_5Y_b": round(b["median_equity_value_5Y_b"], 1), "RV_Growth_Gap": round(b["gap_metrics"]["RV_Growth_Gap"], 4), "Price_Expectation_Gap": round(b["gap_metrics"]["Price_Expectation_Gap"], 4),
                         "convergence_stable": (o.get("convergence") or {}).get("stable"), "robustness_pass": rb.get("pass"), "robustness_shares": [rb.get("same_sign_share"), rb.get("within_delta_tolerance_share")]},
             "paths_file": (o.get("paths_file") or "").replace("/data/workspace-invest/", ""), "valuation_crossover": (b.get("valuation_crossover") or {}).get("mode")}
    if old is not None:
        old["superseded_by"] = new_id
    runs.append(entry)
    st.setdefault("info_log", []).append({"timestamp": NOW, "kind": "calc", "summary": f"Нормативный прогон company_mc 2.3.2 {new_id} (исправление: собственные розыгрыши компании от (seed, ticker); прежний {old_id} — исторический, сводка в пределах MC-шума)."})
    st["updated"] = NOW
    print(f"- {folder}: +{new_id} (supersedes {old_id})")
    if APPLY:
        with open(sp, "w", encoding="utf-8", newline="\r\n" if "\r\n" in raw else "\n") as fh:
            fh.write(dump(st, t))
print("режим:", "ЗАПИСЬ" if APPLY else "сухой прогон")
